"""Technical scans on individual front-month MCX contracts, never spliced futures."""
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
import polars as pl
from fastapi import HTTPException

from scanner.commodity_universe import get_mcx_front_month_universe
from database.candle_repo import upsert_instruments, upsert_candles
from services.market_sync import candle_closed, INDIA


async def scan_commodities(strategy, timeframe, params, token):
    intervals = {'15m': ('minutes', 15, 27), '1h': ('hours', 1, 88), '1d': ('days', 1, 730)}
    if timeframe not in intervals:
        raise HTTPException(400, 'MCX technical scans support 15 minutes, 1 hour or daily candles.')
    resolved = {p.name: p.default for p in strategy.metadata.parameters}
    if set(params) - set(resolved):
        raise HTTPException(400, 'Unknown strategy parameter')
    resolved.update(params)
    for p in strategy.metadata.parameters:
        v = resolved[p.name]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (p.type == 'int' and not isinstance(v, int)) or not p.min_value <= v <= p.max_value:
            raise HTTPException(400, 'Invalid strategy parameter: ' + p.name)
    instruments = await get_mcx_front_month_universe()
    await upsert_instruments(instruments)
    unit, interval, days = intervals[timeframe]
    now = datetime.now(timezone.utc)
    today = now.astimezone(INDIA).date()
    rows, coverage, failures = [], [], []
    window = strategy.candle_window(resolved)
    async with httpx.AsyncClient(timeout=30) as client:
        for instrument in instruments:
            key = instrument['key']
            base = 'https://api.upstox.com/v3/historical-candle/'
            encoded = quote(key, safe='')
            urls = [f'{base}{encoded}/{unit}/{interval}/{today - timedelta(days=1)}/{today - timedelta(days=days)}']
            if unit != 'days':
                urls.append(f'{base}intraday/{encoded}/{unit}/{interval}')
            candles = {}
            try:
                for url in urls:
                    response = await client.get(url, headers={'Authorization': 'Bearer ' + token})
                    if response.status_code in (401, 403, 429):
                        raise HTTPException(response.status_code, 'Upstox denied or rate-limited MCX history. Try again after reconnecting or waiting.')
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get('status') != 'success':
                        raise ValueError('Unsuccessful provider response')
                    for c in payload['data']['candles']:
                        ts = datetime.fromisoformat(c[0].replace('Z', '+00:00')).astimezone(timezone.utc)
                        if candle_closed(ts, unit, interval, now, 'MCX'):
                            candles[ts] = dict(instrument_key=key, timestamp=ts, open=float(c[1]), high=float(c[2]), low=float(c[3]), close=float(c[4]), volume=int(c[5]))
                    await asyncio.sleep(1.05)
                selected = [candles[t] for t in sorted(candles)[-window:]]
                minimum = strategy.metadata.min_candles
                coverage.append(dict(symbol=instrument['symbol'], candles=len(selected), required=minimum, sufficient=len(selected) >= minimum))
                if selected:
                    await upsert_candles([dict(r, timeframe=timeframe) for r in selected])
                if len(selected) >= minimum:
                    rows.extend(selected)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                failures.append(dict(symbol=instrument['symbol'], error=type(exc).__name__))
    frame = pl.DataFrame(rows) if rows else pl.DataFrame()
    # Internal execution context, not a user strategy parameter.
    results = await asyncio.to_thread(strategy.run, frame, {i['key']: i for i in instruments}, dict(resolved, _timeframe=timeframe))
    return dict(strategy_id=strategy.metadata.id, strategy_name=strategy.metadata.name, timeframe=timeframe,
                total_scanned=sum(c['sufficient'] for c in coverage), total_matched=len(results), results=results,
                scanned_at=now.isoformat(), cached=False, coverage=coverage, errors=failures)
