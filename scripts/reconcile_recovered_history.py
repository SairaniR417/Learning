"""Fill missing daily rows in the separate recovered DB from the saved CSV.

Existing recovered values are preserved. The configured source DB and .env are
not changed. Run only after recover_market_database.py completes successfully.
"""
import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from sqlalchemy.engine import make_url
import asyncpg
load_dotenv(ROOT/'.env')


async def main():
    folder = Path((ROOT/'data/backups/current-recovery.txt').read_text(encoding='utf-8'))
    report = json.loads((folder/'recovery-report.json').read_text(encoding='utf-8'))
    if report['status'] != 'salvaged-awaiting-history-reconciliation':
        raise RuntimeError('Recovery must finish before reconciliation')
    url = make_url(os.environ['DATABASE_URL'])
    target_name = report['targetDatabase']
    if target_name == url.database:
        raise RuntimeError('Refusing to reconcile the source database')
    # Import CSV helpers only after directing their connection factory at recovery.
    os.environ['DATABASE_URL'] = url.set(database=target_name).render_as_string(hide_password=False)
    from scripts.restrict_to_fno import read_history
    from scanner.universe import get_fno_stocks
    from database.connection import engine
    stocks = get_fno_stocks()
    rows = read_history(stocks)
    c = await asyncpg.connect(host=url.host or 'localhost',port=url.port or 5432,
                             user=url.username,password=url.password,database=target_name)
    try:
        deferred = folder/'deferred-candle-indexes.json'
        if deferred.exists():
            for definition in json.loads(deferred.read_text(encoding='utf-8')):
                name = definition.split()[3] if definition.startswith('CREATE UNIQUE INDEX ') else definition.split()[2]
                if not await c.fetchval('SELECT to_regclass($1)::text', 'public.'+name):
                    await c.execute(definition)
            constraint = 'candles_instrument_id_timeframe_candle_time_key'
            if not await c.fetchval("SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.candles'::regclass AND conname=$1)",constraint):
                await c.execute('ALTER TABLE public.candles ADD CONSTRAINT '+constraint+' UNIQUE USING INDEX '+constraint)
            print('Recovered candle indexes rebuilt successfully',flush=True)
        ids = {r['provider_instrument_key']:r['id'] for r in await c.fetch('SELECT id,provider_instrument_key FROM instruments')}
        missing_stocks = [s for s in stocks if s['key'] not in ids]
        if missing_stocks:
            from database.candle_repo import upsert_instruments
            await upsert_instruments(missing_stocks)
            ids = {r['provider_instrument_key']:r['id'] for r in await c.fetch('SELECT id,provider_instrument_key FROM instruments')}
        report['missingFnoInstrumentsAdded'] = len(missing_stocks)
        records = [(ids[r['instrument_key']],'1d',r['timestamp'],
                    *(Decimal(str(r[k])) for k in ('open','high','low','close')),r['volume']) for r in rows]
        if any(not 0 < r[5] <= min(r[3],r[6]) <= max(r[3],r[6]) <= r[4] for r in records):
            raise ValueError('Invalid saved CSV OHLC')
        columns = ('instrument_id','timeframe','candle_time','open','high','low','close','volume')
        fields = ','.join(columns)
        async with c.transaction():
            await c.execute('CREATE TEMP TABLE recovery_daily_source AS SELECT '+fields+' FROM public.candles WITH NO DATA')
            await c.copy_records_to_table('recovery_daily_source',records=records,columns=columns)
            result = await c.execute('INSERT INTO public.candles ('+fields+') SELECT '+fields+' FROM recovery_daily_source ON CONFLICT (instrument_id,timeframe,candle_time) DO NOTHING')
            report['dailyRowsRestoredFromCSV'] = int(result.split()[-1])
            missing = await c.fetchval('SELECT count(*) FROM recovery_daily_source s LEFT JOIN public.candles c USING (instrument_id,timeframe,candle_time) WHERE c.id IS NULL')
            if missing:
                raise RuntimeError('Saved daily history is still missing after reconciliation')
            report['savedDailyRowsVerified'] = len(records)
            await c.execute("UPDATE public.candle_revisions SET revision=revision+1 WHERE timeframe='1d'")
        report['dailyCountAfterCSV'] = await c.fetchval("SELECT count(*) FROM public.candles WHERE timeframe='1d'")
        report['finalCandleCount'] = await c.fetchval('SELECT count(*) FROM public.candles')
        await c.execute('''INSERT INTO public.data_coverage (instrument_id,timeframe,earliest_candle,latest_candle,last_checked_at)
            SELECT instrument_id,timeframe,min(candle_time),max(candle_time),now() FROM public.candles GROUP BY instrument_id,timeframe
            ON CONFLICT (instrument_id,timeframe) DO UPDATE SET earliest_candle=excluded.earliest_candle,
            latest_candle=excluded.latest_candle,last_checked_at=excluded.last_checked_at''')
        report['coverageRowsRebuilt'] = await c.fetchval('SELECT count(*) FROM public.data_coverage')
        report['status'] = 'reconciled-awaiting-validation-and-switch'
        report.pop('error',None)
        (folder/'recovery-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('targetDatabase','dailyRowsRestoredFromCSV','dailyCountAfterCSV','finalCandleCount','status')}),flush=True)
    finally:
        await c.close()
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
