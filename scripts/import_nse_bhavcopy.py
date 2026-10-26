"""Import NSE daily OHLCV from a PR archive into existing NSE instruments."""
import asyncio
import csv
import io
import json
import sys
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from database.connection import async_session_factory, engine
from database.models import Instrument, MarketCandle
from database.candle_repo import upsert_candles
from sqlalchemy import select
from scanner.universe import fno_keys, fno_symbols
from services.market_cap import parse_market_caps, SNAPSHOT

async def import_archive(archive, apply=False, expected_date=None):
    archive = Path(archive)
    # Check decompressed sizes before any ZIP member is read into memory.
    with zipfile.ZipFile(archive) as checked:
        members = checked.infolist()
        if len(members) > 200 or sum(m.file_size for m in members) > 128 * 1024 * 1024:
            raise ValueError('NSE archive exceeds decompressed size limit')
        if any(m.file_size > 32 * 1024 * 1024 for m in members):
            raise ValueError('NSE archive member exceeds size limit')
    market_caps = parse_market_caps(archive)
    market_caps["values"] = {k: v for k, v in market_caps["values"].items() if k in fno_symbols()}
    with zipfile.ZipFile(archive) as z:
        names = [n for n in z.namelist() if Path(n).name.lower().startswith('pd') and n.lower().endswith('.csv')]
        if len(names) != 1:
            raise ValueError('Expected exactly one symbol-level pd report')
        date = datetime.strptime(Path(names[0]).stem[2:], '%d%m%Y').date()
        if expected_date is not None and date != expected_date:
            raise ValueError('Downloaded archive date does not match requested date')
        timestamp = datetime.combine(date, datetime.min.time(), timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)
        rows = csv.DictReader(io.StringIO(z.read(names[0]).decode('utf-8-sig')))
        mcap = next(n for n in z.namelist() if Path(n).name.lower().startswith('mcap'))
        dates = {datetime.strptime(r['Trade Date'].strip(), '%d %b %Y').date() for r in csv.DictReader(io.StringIO(z.read(mcap).decode('utf-8-sig')))}
        if dates != {date}:
            raise ValueError('Archive trading dates disagree')
    async with async_session_factory() as s:
        instruments = (await s.execute(select(Instrument).where(Instrument.exchange == 'NSE', Instrument.is_active.is_(True), Instrument.provider_instrument_key.in_(fno_keys())))).scalars().all()
        lookup = {}
        for i in instruments:
            lookup.setdefault(i.symbol, []).append(i)
        report = {'date': str(date), 'source': str(archive), 'matched': 0, 'changed': 0, 'unmatched': [], 'invalid': [], 'ambiguous': [], 'series': {}}
        candidates = {}
        for r in rows:
            r = {k: v.strip() if v else '' for k,v in r.items()}
            if r['MKT'] != 'N' or r['SERIES'] not in {'EQ', 'BE', 'BZ', 'SM', 'ST', 'SZ'}:
                continue
            symbol = r['SYMBOL']
            if symbol not in lookup:
                report['unmatched'].append(symbol)
                continue
            if len(lookup[symbol]) != 1 or symbol in candidates:
                report['ambiguous'].append(symbol)
                continue
            try:
                o,h,l,c = [Decimal(r[k]) for k in ('OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE')]
                volume = int(r['NET_TRDQTY'])
                if not all(v.is_finite() for v in (o,h,l,c)) or not 0 < l <= min(o,c) <= max(o,c) <= h or volume <= 0:
                    raise ValueError('Invalid OHLC or no trading')
                candidates[symbol] = dict(instrument_key=lookup[symbol][0].provider_instrument_key, timeframe='1d', timestamp=timestamp, open=o, high=h, low=l, close=c, volume=volume)
                report['series'][r['SERIES']] = report['series'].get(r['SERIES'], 0) + 1
            except (ValueError, ArithmeticError):
                report['invalid'].append(symbol)
        for symbol in report['ambiguous']:
            candidates.pop(symbol, None)
        report['matched'] = len(candidates)
        report['expected'] = len(instruments)
        report['missing'] = sorted(set(lookup) - set(candidates))
        previous = (await s.execute(select(MarketCandle).where(MarketCandle.timeframe=='1d',MarketCandle.candle_time==timestamp,MarketCandle.instrument_id.in_([i.id for i in instruments])))).scalars().all()
        backup = [{k: str(getattr(r,k)) if k in {'candle_time','open','high','low','close'} else getattr(r,k) for k in ('instrument_id','timeframe','candle_time','open','high','low','close','volume','open_interest')} for r in previous]
    if apply:
        backup_path = ROOT / 'data' / f'bhavcopy-backup-{date}.json'
        if not backup_path.exists():
            backup_path.write_text(json.dumps(backup, indent=2), encoding='utf-8')
        report['changed'] = await upsert_candles(list(candidates.values()))
        previous_cap_date = json.loads(SNAPSHOT.read_text(encoding='utf-8')).get('asOf', '') if SNAPSHOT.exists() else ''
        if market_caps['asOf'] >= previous_cap_date:
            temp = SNAPSHOT.with_suffix('.tmp')
            temp.write_text(json.dumps(market_caps, indent=2), encoding='utf-8')
            temp.replace(SNAPSHOT)
    report['status'] = 'imported' if apply else 'preview'
    (ROOT / 'data' / f'bhavcopy-import-{date}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: len(v) if isinstance(v,list) else v for k,v in report.items()}), flush=True)
    return report


async def main():
    try:
        await import_archive(sys.argv[1], apply='--apply' in sys.argv)
    finally:
        await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
