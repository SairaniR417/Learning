"""Fetch today's NSE daily candles, persist progress, and invalidate scan caches.

Run from the repository root. Credentials are read locally and never logged.
Only provider-supplied candles for today after the equity session are written.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
import httpx
from database.candle_repo import get_all_active_instruments, upsert_candles, upsert_data_coverage
from database.connection import engine
from services.market_sync import INDIA, nse_daily_closed


async def main():
    today = datetime.now(INDIA).date()
    report = ROOT / 'data' / f'daily-sync-{today}.json'
    token = os.getenv('UPSTOX_ACCESS_TOKEN', '').strip()
    if not token:
        raise RuntimeError('No configured Upstox token')
    if datetime.now(INDIA).hour < 16:
        raise RuntimeError('Today is not yet a completed NSE daily candle')
    stocks = [s for s in await get_all_active_instruments() if s['exchange'] == 'NSE']
    state = dict(date=str(today), status='running', total=len(stocks), processed=0, changed=0, no_candle=0, failed=0, errors=[], startedAt=datetime.now(timezone.utc).isoformat())
    if '--resume' in sys.argv and report.exists():
        state = json.loads(report.read_text(encoding='utf-8'))
        if state['date'] != str(today) or state['total'] != len(stocks):
            raise RuntimeError('Resume requires the same date and instrument universe')
        state['status'] = 'running'
    resume_offset = state['processed']
    def save():
        state['updatedAt'] = datetime.now(timezone.utc).isoformat()
        temp = report.with_suffix('.tmp')
        temp.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temp.replace(report)
    save()
    async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
        for stock in stocks[resume_offset:]:
            try:
                r = await client.get('https://api.upstox.com/v3/historical-candle/intraday/' + quote(stock['key'], safe='') + '/days/1', headers={'Authorization': 'Bearer ' + token})
                if r.status_code in (401, 403, 429):
                    state['status'] = 'blocked'
                    state['errors'].append(dict(symbol=stock['symbol'], httpStatus=r.status_code))
                    save()
                    break
                r.raise_for_status()
                payload = r.json()
                if payload.get('status') != 'success':
                    raise ValueError('Provider reported unsuccessful response')
                records = []
                for row in payload['data']['candles']:
                    ts = datetime.fromisoformat(row[0].replace('Z', '+00:00')).astimezone(timezone.utc)
                    if ts.astimezone(INDIA).date() != today or not nse_daily_closed(ts):
                        continue
                    o,h,l,c = map(float, row[1:5])
                    if not 0 < l <= min(o,c) <= max(o,c) <= h:
                        raise ValueError('Invalid provider OHLC')
                    records.append(dict(instrument_key=stock['key'], timeframe='1d', timestamp=ts, open=o, high=h, low=l, close=c, volume=int(row[5])))
                if records:
                    state['changed'] += await upsert_candles(records)
                    await upsert_data_coverage(stock['key'], '1d', [r['timestamp'] for r in records])
                else:
                    state['no_candle'] += 1
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                state['failed'] += 1
                state['errors'].append(dict(symbol=stock['symbol'], error=type(exc).__name__))
            state['processed'] += 1
            save()
            if state['processed'] % 50 == 0:
                print(json.dumps({k:state[k] for k in ('processed','total','changed','no_candle','failed')}), flush=True)
            await asyncio.sleep(1.05)
        else:
            state['status'] = 'complete' if not state['failed'] else 'partial'
        save()
        print(json.dumps(state), flush=True)
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
