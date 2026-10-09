"""High-performance candle and instrument repository with bulk upserts."""

from datetime import datetime, timezone
import json
from typing import Any, Sequence
import polars as pl
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import async_session_factory, engine
from database.models import Instrument, MarketCandle, StrategyCache


async def upsert_instruments(instruments: Sequence[dict[str, Any]]) -> int:
    """Bulk upsert instruments list."""
    if not instruments:
        return 0

    async with async_session_factory() as session:
        is_sqlite = "sqlite" in str(engine.url)
        insert_fn = sqlite_insert if is_sqlite else pg_insert

        # Process in batches of 500
        batch_size = 500
        for i in range(0, len(instruments), batch_size):
            batch = instruments[i : i + batch_size]
            stmt = insert_fn(Instrument).values(batch)
            if is_sqlite:
                stmt = stmt.on_conflict_do_update(
                    index_elements=["instrument_key"],
                    set_={
                        "symbol": stmt.excluded.symbol,
                        "name": stmt.excluded.name,
                        "exchange": stmt.excluded.exchange,
                        "segment": stmt.excluded.segment,
                        "isin": stmt.excluded.isin,
                        "instrument_type": stmt.excluded.instrument_type,
                        "is_active": stmt.excluded.is_active,
                        "updated_at": datetime.now(timezone.utc),
                    },
                )
            else:
                stmt = stmt.on_conflict_do_update(
                    index_elements=["instrument_key"],
                    set_={
                        "symbol": stmt.excluded.symbol,
                        "name": stmt.excluded.name,
                        "exchange": stmt.excluded.exchange,
                        "segment": stmt.excluded.segment,
                        "isin": stmt.excluded.isin,
                        "instrument_type": stmt.excluded.instrument_type,
                        "is_active": stmt.excluded.is_active,
                        "updated_at": datetime.now(timezone.utc),
                    },
                )
            await session.execute(stmt)
        await session.commit()
    return len(instruments)


async def upsert_candles(candles: Sequence[dict[str, Any]]) -> int:
    """Bulk upsert candles with high-throughput batching."""
    if not candles:
        return 0

    async with async_session_factory() as session:
        is_sqlite = "sqlite" in str(engine.url)
        insert_fn = sqlite_insert if is_sqlite else pg_insert

        batch_size = 1000
        for i in range(0, len(candles), batch_size):
            batch = candles[i : i + batch_size]
            stmt = insert_fn(MarketCandle).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["instrument_key", "timeframe", "timestamp"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                },
            )
            await session.execute(stmt)
        await session.commit()
    return len(candles)


async def get_latest_candle_timestamps(timeframe: str) -> dict[str, datetime]:
    """Return a mapping of instrument_key -> latest candle timestamp in DB."""
    async with async_session_factory() as session:
        stmt = (
            select(MarketCandle.instrument_key, func.max(MarketCandle.timestamp))
            .where(MarketCandle.timeframe == timeframe)
            .group_by(MarketCandle.instrument_key)
        )
        result = await session.execute(stmt)
        return {row[0]: row[1] for row in result.fetchall() if row[1] is not None}


async def get_all_active_instruments() -> list[dict[str, Any]]:
    """Return all active NSE equity instruments from DB."""
    async with async_session_factory() as session:
        stmt = select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "key": row.instrument_key,
                "symbol": row.symbol,
                "name": row.name,
                "exchange": row.exchange,
                "segment": row.segment,
                "isin": row.isin,
            }
            for row in rows
        ]


async def load_candles_polars(timeframe: str, min_candles: int = 200) -> pl.DataFrame:
    """Load time-series candles directly into a Polars DataFrame for fast vectorized scanning."""
    async with async_session_factory() as session:
        stmt = (
            select(
                MarketCandle.instrument_key,
                MarketCandle.timestamp,
                MarketCandle.open,
                MarketCandle.high,
                MarketCandle.low,
                MarketCandle.close,
                MarketCandle.volume,
            )
            .where(MarketCandle.timeframe == timeframe)
            .order_by(MarketCandle.instrument_key, MarketCandle.timestamp.asc())
        )
        result = await session.execute(stmt)
        rows = result.fetchall()

        if not rows:
            return pl.DataFrame(
                schema={
                    "instrument_key": pl.Utf8,
                    "timestamp": pl.Datetime("us", "UTC"),
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Int64,
                }
            )

        data = {
            "instrument_key": [r[0] for r in rows],
            "timestamp": [r[1] for r in rows],
            "open": [float(r[2]) for r in rows],
            "high": [float(r[3]) for r in rows],
            "low": [float(r[4]) for r in rows],
            "close": [float(r[5]) for r in rows],
            "volume": [int(r[6]) for r in rows],
        }
        return pl.DataFrame(data)


async def get_cached_strategy_result(cache_key: str) -> dict[str, Any] | None:
    """Retrieve unexpired cached strategy results for concurrent users."""
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        stmt = select(StrategyCache).where(
            StrategyCache.cache_key == cache_key,
            StrategyCache.expires_at > now,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            return {
                "strategy_id": row.strategy_id,
                "timeframe": row.timeframe,
                "total_scanned": row.total_scanned,
                "total_matched": row.total_matched,
                "scanned_at": row.scanned_at.isoformat(),
                "results": json.loads(row.results_json),
                "cached": True,
            }
        return None


async def save_strategy_result_cache(
    cache_key: str,
    strategy_id: str,
    timeframe: str,
    params: dict[str, Any],
    results: list[dict[str, Any]],
    total_scanned: int,
    expires_at: datetime,
):
    """Save strategy scan result to shared cache."""
    is_sqlite = "sqlite" in str(engine.url)
    insert_fn = sqlite_insert if is_sqlite else pg_insert
    payload = {
        "cache_key": cache_key,
        "strategy_id": strategy_id,
        "timeframe": timeframe,
        "params_json": json.dumps(params, sort_keys=True),
        "results_json": json.dumps(results),
        "total_scanned": total_scanned,
        "total_matched": len(results),
        "scanned_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    }
    async with async_session_factory() as session:
        stmt = insert_fn(StrategyCache).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["cache_key"],
            set_={
                "results_json": stmt.excluded.results_json,
                "total_scanned": stmt.excluded.total_scanned,
                "total_matched": stmt.excluded.total_matched,
                "scanned_at": stmt.excluded.scanned_at,
                "expires_at": stmt.excluded.expires_at,
            },
        )
        await session.execute(stmt)
        await session.commit()
