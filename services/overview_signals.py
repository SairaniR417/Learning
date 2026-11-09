"""Overview breadth from stored candles, with explicit history repair jobs."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from math import isfinite

from fastapi import APIRouter, HTTPException
from database.candle_repo import load_recent_candles_polars, create_ingestion_job, get_ingestion_job, update_ingestion_job
from scanner.universe import get_fno_stocks
from services.market_sync import INDIA, nse_daily_closed
from services.option_analysis import weekly_candles

router = APIRouter(prefix="/api/market")
FRAMES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440, "1w": 10080}
_repair_lock = asyncio.Lock()
_repair_jobs = {}


async def repair_history(sync_service, timeframe, background_tasks):
    if timeframe not in FRAMES:
        raise HTTPException(400, "Select a supported overview timeframe.")
    frame = "1d" if timeframe == "1w" else timeframe
    async with _repair_lock:
        if frame in _repair_jobs:
            job = await get_ingestion_job(_repair_jobs[frame])
            if job and job["status"] in {"pending", "running"}:
                return dict(job_id=job["id"], status="sync_started")
        snapshot = await overview_signals(timeframe)
        keys = {s["key"] for s in snapshot["stocks"] if s["bars"] < 51}
        if not keys:
            return dict(job_id=None, status="complete")
        targets = [s for s in get_fno_stocks() if s["key"] in keys]
        days = 730 if frame == "1d" else 7 if frame == "1m" else 28
        now = datetime.now(timezone.utc)
        job_id = await create_ingestion_job(frame, now - timedelta(days=days), now)
        _repair_jobs[frame] = job_id

        async def run():
            try:
                await sync_service.sync_universe()
                await sync_service.sync_candles_for_universe(
                    unit="days" if frame == "1d" else "hours" if frame == "1h" else "minutes",
                    interval=1 if frame in {"1d", "1h"} else FRAMES[frame],
                    lookback_days=days, concurrency=3, target_instruments=targets,
                    job_id=job_id, backfill=True)
            except Exception:
                logging.getLogger(__name__).exception("Overview history repair failed")
                await update_ingestion_job(job_id, "failed", "Could not load history. Check Upstox connection and retry.")
        background_tasks.add_task(run)
        return dict(job_id=job_id, status="sync_started")


def completed(row, frame, now):
    ts = row["timestamp"]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
        row["timestamp"] = ts
    if frame == "1d":
        return nse_daily_closed(ts, now)
    if frame == "1w":
        return ts + timedelta(days=7) <= now
    local = ts.astimezone(INDIA)
    start = local.replace(hour=9, minute=15, second=0, microsecond=0)
    end = local.replace(hour=15, minute=30, second=0, microsecond=0)
    if not start <= local < end:
        return False
    return min(ts + timedelta(minutes=FRAMES[frame]), end) + timedelta(seconds=5) <= now


def valid(row):
    try:
        o, h, l, c, v = (float(row[k]) for k in ("open", "high", "low", "close", "volume"))
        return all(isfinite(x) for x in (o, h, l, c, v)) and 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0
    except (ValueError, TypeError, KeyError):
        return False


def position(price, reference):
    return None if reference is None else "above" if price > reference else "below" if price < reference else "at"


def calculate(rows, frame, now):
    rows = sorted((r for r in rows if completed(r, "1d" if frame == "1w" else frame, now)), key=lambda r: r["timestamp"])
    # Invalid OHLCV breaks the window instead of joining prices across bad data.
    last_invalid = max((i for i, r in enumerate(rows) if not valid(r)), default=-1)
    rows = rows[last_invalid + 1:]
    history_note = "Invalid OHLCV interrupted history. " if last_invalid >= 0 else ""
    if frame == "1w":
        rows = [r for r in weekly_candles(rows) if completed(r, frame, now)]
        # The first loaded week may have been cut off by the bounded daily query.
        rows = rows[1:]
    if not rows:
        return dict(price=None, asOf=None, bars=0, vwap=None, sma20=None, sma50=None,
                    vwapPosition=None, sma20Position=None, sma50Position=None, maTrend=None, crossover=None,
                    historyNote=history_note + "No completed stored candles for this timeframe. Load history to calculate signals.")
    closes = [float(r["close"]) for r in rows]
    price = closes[-1]
    sma20 = sum(closes[-20:]) / 20 if len(rows) >= 20 else None
    sma50 = sum(closes[-50:]) / 50 if len(rows) >= 50 else None
    window = rows[-20:] if frame in {"1d", "1w"} else [r for r in rows if r["timestamp"].astimezone(INDIA).date() == rows[-1]["timestamp"].astimezone(INDIA).date()]
    volume = sum(float(r["volume"]) for r in window)
    vwap = sum(((r["high"] + r["low"] + r["close"]) / 3) * r["volume"] for r in window) / volume if volume > 0 and (frame not in {"1d", "1w"} or len(window) == 20) else None
    cross = None
    if len(rows) >= 51:
        previous20, previous50 = sum(closes[-21:-1]) / 20, sum(closes[-51:-1]) / 50
        if previous20 <= previous50 and sma20 > sma50:
            cross = "bullish"
        elif previous20 >= previous50 and sma20 < sma50:
            cross = "bearish"
    return dict(price=price, asOf=rows[-1]["timestamp"].isoformat(), bars=len(rows), vwap=vwap,
                sma20=sma20, sma50=sma50, vwapPosition=position(price, vwap),
                sma20Position=position(price, sma20), sma50Position=position(price, sma50),
                maTrend=position(sma20, sma50) if sma20 is not None else None, crossover=cross,
                historyNote=history_note + (f"Only {len(rows)} completed bars; SMA 20 needs 20, SMA 50 needs 50 and crossovers need 51. " if len(rows) < 51 else "") +
                ("VWAP needs positive traded volume. " if volume <= 0 else ""))


@router.get("/overview-signals")
async def overview_signals(timeframe: str = "1d"):
    if timeframe not in FRAMES:
        raise HTTPException(400, "Select 1m, 5m, 15m, 30m, 1h, 1d or 1w.")
    now = datetime.now(timezone.utc)
    df = await load_recent_candles_polars("1d" if timeframe == "1w" else timeframe, per_instrument=800 if timeframe == "1m" else 400)
    grouped = {}
    for row in df.iter_rows(named=True):
        grouped.setdefault(row["instrument_key"], []).append(row)
    stocks = [{**{k: s[k] for k in ("key", "symbol", "name", "exchange")},
               **calculate(grouped.get(s["key"], []), timeframe, now)} for s in get_fno_stocks()]
    return dict(timeframe=timeframe, source="stored", fetchedAt=now.isoformat(),
                vwapLabel="20-bar VWAP" if timeframe in {"1d", "1w"} else "Session VWAP",
                stocks=stocks)
