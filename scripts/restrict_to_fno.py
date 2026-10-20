"""Back up, prune, and seed the configured database from the saved F&O CSVs.

Run without arguments to preview; use --apply to perform the migration.
"""
import argparse
import asyncio
import csv
import gzip
import json
import math
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, inspect, select, text
from database.connection import engine, async_session_factory, init_db
from database.models import (
    Instrument, MarketCandle, IngestionJob, DataCoverage, StrategyCache,
    UserWatchlist, PriceAlert, AlertNotification, JournalTrade,
)
from database.candle_repo import upsert_instruments, upsert_candles, upsert_data_coverage
from scanner.universe import get_fno_stocks

IST = timezone(timedelta(hours=5, minutes=30))


def read_history(stocks):
    by_symbol = {s["symbol"]: s for s in stocks}
    records = {}
    with (ROOT / "data/fno/fno_stock_daily_1d.csv").open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            if row["symbol"] not in by_symbol:
                continue
            values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
            volume = int(row["volume"])
            if not all(math.isfinite(v) and v >= 0 for v in values.values()) or volume < 0:
                raise ValueError(f"Invalid candle: {row['symbol']} {row['trade_date']}")
            timestamp = datetime.fromisoformat(row["trade_date"]).replace(tzinfo=IST).astimezone(timezone.utc)
            key = by_symbol[row["symbol"]]["key"]
            identity = (key, timestamp)
            record = dict(instrument_key=key, timeframe="1d", timestamp=timestamp, volume=volume, **values)
            if identity in records and records[identity] != record:
                raise ValueError(f"Conflicting candles: {identity}")
            records[identity] = record
    if {r["instrument_key"] for r in records.values()} != {s["key"] for s in stocks}:
        raise ValueError("Daily CSV does not cover every saved F&O stock.")
    return list(records.values())


async def backup_database(directory):
    """Stream every public table to a compressed JSONL backup before any deletion."""
    directory.mkdir(parents=True, exist_ok=False)
    counts = {}
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
        for table in tables:
            quoted = engine.dialect.identifier_preparer.quote(table)
            counts[table] = 0
            with gzip.open(directory / f"{table}.jsonl.gz", "wt", encoding="utf-8") as output:
                result = await connection.stream(text(f"SELECT * FROM {quoted}"))
                async for row in result.mappings():
                    output.write(json.dumps(dict(row), default=str) + "\n")
                    counts[table] += 1
    (directory / "manifest.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
    return counts


async def prune(stocks):
    keys = {s["key"] for s in stocks}
    symbols = {s["symbol"] for s in stocks}
    report = {}
    async with async_session_factory() as session:
        excluded = select(Instrument.id).where(
            (Instrument.provider_instrument_key.not_in(keys)) | Instrument.provider_instrument_key.is_(None))
        for model in (MarketCandle, DataCoverage, IngestionJob):
            result = await session.execute(delete(model).where(model.instrument_id.in_(excluded)))
            report[model.__tablename__] = result.rowcount
        result = await session.execute(delete(Instrument).where(Instrument.id.in_(excluded)))
        report["instruments"] = result.rowcount
        for model in (AlertNotification, PriceAlert):
            result = await session.execute(delete(model).where(model.instrument_key.not_in(keys)))
            report[model.__tablename__] = result.rowcount
        report["watchlist_entries"] = 0
        for row in (await session.scalars(select(UserWatchlist))).all():
            content = json.loads(row.content_json)
            previous = content.get("entries", [])
            content["entries"] = [e for e in previous if e.get("key") in keys]
            report["watchlist_entries"] += len(previous) - len(content["entries"])
            row.content_json = json.dumps(content)
        report["journal_trades"] = 0
        for row in (await session.scalars(select(JournalTrade))).all():
            content = json.loads(row.content_json)
            if content.get("symbol", "").upper() not in symbols or content.get("segment") not in {"Equity", "Futures", "Options"}:
                await session.delete(row)
                report["journal_trades"] += 1
        await session.execute(delete(StrategyCache))
        await session.commit()
    return report


async def main(apply=False):
    stocks = get_fno_stocks()
    records = read_history(stocks)
    print(json.dumps({"stocks": len(stocks), "daily_candles": len(records), "database": engine.dialect.name,
                      "mode": "apply" if apply else "preview"}), flush=True)
    if not apply:
        await engine.dispose()
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = ROOT / "data/backups" / f"before-fno-{stamp}"
    print("Backup counts:", await backup_database(backup), flush=True)
    await init_db()
    report = await prune(stocks)
    await upsert_instruments(stocks)
    changed = 0
    for offset in range(0, len(records), 2500):
        changed += await upsert_candles(records[offset:offset + 2500])
        if offset % 25000 == 0:
            print(f"Imported {min(offset + 2500, len(records))}/{len(records)} candles", flush=True)
    dates = {}
    for row in records:
        dates.setdefault(row["instrument_key"], []).append(row["timestamp"])
    for key, timestamps in dates.items():
        await upsert_data_coverage(key, "1d", timestamps)
    # The old SQLite file has a different, obsolete instrument schema. Archive it
    # only when PostgreSQL is active, and only after a consistent SQLite backup.
    legacy = ROOT / "data/market_desk.db"
    if engine.dialect.name == "postgresql" and legacy.exists():
        with closing(sqlite3.connect(legacy)) as source, closing(sqlite3.connect(backup / "legacy-market_desk.db")) as target:
            source.backup(target)
        legacy.unlink()
    report.update(stocks=len(stocks), imported_candles=changed, backup=str(backup))
    (backup / "cleanup-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
