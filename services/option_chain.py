"""Normalize Upstox option snapshots without persisting derivative instruments."""
from datetime import date, datetime, timedelta, timezone
import math

import httpx
from fastapi import HTTPException

INDIA = timezone(timedelta(hours=5, minutes=30))


async def provider_rows(request, token, path, params):
    try:
        payload = await request("https://api.upstox.com/v2/option/" + path,
                                headers={"Authorization": f"Bearer {token}"}, params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Upstox option data is temporarily unavailable. Please retry.") from exc
    if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(payload.get("data"), list):
        raise HTTPException(502, "Upstox returned an invalid option response.")
    if any(not isinstance(row, dict) for row in payload["data"]):
        raise HTTPException(502, "Upstox returned invalid option rows.")
    return payload["data"]


async def expiries(request, token, key):
    rows = await provider_rows(request, token, "contract", {"instrument_key": key})
    today = datetime.now(INDIA).date()
    dates = set()
    for row in rows:
        if row.get("underlying_key") != key:
            continue
        try:
            expiry = date.fromisoformat(row["expiry"])
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(502, "Upstox returned an invalid option expiry.") from exc
        if expiry >= today:
            dates.add(expiry.isoformat())
    return {"expiries": sorted(dates)}


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def leg(raw):
    raw = raw if isinstance(raw, dict) else {}
    market = raw.get("market_data") or {}
    greeks = raw.get("option_greeks") or {}
    if not isinstance(market, dict) or not isinstance(greeks, dict):
        raise HTTPException(502, "Upstox returned invalid option market data.")
    return {**{k: number(market.get(k)) for k in ("ltp", "oi", "volume", "bid_price", "ask_price")},
            **{k: number(greeks.get(k)) for k in ("iv", "delta", "gamma", "theta", "vega")}}


async def chain(request, token, key, expiry):
    if expiry < datetime.now(INDIA).date():
        raise HTTPException(400, "Select a current or upcoming expiry.")
    rows = await provider_rows(request, token, "chain", {
        "instrument_key": key, "expiry_date": expiry.isoformat()})
    result = []
    spot = None
    seen = set()
    for row in rows:
        strike = number(row.get("strike_price"))
        if row.get("underlying_key") != key or row.get("expiry") != expiry.isoformat() or strike is None or strike <= 0 or strike in seen:
            raise HTTPException(502, "Upstox returned inconsistent option-chain data.")
        seen.add(strike)
        price = number(row.get("underlying_spot_price"))
        if spot is None and price is not None and price > 0:
            spot = price
        result.append({"strike": strike, "call": leg(row.get("call_options")), "put": leg(row.get("put_options"))})
    result.sort(key=lambda row: row["strike"])
    atm = min(result, key=lambda row: abs(row["strike"] - spot))["strike"] if result and spot is not None else None
    return {"rows": result, "spot": spot, "atmStrike": atm, "expiry": expiry.isoformat(),
            "receivedAt": datetime.now(timezone.utc).isoformat()}
