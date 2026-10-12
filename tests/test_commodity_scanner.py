import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import HTTPException
from scanner.strategies.base import StrategyMetadata, StrategyParameter
from services.commodity_scanner import scan_commodities


class DummyStrategy:
    metadata = StrategyMetadata(id='test', name='Test', description='Test', min_candles=2,
                                parameters=[StrategyParameter(name='period', display_name='Period', type='int', default=2, min_value=2, max_value=10)])
    def candle_window(self, params):
        return 3
    def run(self, frame, instruments, params):
        assert params['_timeframe'] == '15m'
        assert frame.height == 2
        assert set(frame['instrument_key']) == {'MCX_FO|123'}
        return [{'instrumentKey': 'MCX_FO|123', 'exchange': 'MCX', 'status': 'BUY'}]


class CommodityScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_deduplication_open_bar_exclusion_and_persistence(self):
        now = datetime.now(timezone.utc)
        bars = [[(now-timedelta(minutes=m)).isoformat(), 100, 102, 99, 101, 1000] for m in (45, 30, 0)]
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'status': 'success', 'data': {'candles': bars}})))
        with patch('services.commodity_scanner.get_mcx_front_month_universe', AsyncMock(return_value=[{'key': 'MCX_FO|123', 'symbol': 'GOLD', 'exchange': 'MCX'}])), \
             patch('services.commodity_scanner.httpx.AsyncClient', return_value=client), \
             patch('services.commodity_scanner.upsert_instruments', AsyncMock()), \
             patch('services.commodity_scanner.upsert_candles', AsyncMock()) as save, \
             patch('services.commodity_scanner.asyncio.sleep', AsyncMock()):
            result = await scan_commodities(DummyStrategy(), '15m', {}, 'mock-token')
        self.assertEqual(result['total_scanned'], 1)
        self.assertEqual(result['results'][0]['exchange'], 'MCX')
        self.assertEqual(len(save.await_args.args[0]), 2)
        self.assertEqual(result['coverage'][0]['candles'], 2)

    async def test_bad_parameters_rejected_before_provider_calls(self):
        for params in ({'period': 1}, {'period': 2.5}, {'unknown': 5}):
            with self.assertRaises(HTTPException):
                await scan_commodities(DummyStrategy(), '15m', params, 'mock-token')

    async def test_unsupported_timeframe_rejected(self):
        with self.assertRaises(HTTPException):
            await scan_commodities(DummyStrategy(), '1w', {}, 'mock-token')


if __name__ == '__main__':
    unittest.main()
