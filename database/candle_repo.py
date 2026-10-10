"""Repositories for instrument metadata, OHLCV history, and strategy caching."""
from datetime import datetime, timezone
import json
from typing import Any, Sequence
import polars as pl
from sqlalchemy import delete, func, select, or_, true
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from database.connection import async_session_factory, engine
from database.models import Instrument, MarketCandle, StrategyCache, CandleRevision


def _insert_fn():
    return sqlite_insert if "sqlite" in str(engine.url) else pg_insert


async def upsert_instruments(instruments: Sequence[dict[str, Any]]) -> int:
    if not instruments:
        return 0
    prepared = [{
        "symbol": item["symbol"], "exchange": item.get("exchange", "NSE"),
        "instrument_type": item.get("instrument_type", "EQ"),
        "provider_instrument_key": item.get("provider_instrument_key") or item.get("instrument_key") or item.get("key"),
        "expiry_date": item.get("expiry_date"), "is_active": item.get("is_active", True),
    } for item in instruments]
    insert_fn = _insert_fn()
    async with async_session_factory() as session:
        for offset in range(0, len(prepared), 500):
            stmt = insert_fn(Instrument).values(prepared[offset:offset + 500])
            stmt = stmt.on_conflict_do_update(
                index_elements=["exchange", "provider_instrument_key"],
                set_={"symbol": stmt.excluded.symbol, "instrument_type": stmt.excluded.instrument_type,
                      "expiry_date": stmt.excluded.expiry_date, "is_active": stmt.excluded.is_active},
            )
            await session.execute(stmt)
        await session.commit()
    return len(prepared)


async def upsert_candles(candles: Sequence[dict[str, Any]]) -> int:
    if not candles:
        return 0
    unique = list({(c["instrument_key"], c["timeframe"], c["timestamp"]): c for c in candles}.values())
    async with async_session_factory() as session:
        keys = list({c["instrument_key"] for c in unique})
        result = await session.execute(select(Instrument.provider_instrument_key, Instrument.id).where(
            Instrument.provider_instrument_key.in_(keys)))
        ids = {key: instrument_id for key, instrument_id in result.all()}
        missing = set(keys) - ids.keys()
        if missing:
            raise ValueError(f"Unknown instrument keys in candle batch: {', '.join(sorted(missing)[:3])}")
        prepared = [{"instrument_id": ids[c["instrument_key"]], "timeframe": c["timeframe"],
                     "candle_time": c["timestamp"], "open": c["open"], "high": c["high"],
                     "low": c["low"], "close": c["close"], "volume": c.get("volume", 0),
                     "open_interest": c.get("open_interest")} for c in unique]
        insert_fn = _insert_fn()
        changed = 0
        changed_timeframes: set[str] = set()
        for offset in range(0, len(prepared), 100):
            batch = prepared[offset:offset + 100]
            stmt = insert_fn(MarketCandle).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["instrument_id", "timeframe", "candle_time"],
                set_={"open": stmt.excluded.open, "high": stmt.excluded.high, "low": stmt.excluded.low,
                      "close": stmt.excluded.close, "volume": stmt.excluded.volume,
                      "open_interest": stmt.excluded.open_interest},
                where=or_(*(getattr(MarketCandle, field) != getattr(stmt.excluded, field)
                            for field in ("open", "high", "low", "close", "volume", "open_interest"))),
            )
            result = await session.execute(stmt)
            if result.rowcount and result.rowcount > 0:
                changed += result.rowcount
                changed_timeframes.update(c["timeframe"] for c in batch)
        for timeframe in changed_timeframes:
            stmt = insert_fn(CandleRevision).values(timeframe=timeframe, revision=1)
            await session.execute(stmt.on_conflict_do_update(index_elements=["timeframe"],
                set_={"revision": CandleRevision.revision + 1}))
            await session.execute(delete(StrategyCache).where(StrategyCache.timeframe == timeframe))
        await session.commit()
    return changed


async def get_latest_candle_timestamps(timeframe: str) -> dict[str, datetime]:
    async with async_session_factory() as session:
        stmt = (select(Instrument.provider_instrument_key, func.max(MarketCandle.candle_time))
                .join(MarketCandle, MarketCandle.instrument_id == Instrument.id)
                .where(MarketCandle.timeframe == timeframe)
                .group_by(Instrument.provider_instrument_key))
        return {key: timestamp for key, timestamp in (await session.execute(stmt)).all() if timestamp is not None}


async def get_all_active_instruments() -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        stmt = select(Instrument).where(Instrument.is_active.is_(True)).order_by(Instrument.symbol)
        rows = (await session.execute(stmt)).scalars().all()
        return [{"key": row.provider_instrument_key, "symbol": row.symbol, "name": row.symbol,
                 "exchange": row.exchange, "segment": row.exchange, "isin": None} for row in rows]


async def load_candles_polars(timeframe: str, min_candles: int = 200) -> pl.DataFrame:
    if not 1 <= min_candles <= 10000:
        raise ValueError("Candle window must be between 1 and 10000")
    async with async_session_factory() as session:
        ranked = select(
            Instrument.provider_instrument_key.label("instrument_key"), MarketCandle.candle_time.label("timestamp"),
            MarketCandle.open, MarketCandle.high, MarketCandle.low, MarketCandle.close, MarketCandle.volume,
            func.row_number().over(partition_by=MarketCandle.instrument_id,
                order_by=MarketCandle.candle_time.desc()).label("position")
        ).join(Instrument, Instrument.id == MarketCandle.instrument_id).where(
            MarketCandle.timeframe == timeframe).subquery()
        stmt = select(ranked.c.instrument_key, ranked.c.timestamp, ranked.c.open, ranked.c.high,
                      ranked.c.low, ranked.c.close, ranked.c.volume).where(
            ranked.c.position <= min_candles).order_by(ranked.c.instrument_key, ranked.c.timestamp.asc())
        rows = (await session.execute(stmt)).all()
        if not rows:
            return pl.DataFrame(schema={"instrument_key": pl.Utf8, "timestamp": pl.Datetime("us", "UTC"),
                "open": pl.Float64, "high": pl.Float64, "low": pl.Float64, "close": pl.Float64, "volume": pl.Int64})
        return pl.DataFrame({"instrument_key": [r[0] for r in rows], "timestamp": [r[1] for r in rows],
            "open": [float(r[2]) for r in rows], "high": [float(r[3]) for r in rows],
            "low": [float(r[4]) for r in rows], "close": [float(r[5]) for r in rows],
            "volume": [int(r[6]) for r in rows]})


async def load_recent_candles_polars(timeframe: str, per_instrument: int = 250) -> pl.DataFrame:
    """Load only each active instrument's newest candles using the lookup index."""
    if not 1 <= per_instrument <= 10000:
        raise ValueError("Candle window must be between 1 and 10000")
    recent = (select(MarketCandle.candle_time.label("timestamp"), MarketCandle.open, MarketCandle.high,
                     MarketCandle.low, MarketCandle.close, MarketCandle.volume)
              .where(MarketCandle.instrument_id == Instrument.id, MarketCandle.timeframe == timeframe)
              .order_by(MarketCandle.candle_time.desc()).limit(per_instrument).lateral("recent_candles"))
    stmt = (select(Instrument.provider_instrument_key, recent.c.timestamp, recent.c.open, recent.c.high,
                   recent.c.low, recent.c.close, recent.c.volume)
            .select_from(Instrument).join(recent, true())
            .where(Instrument.is_active.is_(True))
            .order_by(Instrument.provider_instrument_key, recent.c.timestamp.asc()))
    async with async_session_factory() as session:
        rows = (await session.execute(stmt)).all()
    if not rows:
        return pl.DataFrame(schema={"instrument_key": pl.Utf8, "timestamp": pl.Datetime("us", "UTC"),
            "open": pl.Float64, "high": pl.Float64, "low": pl.Float64, "close": pl.Float64, "volume": pl.Int64})
    return pl.DataFrame({"instrument_key": [r[0] for r in rows], "timestamp": [r[1] for r in rows],
        "open": [float(r[2]) for r in rows], "high": [float(r[3]) for r in rows],
        "low": [float(r[4]) for r in rows], "close": [float(r[5]) for r in rows],
        "volume": [int(r[6]) for r in rows]})


async def get_cached_strategy_result(cache_key: str) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        row = (await session.execute(select(StrategyCache).where(
            StrategyCache.cache_key == cache_key, StrategyCache.expires_at > now))).scalar_one_or_none()
        if row:
            return {"strategy_id": row.strategy_id, "timeframe": row.timeframe, "total_scanned": row.total_scanned,
                "total_matched": row.total_matched, "scanned_at": row.scanned_at.isoformat(),
                "results": json.loads(row.results_json), "cached": True}
        return None


async def save_strategy_result_cache(cache_key: str, strategy_id: str, timeframe: str,
    params: dict[str, Any], results: list[dict[str, Any]], total_scanned: int, expires_at: datetime):
    payload = {"cache_key": cache_key, "strategy_id": strategy_id, "timeframe": timeframe,
        "params_json": json.dumps(params, sort_keys=True), "results_json": json.dumps(results),
        "total_scanned": total_scanned, "total_matched": len(results),
        "scanned_at": datetime.now(timezone.utc), "expires_at": expires_at}
    async with async_session_factory() as session:
        insert_stmt = _insert_fn()(StrategyCache).values(payload)
        stmt = insert_stmt.on_conflict_do_update(index_elements=["cache_key"],
            set_={"results_json": insert_stmt.excluded.results_json, "total_scanned": insert_stmt.excluded.total_scanned,
                "total_matched": insert_stmt.excluded.total_matched, "scanned_at": insert_stmt.excluded.scanned_at,
                "expires_at": insert_stmt.excluded.expires_at})
        await session.execute(stmt)
        await session.commit()


async def get_candle_revision(timeframe: str) -> int:
    async with async_session_factory() as session:
        return (await session.scalar(select(CandleRevision.revision).where(
            CandleRevision.timeframe == timeframe))) or 0



async def create_ingestion_job(timeframe: str, start_time: datetime, end_time: datetime) -> int:
    from database.models import IngestionJob
    async with async_session_factory() as session:
        job = IngestionJob(timeframe=timeframe, start_time=start_time, end_time=end_time, status="pending",
                           updated_at=datetime.now(timezone.utc))
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job.id


async def update_ingestion_job(job_id: int, status: str, last_error: str | None = None) -> None:
    from database.models import IngestionJob
    async with async_session_factory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is not None:
            job.status = status
            job.last_error = last_error
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()


async def get_ingestion_job(job_id: int) -> dict[str, Any] | None:
    from database.models import IngestionJob
    async with async_session_factory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            return None
        return {"id": job.id, "timeframe": job.timeframe, "start_time": job.start_time,
                "end_time": job.end_time, "status": job.status, "last_error": job.last_error,
                "updated_at": job.updated_at}


async def upsert_data_coverage(instrument_key: str, timeframe: str, timestamps: Sequence[datetime]) -> None:
    if not timestamps:
        return
    from database.models import DataCoverage
    timestamps = [ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
                  for ts in timestamps]
    async with async_session_factory() as session:
        instrument_id = await session.scalar(select(Instrument.id).where(
            Instrument.provider_instrument_key == instrument_key))
        if instrument_id is None:
            return
        current = await session.scalar(select(DataCoverage).where(
            DataCoverage.instrument_id == instrument_id, DataCoverage.timeframe == timeframe))
        earliest, latest = min(timestamps), max(timestamps)
        if current:
            if current.earliest_candle is not None:
                old_earliest = current.earliest_candle.replace(tzinfo=timezone.utc) if current.earliest_candle.tzinfo is None else current.earliest_candle
                earliest = min(earliest, old_earliest)
            if current.latest_candle is not None:
                old_latest = current.latest_candle.replace(tzinfo=timezone.utc) if current.latest_candle.tzinfo is None else current.latest_candle
                latest = max(latest, old_latest)
        checked = datetime.now(timezone.utc)
        stmt = _insert_fn()(DataCoverage).values(instrument_id=instrument_id, timeframe=timeframe,
            earliest_candle=earliest, latest_candle=latest, last_checked_at=checked)
        await session.execute(stmt.on_conflict_do_update(index_elements=["instrument_id", "timeframe"],
            set_={"earliest_candle": earliest, "latest_candle": latest, "last_checked_at": checked}))
        await session.commit()
