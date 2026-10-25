"""Unattended BHAV catch-up and completed candles for previously selected stocks."""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
import httpx
from sqlalchemy import select, func
from database.connection import async_session_factory, engine, init_db
from database.models import Instrument, MarketCandle, StockChartSelection
from database.candle_repo import get_all_active_instruments
from scanner.universe import fno_keys
from services.market_sync import INDIA, MarketSyncService
from scripts.import_nse_bhavcopy import import_archive


async def run():
    now = datetime.now(INDIA)
    end = now.date() if now.hour >= 18 else now.date()-timedelta(days=1)
    async with async_session_factory() as session:
        latest = (await session.execute(select(func.max(MarketCandle.timestamp)).join(
            Instrument, Instrument.id == MarketCandle.instrument_id).where(
            MarketCandle.timeframe == '1d', Instrument.provider_instrument_key.in_(fno_keys()))
            .group_by(MarketCandle.instrument_id))).scalars().all()
        selected_query = select(Instrument.provider_instrument_key).join(
            StockChartSelection, Instrument.id == StockChartSelection.instrument_id).where(
            StockChartSelection.last_viewed_at >= now-timedelta(days=28),
            Instrument.provider_instrument_key.in_(fno_keys()))
        selected = set((await session.execute(selected_query)).scalars().all())
    # Small correction overlap; older missing sessions are caught up from the stalest stock.
    start = min(ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts for ts in latest).astimezone(INDIA).date()-timedelta(days=2) if latest else end-timedelta(days=14)
    start = max(start, end-timedelta(days=365))
    folder = ROOT / 'data' / 'archives'
    folder.mkdir(parents=True, exist_ok=True)
    summary = dict(start=str(start), end=str(end), imported=[], unavailable=[], failed=[], intraday=None)
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, trust_env=False, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        day = start
        while day <= end:
            if day.weekday() < 5:
                archive = folder / f'PR{day:%d%m%y}.zip'
                try:
                    # Retry transient failures; a 404 may be a holiday or an unpublished archive.
                    for attempt in range(3):
                        try:
                            response = await client.get(f'https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/{archive.name}')
                            if response.status_code == 404:
                                break
                            response.raise_for_status()
                            break
                        except httpx.HTTPError:
                            if attempt == 2:
                                raise
                            await asyncio.sleep(2 ** attempt)
                    if response.status_code == 404:
                        summary['unavailable'].append(str(day))
                    else:
                        temp = archive.with_suffix('.tmp')
                        temp.write_bytes(response.content)
                        report = await import_archive(temp, apply=True, expected_date=day)
                        temp.replace(archive)
                        summary['imported'].append(dict(date=str(day), changed=report['changed']))
                        if report['invalid'] or report['ambiguous'] or not report['matched']:
                            summary['failed'].append(dict(date=str(day), error='Incomplete BHAV import; inspect daily report'))
                except Exception as exc:
                    summary['failed'].append(dict(date=str(day), error=type(exc).__name__))
                await asyncio.sleep(1.05)
            day += timedelta(days=1)
    token = os.getenv('UPSTOX_ACCESS_TOKEN', '').strip()
    if selected and token:
        stocks = [s for s in await get_all_active_instruments() if s['key'] in selected]
        summary['intraday'] = await MarketSyncService(lambda: token).sync_candles_for_universe(
            unit='minutes', interval=1, lookback_days=28, concurrency=1, target_instruments=stocks)
    elif selected:
        summary['intraday'] = {'status': 'skipped', 'reason': 'No configured Upstox token; BHAV daily update is independent.'}
    summary['completedAt'] = datetime.now(INDIA).isoformat()
    report_path = ROOT / 'data' / 'scheduled-update.json'
    temp = report_path.with_suffix('.tmp')
    temp.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    temp.replace(report_path)
    print(json.dumps(summary), flush=True)
    return 1 if summary['failed'] or (summary['intraday'] or {}).get('errors') else 0


async def main():
    try:
        await init_db()
        return await run()
    except Exception as exc:
        report = dict(status='failed', error=type(exc).__name__, completedAt=datetime.now(INDIA).isoformat())
        if 'invalid page' in str(getattr(exc, 'orig', '')):
            report['reason'] = 'PostgreSQL reported damaged storage pages. Database recovery is required before updates can complete.'
        (ROOT / 'data' / 'scheduled-update.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
        return 1
    finally:
        await engine.dispose()


if __name__ == '__main__':
    import msvcrt
    lock = open(ROOT / 'data' / 'scheduled-update.lock', 'a+b')
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        sys.exit('Market data update is already running')
    try:
        sys.exit(asyncio.run(main()))
    finally:
        lock.close()
