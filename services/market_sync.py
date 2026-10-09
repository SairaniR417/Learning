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
        async with self._sync_lock:
            token = self.get_token()
            timeframe = map_timeframe(unit, interval)
            today = datetime.now(timezone.utc).date()
            default_start_date = today - timedelta(days=lookback_days)

            # 1. Sync universe first if needed
            instruments = target_instruments or await get_all_active_instruments()
            if not instruments:
                await self.sync_universe()
                instruments = await get_all_active_instruments()

            # 2. Get latest timestamp for each symbol in DB
            latest_map = await get_latest_candle_timestamps(timeframe)

            semaphore = asyncio.Semaphore(concurrency)
            stats = {"total": len(instruments), "synced": 0, "skipped": 0, "failed": 0, "candles_added": 0}

            async def sync_one(instrument: dict[str, Any]):
                key = instrument["key"]
                last_ts = latest_map.get(key)

                # Determine delta start date
                if last_ts is not None:
                    # Convert last_ts to date
                    last_date = last_ts.date() if isinstance(last_ts, datetime) else last_ts
                    if last_date >= today:
                        # Already up to date
                        stats["skipped"] += 1
                        return
                    # Fetch from last recorded date to today
                    from_date = last_date
                else:
                    from_date = default_start_date

                encoded_key = url_quote(key, safe="")
                url = f"https://api.upstox.com/v3/historical-candle/{encoded_key}/{unit}/{interval}/{today.isoformat()}/{from_date.isoformat()}"

                async with semaphore:
                    try:
                        async with httpx.AsyncClient(timeout=15) as client:
                            response = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
                            if response.status_code == 200:
                                payload = response.json()
                                raw_candles = payload.get("data", {}).get("candles", [])
                                if raw_candles:
                                    candle_records = []
                                    for r in raw_candles:
                                        ts = datetime.fromisoformat(r[0].replace("Z", "+00:00"))
                                        candle_records.append({
                                            "instrument_key": key,
                                            "timeframe": timeframe,
                                            "timestamp": ts,
                                            "open": float(r[1]),
                                            "high": float(r[2]),
                                            "low": float(r[3]),
                                            "close": float(r[4]),
                                            "volume": int(r[5]),
                                        })
                                    added = await upsert_candles(candle_records)
                                    stats["candles_added"] += added
                                stats["synced"] += 1
                            else:
                                stats["failed"] += 1
                    except Exception:
                        stats["failed"] += 1

            # Execute parallel delta ingestion in batches
            batch_size = 50
            for i in range(0, len(instruments), batch_size):
                batch = instruments[i : i + batch_size]
                await asyncio.gather(*(sync_one(inst) for inst in batch))

            return {
                "timeframe": timeframe,
                "stats": stats,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
