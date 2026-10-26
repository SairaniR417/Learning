"""Route contract tests without starting the database or broker client."""
import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


class HTTPException(Exception):
    def __init__(self, status, detail):
        self.status_code = status
        self.detail = detail


class UnderlyingChartRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'main.py'
        node = next(n for n in ast.parse(source.read_text(encoding='utf-8-sig')).body
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == 'underlying_chart')
        node.decorator_list = []
        self.request = object()
        namespace = {'asyncio': asyncio, 'HTTPException': HTTPException,
                     'api_json_request': self.request, 'require_token': lambda: 'token'}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
        self.route = namespace['underlying_chart']
        self.market = SimpleNamespace(require_key=AsyncMock())
        self.analysis = SimpleNamespace(history=AsyncMock())
        services = ModuleType('services')
        services.option_market, services.option_analysis = self.market, self.analysis
        self.modules = patch.dict(sys.modules, {'services': services})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    async def test_rejects_unsupported_interval_before_fetch(self):
        with self.assertRaises(HTTPException) as error:
            await self.route('NSE_INDEX|Nifty 50', 7)
        self.assertEqual(error.exception.status_code, 400)
        self.analysis.history.assert_not_awaited()

    async def test_rejects_unlisted_instrument_before_fetch(self):
        self.market.require_key.side_effect = HTTPException(400, 'Unknown key')
        with self.assertRaises(HTTPException):
            await self.route('UNKNOWN', 5)
        self.analysis.history.assert_not_awaited()

    async def test_returns_bounded_completed_and_developing_candles(self):
        row = dict(timestamp=datetime.now(timezone.utc), open=100, high=102, low=99,
                   close=101, volume=10, instrument_key='MCX_FO|123')
        self.analysis.history.return_value = dict(candles=[row]*1000,
                                                  formingCandles=[dict(row, close=102)], invalidCandles=2)
        result = await self.route('MCX_FO|123', 15)
        self.assertEqual(len(result['candles']), 1000)
        self.assertEqual(result['candles'][-1]['close'], 102)
        self.assertNotIn('instrument_key', result['candles'][0])
        self.assertEqual(result['invalidCandles'], 2)
        self.analysis.history.assert_awaited_once_with(self.request, 'token', 'MCX_FO|123', 15)

    async def test_timeout_returns_retryable_error(self):
        self.analysis.history.side_effect = TimeoutError()
        with self.assertRaises(HTTPException) as error:
            await self.route('NSE_INDEX|Nifty 50', 5)
        self.assertEqual(error.exception.status_code, 504)


if __name__ == '__main__':
    unittest.main()
