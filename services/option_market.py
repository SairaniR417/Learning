"""On-demand option discovery, shared snapshots and MCX quote assembly."""
import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import logging
import os
import time

import httpx
from fastapi import HTTPException
from scanner.universe import get_fno_stocks, require_fno_key
from services import option_chain

INDICES = [
    {'key': 'NSE_INDEX|Nifty 50', 'symbol': 'NIFTY', 'name': 'Nifty 50', 'group': 'Indices'},
    {'key': 'NSE_INDEX|Nifty Bank', 'symbol': 'BANKNIFTY', 'name': 'Bank Nifty', 'group': 'Indices'},
    {'key': 'BSE_INDEX|SENSEX', 'symbol': 'SENSEX', 'name': 'Sensex', 'group': 'Indices'},
]


class SharedCache:
    def __init__(self, capacity=512):
        self.entries = OrderedDict()
        self.pending = {}
        self.capacity = capacity

    async def get(self, key, ttl, load):
        cached = self.entries.get(key)
        if cached and cached[0] > time.monotonic():
            self.entries.move_to_end(key)
            return cached[1]
        if key not in self.pending:
            async def fetch():
                try:
                    value = await load()
                    self.entries[key] = (time.monotonic() + ttl, value)
                    self.entries.move_to_end(key)
                    while len(self.entries) > self.capacity:
                        self.entries.popitem(last=False)
                    return value
                finally:
                    self.pending.pop(key, None)
            task = asyncio.create_task(fetch())
            # A disconnected caller must not cancel a fetch shared by other viewers.
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            self.pending[key] = task
        return await asyncio.shield(self.pending[key])


cache = SharedCache()
_request_lock = asyncio.Lock()
_last_request = 0.0


async def limited_request(request, *args, **kwargs):
    global _last_request
    async with _request_lock:
        await asyncio.sleep(max(0, 1.0 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        try:
            return await request(*args, **kwargs)
        except httpx.HTTPError as exc:
            raise HTTPException(502, 'Option market data is temporarily unavailable. Please retry.') from exc


def contract_date(row):
    value = row['expiry']
    return (datetime.fromtimestamp(value / 1000, option_chain.INDIA).date()
            if isinstance(value, (int, float)) else datetime.fromisoformat(value).date())


async def mcx_contracts():
    async def load():
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get('https://assets.upstox.com/market-quote/instruments/exchange/MCX.json.gz')
                response.raise_for_status()
            rows = json.loads(gzip.decompress(response.content))
            names = {r['instrument_key']: r.get('trading_symbol', r.get('name', ''))
                     for r in rows if r.get('instrument_type') == 'FUT'}
            today = datetime.now(option_chain.INDIA).date()
            return [dict(r, underlying_label=names.get(r.get('underlying_key'), r.get('underlying_symbol', '')))
                    for r in rows if r.get('instrument_type') in {'CE', 'PE'}
                    and r.get('underlying_key', '').startswith('MCX_FO|')
                    and contract_date(r) >= today]
        except (httpx.HTTPError, ValueError, OSError, KeyError, TypeError) as exc:
            raise HTTPException(502, 'Commodity contract list is unavailable. Please retry.') from exc
    # Daily boundary prevents yesterday's expired contracts lingering into a new day.
    return await cache.get(('mcx', str(datetime.now(option_chain.INDIA).date())), 3600, load)


async def underlyings(commodities=False):
    if commodities:
        rows = await mcx_contracts()
        by_key = {r['underlying_key']: {'key': r['underlying_key'], 'symbol': r['underlying_symbol'],
                  'name': r.get('underlying_label', r['underlying_symbol']),
                  'group': 'Commodities'} for r in rows}
        return {'underlyings': sorted(by_key.values(), key=lambda r: (r['symbol'], r['key']))}
    return {'underlyings': INDICES + [dict(key=s['key'], symbol=s['symbol'], name=s['name'], group='F&O stocks')
                                     for s in get_fno_stocks()]}


async def require_key(key):
    if key in {i['key'] for i in INDICES}:
        return
    if key.startswith('MCX_FO|'):
        if any(r['underlying_key'] == key for r in await mcx_contracts()):
            return
        raise HTTPException(400, 'Select a listed commodity underlying.')
    require_fno_key(key)


async def expiries(request, token, key):
    await require_key(key)
    async def load():
        if key.startswith('MCX_FO|'):
            return {'expiries': sorted({contract_date(r).isoformat() for r in await mcx_contracts()
                                       if r['underlying_key'] == key})}
        return await option_chain.expiries(lambda *a, **k: limited_request(request, *a, **k), token, key)
    return await cache.get(('expiries', hashlib.sha256(token.encode()).hexdigest(), key,
                            str(datetime.now(option_chain.INDIA).date())), 900, load)


async def commodity_chain(request, token, key, expiry):
    contracts = [r for r in await mcx_contracts() if r['underlying_key'] == key and contract_date(r) == expiry]
    if not contracts:
        raise HTTPException(400, 'Select an available commodity expiry.')
    keys = [key] + [r['instrument_key'] for r in contracts]
    quotes = {}
    for offset in range(0, len(keys), 500):
        payload = await limited_request(request, 'https://api.upstox.com/v2/market-quote/quotes',
            headers={'Authorization': f'Bearer {token}'}, params={'instrument_key': ','.join(keys[offset:offset + 500])})
        if not isinstance(payload, dict) or payload.get('status') != 'success' or not isinstance(payload.get('data'), dict):
            raise HTTPException(502, 'Commodity quotes are unavailable.')
        quotes.update({q['instrument_token']: q for q in payload['data'].values() if q.get('instrument_token')})
    rows = {}
    missing = 0
    for contract in contracts:
        strike = contract['strike_price']
        row = rows.setdefault(strike, {'strike': strike, 'call': option_chain.leg(None), 'put': option_chain.leg(None)})
        quote = quotes.get(contract['instrument_key'], {})
        if not quote:
            missing += 1
        depth = quote.get('depth') or {}
        def best(side):
            levels = depth.get(side) or []
            return levels[0].get('price') if levels else None
        row['call' if contract['instrument_type'] == 'CE' else 'put'] = option_chain.leg({'market_data': {
            'ltp': quote.get('last_price'), 'oi': quote.get('oi'), 'volume': quote.get('volume'),
            'bid_price': best('buy'), 'ask_price': best('sell')}})
    if missing == len(contracts):
        raise HTTPException(502, 'No commodity option quotes returned. Check your MCX market-data access.')
    spot = option_chain.number(quotes.get(key, {}).get('last_price'))
    result = sorted(rows.values(), key=lambda r: r['strike'])
    return {'rows': result, 'spot': spot,
            'atmStrike': min(result, key=lambda r: abs(r['strike'] - spot))['strike'] if spot and result else None,
            'expiry': expiry.isoformat(), 'receivedAt': datetime.now(timezone.utc).isoformat(),
            'warning': f'MCX chain assembled from contract quotes; underlying is a futures contract. Greeks unavailable. Missing quotes: {missing}.'}


async def chain(request, token, key, expiry):
    await require_key(key)
    if expiry < datetime.now(option_chain.INDIA).date():
        raise HTTPException(400, 'Select a current or upcoming expiry.')
    async def load():
        result = (await commodity_chain(request, token, key, expiry) if key.startswith('MCX_FO|') else
                  await option_chain.chain(lambda *a, **k: limited_request(request, *a, **k), token, key, expiry))
        if os.getenv('OPTION_CHAIN_SAVE_SNAPSHOTS', 'false').lower() in {'true', '1', 'yes'}:
            try:
                from database.connection import async_session_factory
                from database.models import OptionChainSnapshot
                async with async_session_factory() as session:
                    session.add(OptionChainSnapshot(instrument_key=key, expiry=expiry,
                        received_at=datetime.fromisoformat(result['receivedAt']), content_json=json.dumps(result)))
                    await session.commit()
            except Exception:
                logging.getLogger(__name__).exception('Option snapshot could not be saved')
                result = dict(result, warning=(result.get('warning', '') + ' Snapshot could not be saved.').strip())
        return result
    return await cache.get(('chain', hashlib.sha256(token.encode()).hexdigest(), key, expiry.isoformat()), 55, load)
