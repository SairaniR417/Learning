"""Validated latest-price snapshots for every chart instrument."""
import asyncio
import math
from datetime import datetime, timezone
from fastapi import HTTPException
from services import option_market, option_analysis


async def latest(request, token, key, expiry=None, strike=None, side='CE'):
    async with asyncio.timeout(15):
        if expiry is not None or strike is not None:
            if expiry is None or strike is None or side not in {'CE','PE'} or not math.isfinite(strike) or strike <= 0:
                raise HTTPException(400, 'Select a valid option contract.')
            contract = await option_analysis.resolve_contract(request, token, key, expiry, strike, side)
            key = contract['instrument_key']
        else:
            await option_market.require_key(key)
        async def load():
            payload = await request('https://api.upstox.com/v3/market-quote/ltp',
                headers={'Authorization': f'Bearer {token}'}, params={'instrument_key': key})
            rows = payload.get('data', {}) if isinstance(payload, dict) else {}
            row = next((r for r in rows.values() if isinstance(r, dict) and r.get('instrument_token') == key), None) if isinstance(rows, dict) else None
            price = row.get('last_price') if row else None
            if isinstance(price, bool) or not isinstance(price, (int,float)) or not math.isfinite(price) or price <= 0:
                raise HTTPException(502, 'Latest price unavailable for this instrument.')
            return dict(instrumentKey=key, price=price, receivedAt=datetime.now(timezone.utc).isoformat())
        # Match the polling interval without refetching when multiple chart views overlap.
        import hashlib
        return await option_market.cache.get(('chart-ltp',hashlib.sha256(token.encode()).hexdigest(),key),10,load)
