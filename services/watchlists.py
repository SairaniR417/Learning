"""Local-user watchlists, one-shot price alerts, and a persistent notification inbox."""
import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update, func
from database.connection import async_session_factory
from database.models import UserWatchlist, PriceAlert, AlertNotification

from scanner.universe import fno_keys, get_fno_stocks, require_fno_key

router = APIRouter(prefix="/api/watchlists")
log = logging.getLogger(__name__)
quote_fetcher = None
monitor = None
CONDITIONS = {"above": "at or above", "below": "at or below", "cross_up": "crossed above", "cross_down": "crossed below"}


def utc_iso(value):
    # SQLite drops timezone metadata; all alert timestamps are stored in UTC.
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


class WatchEntry(BaseModel):
    key: str = Field(pattern=r"^[A-Z0-9_]+\|[A-Za-z0-9 ._-]+$", max_length=200)
    symbol: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    exchange: str = Field(min_length=1, max_length=30)
    section: str = Field(default="Stocks", min_length=1, max_length=60)
    flag: Literal["", "red", "green", "yellow", "blue"] = ""

    @model_validator(mode="after")
    def allowed_stock(self):
        stock = next((s for s in get_fno_stocks() if s["key"] == self.key), None)
        if stock is None:
            raise ValueError("Select a stock from the saved F&O list.")
        self.symbol, self.name, self.exchange = stock["symbol"], stock["name"], stock["exchange"]
        return self


class WatchlistInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sections: list[str] = Field(default_factory=lambda: ["Stocks"], min_length=1, max_length=30)
    entries: list[WatchEntry] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_content(self):
        self.name = self.name.strip()
        if not self.name or any(not s.strip() or len(s) > 60 for s in self.sections):
            raise ValueError("List and section names cannot be blank; sections are limited to 60 characters.")
        if len(set(self.sections)) != len(self.sections):
            raise ValueError("Section names must be unique.")
        if len({entry.key for entry in self.entries}) != len(self.entries):
            raise ValueError("A symbol can appear only once per list.")
        if any(entry.section not in self.sections for entry in self.entries):
            raise ValueError("Every symbol must belong to a section in this list.")
        return self


class AlertInput(BaseModel):
    key: str = Field(pattern=r"^[A-Z0-9_]+\|[A-Za-z0-9 ._-]+$", max_length=200)
    symbol: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    exchange: str = Field(min_length=1, max_length=30)
    condition: Literal["above", "below", "cross_up", "cross_down"]
    target: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def allowed_stock(self):
        stock = next((s for s in get_fno_stocks() if s["key"] == self.key), None)
        if stock is None:
            raise ValueError("Select a stock from the saved F&O list.")
        self.symbol, self.name, self.exchange = stock["symbol"], stock["name"], stock["exchange"]
        return self


def serialize_list(row):
    content = json.loads(row.content_json)
    content["entries"] = [entry for entry in content.get("entries", []) if entry.get("key") in fno_keys()]
    return {"id": row.id, "name": row.name, **content}


def serialize_alert(row):
    return {"id": row.id, "key": row.instrument_key, "symbol": row.symbol, "name": row.name, "exchange": row.exchange,
            "condition": row.condition, "target": row.target, "active": row.active, "lastPrice": row.last_price,
            "triggeredAt": utc_iso(row.triggered_at) if row.triggered_at else None}


@router.get("")
async def get_lists():
    async with async_session_factory() as session:
        rows = (await session.scalars(select(UserWatchlist).order_by(UserWatchlist.id))).all()
        return {"lists": [serialize_list(row) for row in rows]}


@router.post("")
async def create_list(body: WatchlistInput):
    async with async_session_factory() as session:
        if (await session.scalar(select(func.count()).select_from(UserWatchlist))) >= 30:
            raise HTTPException(400, "A maximum of 30 watchlists is supported.")
        row = UserWatchlist(name=body.name, content_json=json.dumps(body.model_dump(exclude={"name"})))
        session.add(row)
        await session.commit()
        return serialize_list(row)


@router.put("/{list_id:int}")
async def save_list(list_id: int, body: WatchlistInput):
    async with async_session_factory() as session:
        row = await session.get(UserWatchlist, list_id)
        if row is None:
            raise HTTPException(404, "Watchlist not found.")
        row.name = body.name
        row.content_json = json.dumps(body.model_dump(exclude={"name"}))
        await session.commit()
        return serialize_list(row)


@router.delete("/{list_id:int}")
async def delete_list(list_id: int):
    async with async_session_factory() as session:
        row = await session.get(UserWatchlist, list_id)
        if row is None:
            raise HTTPException(404, "Watchlist not found.")
        await session.delete(row)
        await session.commit()
    return {"deleted": True}


@router.get("/quotes")
async def watch_quotes(keys: str = Query(min_length=1, max_length=20000)):
    import re
    values = list(dict.fromkeys(keys.split(',')))
    if len(values) > 100 or any(not re.fullmatch(r"[A-Z0-9_]+\|[A-Za-z0-9 ._-]+", k) for k in values):
        raise HTTPException(400, "Provide between 1 and 100 valid instrument keys.")
    for key in values:
        require_fno_key(key)
    if quote_fetcher is None:
        raise HTTPException(503, "Quote service unavailable.")
    return {"quotes": await quote_fetcher(values), "receivedAt": datetime.now(timezone.utc).isoformat()}


@router.get("/alerts")
async def get_alerts():
    async with async_session_factory() as session:
        rows = (await session.scalars(select(PriceAlert).where(PriceAlert.instrument_key.in_(fno_keys())).order_by(PriceAlert.active.desc(), PriceAlert.id.desc()).limit(500))).all()
        return {"alerts": [serialize_alert(row) for row in rows]}


@router.post("/alerts")
async def create_alert(body: AlertInput):
    async with async_session_factory() as session:
        if (await session.scalar(select(func.count()).select_from(PriceAlert).where(PriceAlert.active.is_(True), PriceAlert.instrument_key.in_(fno_keys())))) >= 100:
            raise HTTPException(400, "A maximum of 100 active alerts is supported.")
        row = PriceAlert(instrument_key=body.key, symbol=body.symbol, name=body.name, exchange=body.exchange, condition=body.condition, target=body.target)
        session.add(row)
        await session.commit()
        return serialize_alert(row)


@router.delete("/alerts/{alert_id}")
async def cancel_alert(alert_id: int):
    async with async_session_factory() as session:
        row = await session.get(PriceAlert, alert_id)
        if row is None:
            raise HTTPException(404, "Alert not found.")
        row.active = False
        await session.commit()
    return {"cancelled": True}


@router.get("/notifications")
async def notifications():
    async with async_session_factory() as session:
        rows = (await session.scalars(select(AlertNotification).where(AlertNotification.instrument_key.in_(fno_keys())).order_by(AlertNotification.id.desc()).limit(100))).all()
        unread = await session.scalar(select(func.count()).select_from(AlertNotification).where(AlertNotification.read.is_(False), AlertNotification.instrument_key.in_(fno_keys())))
        return {"notifications": [{"id": r.id, "key": r.instrument_key, "symbol": r.symbol, "name": r.name, "exchange": r.exchange,
                 "message": r.message, "price": r.price, "createdAt": utc_iso(r.created_at), "read": r.read} for r in rows],
                "unread": unread, "monitor": {"running": bool(monitor and monitor.task and not monitor.task.done()),
                "lastCheck": monitor.last_check if monitor else None, "error": monitor.error if monitor else "Alert monitoring has not started."}}


@router.post("/notifications/read")
async def mark_notifications_read():
    async with async_session_factory() as session:
        await session.execute(update(AlertNotification).where(AlertNotification.read.is_(False), AlertNotification.instrument_key.in_(fno_keys())).values(read=True))
        await session.commit()
    return {"read": True}


@router.post("/notifications/{notification_id}/read")
async def mark_one_read(notification_id: int):
    async with async_session_factory() as session:
        await session.execute(update(AlertNotification).where(AlertNotification.id == notification_id).values(read=True))
        await session.commit()
    return {"read": True}


def condition_met(condition: str, price: float, target: float, previous: float | None):
    if condition == "above":
        return price >= target
    if condition == "below":
        return price <= target
    if previous is None:
        return False
    if condition == "cross_up":
        return previous <= target < price
    return previous >= target > price


class AlertMonitor:
    """Persist notifications atomically; monitoring survives closing the browser, not stopping the API."""
    def __init__(self, fetch_quotes, interval=30):
        self.fetch_quotes = fetch_quotes
        self.interval = interval
        self.task = None
        self.last_check = None
        self.error = ""

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run(self):
        while True:
            try:
                await self.check()
                self.error = ""
                self.last_check = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                self.error = getattr(exc, "detail", None) or "Price checks unavailable. Monitoring will retry automatically."
                log.warning("Alert monitor check failed: %s", type(exc).__name__)
            await asyncio.sleep(self.interval)

    async def check(self):
        async with async_session_factory() as session:
            alerts = (await session.scalars(select(PriceAlert).where(PriceAlert.active.is_(True), PriceAlert.instrument_key.in_(fno_keys())))).all()
        if not alerts:
            return
        prices = await self.fetch_quotes(list({a.instrument_key for a in alerts}))
        missing = False
        async with async_session_factory() as session:
            for alert in alerts:
                quote = prices.get(alert.instrument_key)
                price = quote.get("price") if quote else None
                if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
                    missing = True
                    continue
                triggered = condition_met(alert.condition, price, alert.target, alert.last_price)
                when = datetime.now(timezone.utc)
                values = {"last_price": price}
                if triggered:
                    values.update(active=False, triggered_at=when)
                changed = await session.execute(update(PriceAlert).where(PriceAlert.id == alert.id, PriceAlert.active.is_(True), PriceAlert.instrument_key.in_(fno_keys())).values(**values))
                if triggered and changed.rowcount:
                    session.add(AlertNotification(alert_id=alert.id, instrument_key=alert.instrument_key, symbol=alert.symbol, name=alert.name,
                        exchange=alert.exchange, message=f"{alert.symbol} {CONDITIONS[alert.condition]} {alert.target:,.2f}. Observed price: {price:,.2f}.", price=price, created_at=when))
            await session.commit()
        if missing:
            raise HTTPException(502, "Some alert prices are unavailable. Monitoring will retry automatically.")
