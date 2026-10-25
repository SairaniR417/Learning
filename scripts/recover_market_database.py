"""Salvage readable candles into a NEW database; never modifies the source DB.

Requires a completed preservation backup and non-candle pg_dump in the recovery
folder. The app is not switched automatically. Damaged source heap pages are
reported explicitly; no corruption-bypass setting is enabled.
"""
import asyncio
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from sqlalchemy.engine import make_url
import asyncpg

load_dotenv(ROOT / '.env')
BIN = Path('C:/Program Files/PostgreSQL/18/bin')
COLUMNS = ('id','instrument_id','timeframe','candle_time','open','high','low','close','volume','open_interest')


async def main():
    folder = Path((ROOT/'data/backups/current-recovery.txt').read_text(encoding='utf-8'))
    if not (folder/'cluster-preservation/backup_manifest').exists():
        raise RuntimeError('Completed physical preservation backup required')
    dump = folder/'non-candle-data.dump'
    if not dump.exists():
        raise RuntimeError('Non-candle backup required')
    url = make_url(os.environ['DATABASE_URL'])
    params = dict(host=url.host or 'localhost',port=url.port or 5432,user=url.username,password=url.password)
    source = await asyncpg.connect(**params,database=url.database)
    target_name = 'traders_gita_recovered_' + folder.name.removeprefix('recovery-').lower()
    if not re.fullmatch('[a-z0-9_]+',target_name) or target_name == url.database:
        raise ValueError('Invalid recovery database name')
    resume = '--resume' in sys.argv
    if resume:
        report = json.loads((folder/'recovery-report.json').read_text(encoding='utf-8'))
        if report['targetDatabase'] != target_name or report['sourceDatabase'] != url.database or report['status'] != 'failed':
            raise RuntimeError('Resume requires the same failed recovery')
        report.pop('error',None)
    else:
        report = dict(status='preparing',sourceDatabase=url.database,targetDatabase=target_name,
                      recoveredCandles=0,invalidOHLCV=0,damagedHeapBlocks=[],blocksProcessed=0)
    def save():
        temp = folder/'recovery-report.tmp'
        temp.write_text(json.dumps(report,indent=2),encoding='utf-8')
        temp.replace(folder/'recovery-report.json')
    save()
    target = None
    try:
        # Refuse to replace or reuse any existing database.
        if not resume:
            await source.execute(f'CREATE DATABASE "{target_name}" TEMPLATE template0')
        env = os.environ.copy()
        env.update(PGHOST=params['host'],PGPORT=str(params['port']),PGUSER=params['user'],PGPASSWORD=params['password'] or '',PGDATABASE=target_name)
        if not resume:
            with (folder/'restore.log').open('w',encoding='utf-8') as log:
                result = await asyncio.to_thread(subprocess.run,
                    [str(BIN/'pg_restore.exe'),'--exit-on-error','--no-password','--dbname',target_name,str(dump)],
                    env=env,stdout=log,stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError('Non-candle restore failed; inspect restore.log')
        target = await asyncpg.connect(**params,database=target_name)
        if resume and await target.fetchval('SELECT count(*) FROM public.candles') != report['recoveredCandles']:
            raise RuntimeError('Resume count mismatch')
        # A fixed read-only snapshot prevents vacuum from removing visible tuples;
        # savepoints allow each damaged range to fail without losing the snapshot.
        async with source.transaction(isolation='repeatable_read',readonly=True):
            await source.execute('LOCK TABLE public.candles IN ACCESS SHARE MODE')
            size = await source.fetchval("SELECT pg_relation_size('public.candles')")
            block_size = int(await source.fetchval('SHOW block_size'))
            total = math.ceil(size/block_size)
            report.update(status='salvaging',totalBlocks=total)
            query = 'SELECT '+','.join(COLUMNS)+" FROM public.candles WHERE ctid >= $1::text::tid AND ctid < $2::text::tid"
            plan = await source.fetch('EXPLAIN '+query, '(0,0)','(512,0)')
            if not any('Tid Range Scan' in row[0] for row in plan):
                raise RuntimeError('Expected a bounded heap scan; refusing a full-table/index scan')
            async def recover_range(start,end):
                try:
                    async with source.transaction():
                        rows = await source.fetch(query,f'({start},0)',f'({end},0)')
                except asyncpg.PostgresError as exc:
                    match = re.search(r'invalid page in block (\d+)',str(exc))
                    bulk = re.search(r'invalid pages among blocks (\d+)\.\.(\d+)',str(exc))
                    if not match and not bulk:
                        raise
                    block = int(match.group(1)) if match else int(bulk.group(1))
                    if not start <= block < end:
                        raise RuntimeError('Damage reported outside the requested heap range') from exc
                    if end-start == 1:
                        report['damagedHeapBlocks'].append(start)
                        return
                    mid = (start+end)//2
                    await recover_range(start,mid)
                    await recover_range(mid,end)
                    return
                valid = []
                for row in rows:
                    o,h,l,c = (row[k] for k in ('open','high','low','close'))
                    if not all(v.is_finite() for v in (o,h,l,c)) or not 0 < l <= min(o,c) <= max(o,c) <= h or row['volume'] < 0:
                        report['invalidOHLCV'] += 1
                        continue
                    valid.append(tuple(row))
                if valid:
                    await target.copy_records_to_table('candles',records=valid,columns=COLUMNS,schema_name='public')
                    report['recoveredCandles'] += len(valid)
            for start in range(report['blocksProcessed'],total,512):
                previous = (report['recoveredCandles'],report['invalidOHLCV'],len(report['damagedHeapBlocks']))
                try:
                    async with target.transaction():
                        await recover_range(start,min(start+512,total))
                except Exception:
                    report['recoveredCandles'],report['invalidOHLCV'] = previous[:2]
                    del report['damagedHeapBlocks'][previous[2]:]
                    raise
                report['blocksProcessed'] = min(start+512,total)
                save()
                if start % 4096 == 0:
                    print(json.dumps({k:report[k] for k in ('blocksProcessed','totalBlocks','recoveredCandles','damagedHeapBlocks')}),flush=True)
        await target.execute("SELECT setval(pg_get_serial_sequence('public.candles','id'), COALESCE((SELECT max(id) FROM public.candles),1), EXISTS(SELECT 1 FROM public.candles))")
        # Cached scans and coverage describe the old data and must be recomputed.
        await target.execute('TRUNCATE public.strategy_cache, public.data_coverage')
        await target.execute('UPDATE public.candle_revisions SET revision = revision + 1')
        await target.execute('ANALYZE public.candles')
        report['validatedCount'] = await target.fetchval('SELECT count(*) FROM public.candles')
        report['byTimeframe'] = [dict(r) for r in await target.fetch('SELECT timeframe,count(*) AS count,min(candle_time)::text AS earliest,max(candle_time)::text AS latest FROM public.candles GROUP BY timeframe ORDER BY timeframe')]
        report['nonCandleCounts'] = {}
        for row in await source.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('candles','strategy_cache','data_coverage','candle_revisions')"):
            name = row['tablename']
            quoted = '"'+name.replace('"','""')+'"'
            old = await source.fetchval('SELECT count(*) FROM public.'+quoted)
            new = await target.fetchval('SELECT count(*) FROM public.'+quoted)
            report['nonCandleCounts'][name] = dict(source=old,recovered=new)
            if old != new:
                raise RuntimeError('Non-candle record counts changed; do not switch databases')
            checksum_query = "SELECT md5(coalesce(string_agg(v,' ' ORDER BY v),'')) FROM (SELECT to_jsonb(t)::text v FROM public."+quoted+" t) q"
            if await source.fetchval(checksum_query) != await target.fetchval(checksum_query):
                raise RuntimeError('Non-candle record contents differ; do not switch databases')
        if report['validatedCount'] != report['recoveredCandles']:
            raise RuntimeError('Recovered candle count mismatch')
        report['status'] = 'salvaged-awaiting-history-reconciliation'
        save()
        print(json.dumps(report),flush=True)
    except Exception as exc:
        report.update(status='failed',error=type(exc).__name__)
        save()
        raise
    finally:
        await source.close()
        if target:
            await target.close()


if __name__ == '__main__':
    asyncio.run(main())
