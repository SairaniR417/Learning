"""Shared strategy workspace for verified index and commodity underlyings."""
import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from services import underlying_analysis as analysis
from scanner.strategies import strategy_registry

INDEX = 'NSE_INDEX|Nifty 50'
FUTURE = 'MCX_FO|123'
ITEMS = [dict(key=INDEX,symbol='NIFTY',name='Nifty 50',group='Indices'),
         dict(key=FUTURE,symbol='GOLD',name='Gold October futures',group='Commodities')]


def history(key, interval):
    now = datetime.now(timezone.utc)
    step = timedelta(minutes=interval)
    rows=[]
    for n in range(260):
        close=100+math.sin(n/9)*4+n*.02
        rows.append(dict(instrument_key=key,timestamp=now-step*(261-n),open=close-.1,
                         high=close+1,low=close-1,close=close,volume=0 if key == INDEX else 1000))
    forming=dict(rows[-1],timestamp=now-timedelta(seconds=1),close=rows[-1]['close']+.1)
    return dict(candles=rows,formingCandles=[forming],invalidCandles=0)


class UnderlyingWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_indices_and_futures_get_all_shared_overlays_for_the_exact_key(self):
        for key in (INDEX,FUTURE):
            with self.subTest(key=key):
                async def fetch(request,token,requested_key,interval):
                    return history(requested_key,interval)
                with patch.object(analysis.option_market,'require_key',AsyncMock()), \
                     patch.object(analysis.option_market,'underlyings',AsyncMock(return_value={'underlyings':ITEMS})), \
                     patch.object(analysis.option_analysis,'history',AsyncMock(side_effect=fetch)) as load:
                    result=await analysis.analyze(None,'token',key,'5m',2,
                        rsi_settings={'period':10,'timeframe':15},sutradhar_settings={'p1':10,'p2':6,'p3':4})
                self.assertEqual({r['id'] for r in result['strategies']},
                                 {r['id'] for r in strategy_registry.list_strategies()})
                self.assertEqual(result['contract']['key'],key)
                self.assertEqual({c.args[2] for c in load.await_args_list},{key})
                self.assertEqual([c.args[3] for c in load.await_args_list],[5,15,1440])
                self.assertEqual(result['rsiDivergence']['settings']['period'],10)
                self.assertEqual(len(result['candles']),260)
                self.assertEqual(len(result['ghostRider']['candles']),261)
                self.assertTrue(result['ghostRider']['developingBar'])
                self.assertFalse(result['staleData'])
                self.assertFalse(result['storedPreview'])
                self.assertIn('underlying price',result['underlying']['description'])
                if key == FUTURE:
                    self.assertEqual(result['sutradhar']['status'],'UNAVAILABLE')
                    self.assertIn('continuous',result['sutradhar']['message'])

    async def test_stock_key_does_not_bypass_stock_data_path(self):
        with patch.object(analysis.option_market,'require_key',AsyncMock()), \
             patch.object(analysis.option_market,'underlyings',AsyncMock(return_value={'underlyings':ITEMS})), \
             patch.object(analysis.option_analysis,'history',AsyncMock()) as load:
            with self.assertRaises(HTTPException):
                await analysis.analyze(None,'token','NSE_EQ|INE002A01018')
        load.assert_not_awaited()

    async def test_provider_failure_propagates_for_old_data_alert(self):
        with patch.object(analysis.option_market,'require_key',AsyncMock()), \
             patch.object(analysis.option_market,'underlyings',AsyncMock(return_value={'underlyings':ITEMS})), \
             patch.object(analysis.option_analysis,'history',AsyncMock(side_effect=HTTPException(502,'Unavailable'))):
            with self.assertRaises(HTTPException) as error:
                await analysis.analyze(None,'token',INDEX)
        self.assertEqual(error.exception.status_code,502)

    async def test_unsupported_timeframe_never_fetches_candles(self):
        with patch.object(analysis.option_market,'require_key',AsyncMock()), \
             patch.object(analysis.option_market,'underlyings',AsyncMock(return_value={'underlyings':ITEMS})), \
             patch.object(analysis.option_analysis,'history',AsyncMock()) as load:
            with self.assertRaises(HTTPException):
                await analysis.analyze(None,'token',INDEX,'2m')
        load.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
