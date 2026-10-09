"""Centralized Market Data Ingestion and Delta Synchronization Engine."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Sequence
from urllib.parse import quote as url_quote
import httpx

from database.candle_repo import (
    get_all_active_instruments,
    get_latest_candle_timestamps,
    upsert_candles,
    upsert_instruments,
)
from scanner.universe import get_nse_equity_universe


def map_timeframe(unit: str, interval: int) -> str:
    """Standardize timeframe string e.g. '1d', '1m', '5m', '15m', '1h'."""
    unit_map = {"days": "d", "day": "d", "minutes": "m", "minute": "m", "hours": "h", "hour": "h", "weeks": "w", "months": "M"}
    u = unit_map.get(unit.lower(), unit)
    return f"{interval}{u}" if interval > 1 or u != "d" else "1d"


INDIA = timezone(timedelta(hours=5, minutes=30))


def history_windows(start, end, unit, interval):
    # Conservative inclusive windows fit even the shortest calendar month/quarter.
    days = 28 if unit == "minutes" and interval <= 15 else 89 if unit in {"minutes", "hours"} else 3650
    while start <= end:
        stop = min(end, start + timedelta(days=days - 1))
        yield start, stop
        start = stop + timedelta(days=1)


def candle_closed(ts, unit, interval, now):
    if unit == "days":
        # Daily bars are admitted on the following local date until calendars exist.
        return ts.astimezone(INDIA).date() < now.astimezone(INDIA).date()
    duration = timedelta(minutes=interval) if unit == "minutes" else timedelta(hours=interval)
    return ts + duration + timedelta(seconds=5) <= now


class MarketSyncService:
    """Central sync manager responsible for keeping the time-series DB up to date."""

    def __init__(self, get_token_fn: Callable[[], str]):
        self.get_token = get_token_fn
        self._sync_lock = asyncio.Lock()

    async def sync_universe(self) -> int:
        """Fetch daily master and synchronize instruments table."""
        universe = await get_nse_equity_universe()
        records = [
            {
                "instrument_key": item["key"],
                "symbol": item["symbol"],
                "name": item["name"],
                "exchange": item["exchange"],
                "segment": item["segment"],
                "isin": item.get("isin"),
                "instrument_type": item.get("instrument_type", "EQ"),
                "is_active": True,
            }
            for item in universe
        ]
        count = await upsert_instruments(records)
        return count

    async def sync_candles_for_universe(
        self,
        *,
        unit: str = "days",
        interval: int = 1,
        lookback_days: int = 730,  # Default 2 years for 1d
        concurrency: int = 15,
        target_instruments: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Delta-sync historical and recent candles for all active universe instruments."""
        if unit not in {"minutes", "hours", "days"} or not (1 <= interval <= {"minutes": 300, "hours": 5, "days": 1}[unit]):
            raise ValueError("Unsupported sync timeframe")
        if not 1 <= concurrency <= 15 or not 1 <= lookback_days <= 3653:
            raise ValueError("Invalid concurrency or lookback")
        async with self._sync_lock:
            token = self.get_token()
            timeframe = map_timeframe(unit, interval)
            today = datetime.now(INDIA).date()
            default_start_date = today - timedelta(days=lookback_days)

            # 1. Sync universe first if needed
            instruments = list(target_instruments) if target_instruments is not None else await get_all_active_instruments()
            if not instruments and target_instruments is None:
                await self.sync_universe()
                instruments = await get_all_active_instruments()

            latest_map = await get_latest_candle_timestamps(timeframe)
            semaphore = asyncio.Semaphore(concurrency)
            stats = {"total": len(instruments), "synced": 0, "failed": 0, "candles_changed": 0}
            errors = []
            # Reuse connections across the entire sync. Historical APIs are date-based,
            # so refetch a small overlap and let conditional upserts discard duplicates.
            async with httpx.AsyncClient(timeout=30) as client:
                async def sync_one(instrument):
                    key = instrument["key"]
                    last_ts = latest_map.get(key)
                    if last_ts is not None:
                        if last_ts.tzinfo is None:
                            last_ts = last_ts.replace(tzinfo=timezone.utc)
                        start = last_ts.astimezone(INDIA).date() - timedelta(days=2)
                    else:
                        start = default_start_date
                    earliest = date(2022, 1, 1) if unit in {"minutes", "hours"} else date(2000, 1, 1)
                    start = max(start, earliest)
                    encoded_key = url_quote(key, safe="")
                    base = "https://api.upstox.com/v3/historical-candle"
                    urls = [f"{base}/{encoded_key}/{unit}/{interval}/{end}/{begin}"
                            for begin, end in history_windows(start, today - timedelta(days=1), unit, interval)]
                    if unit in {"minutes", "hours"}:
                        urls.append(f"{base}/intraday/{encoded_key}/{unit}/{interval}")
                    async with semaphore:
                        try:
                            for url in urls:
                                response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                                response.raise_for_status()
                                payload = response.json()
                                if payload.get("status") != "success":
                                    raise ValueError("Provider did not return a successful candle response")
                                records = []
                                now = datetime.now(timezone.utc)
                                for row in payload["data"]["candles"]:
                                    ts = datetime.fromisoformat(row[0].replace("Z", "+00:00")).astimezone(timezone.utc)
                                    if not candle_closed(ts, unit, interval, now):
                                        continue
                                    records.append({"instrument_key": key, "timeframe": timeframe,
                                        "timestamp": ts, "open": float(row[1]), "high": float(row[2]),
                                        "low": float(row[3]), "close": float(row[4]), "volume": int(row[5])})
                                stats["candles_changed"] += await upsert_candles(records)
                            stats["synced"] += 1
                        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                            stats["failed"] += 1
                            errors.append({"instrument_key": key, "error": type(exc).__name__})
                for offset in range(0, len(instruments), 50):
                    await asyncio.gather(*(sync_one(item) for item in instruments[offset:offset + 50]))
            return {"timeframe": timeframe, "stats": stats, "errors": errors,
                    "completed_at": datetime.now(timezone.utc).isoformat()}
