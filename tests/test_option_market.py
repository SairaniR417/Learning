import asyncio
from datetime import datetime, timedelta
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from database.connection import Base
from database.models import OptionChainSnapshot
from services import option_market as market


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_requests_share_fetch_and_cache(self):
        cache = market.SharedCache(2)
        gate = asyncio.Event()
        async def load():
            await gate.wait()
            return {'value': 1}
        loader = AsyncMock(side_effect=load)
        callers = [asyncio.create_task(cache.get('key', 55, loader)) for _ in range(5)]
        await asyncio.sleep(0)
        gate.set()
        results = await asyncio.gather(*callers)
        self.assertEqual(results, [{'value': 1}] * 5)
        self.assertEqual(await cache.get('key', 55, loader), {'value': 1})
        loader.assert_awaited_once()

    async def test_cancelled_viewer_does_not_cancel_shared_fetch(self):
        cache = market.SharedCache()
        gate = asyncio.Event()
        async def load():
            await gate.wait()
            return 3
        first = asyncio.create_task(cache.get('key', 10, load))
        second = asyncio.create_task(cache.get('key', 10, load))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        gate.set()
        self.assertEqual(await second, 3)

    async def test_expiration_eviction_and_failed_requests_retry(self):
        cache = market.SharedCache(1)
        loader = AsyncMock(return_value=1)
        await cache.get('one', -1, loader)
        await cache.get('one', 10, loader)
        self.assertEqual(loader.await_count, 2)
        await cache.get('two', 10, loader)
        self.assertEqual(list(cache.entries), ['two'])
        failing = AsyncMock(side_effect=ValueError('provider'))
        for _ in range(2):
            with self.assertRaises(ValueError):
                await cache.get('bad', 10, failing)
        self.assertEqual(failing.await_count, 2)
        self.assertFalse(cache.pending)


class MarketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cache_patch = patch.object(market, 'cache', market.SharedCache())
        self.cache_patch.start()
        self.expiry = datetime.now(market.option_chain.INDIA).date() + timedelta(days=20)

    async def asyncTearDown(self):
        self.cache_patch.stop()

    async def test_indices_allowed_and_outside_stock_rejected(self):
        for index in market.INDICES:
            await market.require_key(index['key'])
        with self.assertRaises(HTTPException):
            await market.require_key('NSE_EQ|OUTSIDE')
        response = await market.underlyings()
        self.assertEqual(len(response['underlyings']), 216)

    async def test_chain_cached_by_token_key_and_expiry(self):
        loader = AsyncMock(return_value={'rows': [], 'receivedAt': datetime.now().isoformat()})
        with patch.object(market.option_chain, 'chain', loader), patch.dict('os.environ', {'OPTION_CHAIN_SAVE_SNAPSHOTS': 'false'}):
            for token in ['a', 'a', 'b']:
                await market.chain(AsyncMock(), token, market.INDICES[0]['key'], self.expiry)
        self.assertEqual(loader.await_count, 2)

    async def test_mcx_chain_uses_only_selected_contracts_and_preserves_missing(self):
        key = 'MCX_FO|123'
        contracts = [dict(underlying_key=key, underlying_symbol='GOLD', expiry=self.expiry.isoformat(),
                          instrument_key=f'MCX_FO|{n}', instrument_type=side, strike_price=100)
                     for n, side in [(1, 'CE'), (2, 'PE')]]
        contracts.append(dict(contracts[0], underlying_key='MCX_FO|OTHER', instrument_key='MCX_FO|OTHER_CE'))
        provider = AsyncMock(return_value={'status': 'success', 'data': {
            'spot': {'instrument_token': key, 'last_price': 102},
            'call': {'instrument_token': 'MCX_FO|1', 'last_price': 0, 'oi': 200,
                     'depth': {'buy': [{'price': 4}], 'sell': [{'price': 5}]}}
        }})
        async def passthrough(request, *args, **kwargs):
            return await request(*args, **kwargs)
        with patch.object(market, 'mcx_contracts', AsyncMock(return_value=contracts)), \
             patch.object(market, 'limited_request', side_effect=passthrough):
            result = await market.commodity_chain(provider, 'token', key, self.expiry)
        self.assertEqual(result['atmStrike'], 100)
        self.assertEqual(result['rows'][0]['call']['ltp'], 0)
        self.assertEqual(result['rows'][0]['call']['bid_price'], 4)
        self.assertIsNone(result['rows'][0]['put']['ltp'])
        self.assertIn('Missing quotes: 1', result['warning'])
        self.assertEqual(provider.call_args.kwargs['params']['instrument_key'], f'{key},MCX_FO|1,MCX_FO|2')

    async def test_optional_snapshot_saved_only_on_cache_miss(self):
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        factory = async_sessionmaker(engine)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            loader = AsyncMock(return_value={'rows': [], 'receivedAt': datetime.now(market.timezone.utc).isoformat()})
            with patch.object(market.option_chain, 'chain', loader), \
                 patch('database.connection.async_session_factory', factory), \
                 patch.dict('os.environ', {'OPTION_CHAIN_SAVE_SNAPSHOTS': 'true'}):
                for _ in range(2):
                    await market.chain(AsyncMock(), 'token', market.INDICES[0]['key'], self.expiry)
            async with factory() as session:
                self.assertEqual(await session.scalar(select(func.count()).select_from(OptionChainSnapshot)), 1)
        finally:
            await engine.dispose()
