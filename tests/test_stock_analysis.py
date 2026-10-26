import math
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock,patch
import polars as pl

from fastapi import HTTPException
from services import stock_analysis as analysis
from scanner.strategies import strategy_registry

KEY='NSE_EQ|INE002A01018'


def rows(count=300,developing=False):
    start=datetime(2025,1,1,tzinfo=timezone.utc)
    result=[]
    for n in range(count):
        price=100+math.sin(n/9)*4+n*.02
        result.append(dict(timestamp=(start+timedelta(days=n)).isoformat(),open=price-.1,high=price+1,low=price-1,close=price,volume=1000))
    if developing:
        result.append(dict(timestamp=datetime.now(timezone.utc).isoformat(),open=108,high=111,low=107,close=110,volume=500,developing=True))
    return result


class StockWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_stored_preview_never_waits_for_broker_and_keeps_all_strategies(self):
        from services import ghost_scanner
        stored=[dict(r,timestamp=datetime.fromisoformat(r['timestamp']),instrument_key=KEY) for r in rows()]
        with patch.object(ghost_scanner,'load_stock_candles',AsyncMock(return_value=pl.DataFrame(stored))) as load, \
             patch.object(analysis.stock_chart,'stock_chart',AsyncMock()) as live:
            result=await analysis.analyze(KEY,stored_only=True)
        live.assert_not_called()
        self.assertEqual({call.args for call in load.await_args_list},{(KEY,'1d'),(KEY,'5m')})
        self.assertTrue(result['storedPreview'])
        self.assertTrue(result['staleData'])
        self.assertEqual(len(result['candles']),300)
        self.assertEqual({s['id'] for s in result['strategies']},{s['id'] for s in strategy_registry.list_strategies()})
        self.assertTrue(all('status' in s and 'name' in s for s in result['strategies']))

    async def test_all_strategies_selected_stock_and_developing_policy(self):
        async def chart(key,frame):
            return dict(candles=rows(developing=True),warning=None)
        with patch.object(analysis.stock_chart,'stock_chart',AsyncMock(side_effect=chart)) as fetch:
            result=await analysis.analyze(KEY)
        self.assertEqual({s['id'] for s in result['strategies']},{s['id'] for s in strategy_registry.list_strategies()})
        self.assertEqual(len(result['candles']),300)
        self.assertEqual(len(result['ghostRider']['candles']),301)
        self.assertTrue(result['ghostRider']['developingBar'])
        self.assertEqual(result['rsiDivergence']['interval'],1440)
        self.assertEqual({call.args[0] for call in fetch.await_args_list},{KEY})
        self.assertEqual([call.args[1] for call in fetch.await_args_list],['1d','5m'])
        self.assertFalse(any('premium setup' in s['scenario'] for s in result['strategies']))
        self.assertIn('RELIANCE',result['contract']['name'])
        self.assertIsNone(result['underlying']['supportsPremium'])

    async def test_offline_daily_history_still_renders(self):
        async def chart(key,frame):
            return dict(candles=rows() if frame=='1d' else [],warning='Connect Upstox for live candles.')
        with patch.object(analysis.stock_chart,'stock_chart',AsyncMock(side_effect=chart)):
            result=await analysis.analyze(KEY)
        self.assertEqual(len(result['candles']),300)
        self.assertEqual(result['warnings'].count('Connect Upstox for live candles.'),1)
        self.assertTrue(result['staleData'])
        self.assertEqual(result['dataAsOf'], result['candles'][-1]['timestamp'])
        self.assertTrue(any('5-minute' in w for w in result['warnings']))

    async def test_sutradhar_and_secondary_rsi_reuse_same_stock_frames(self):
        async def chart(key,frame):
            return dict(candles=rows(),warning=None)
        with patch.object(analysis.stock_chart,'stock_chart',AsyncMock(side_effect=chart)) as fetch:
            result=await analysis.analyze(KEY,'5m',rsi_settings={'timeframe':15},sutradhar_settings={'p1':10,'p2':6,'p3':4})
        self.assertEqual([c.args[1] for c in fetch.await_args_list],['5m','15m','1d'])
        self.assertEqual(result['rsiDivergence']['interval'],15)
        self.assertIsNotNone(result['sutradhar'])
        self.assertEqual(result['sutradhar']['settings']['p1'],10)

    async def test_invalid_scope_or_settings_never_fetch(self):
        with patch.object(analysis.stock_chart,'stock_chart',AsyncMock()) as fetch:
            for key,frame,settings in [('NSE_INDEX|Nifty 50','1d',None),(KEY,'2m',None),(KEY,'1d',{'period':0})]:
                with self.assertRaises(HTTPException):
                    await analysis.analyze(key,frame,rsi_settings=settings)
        fetch.assert_not_called()
