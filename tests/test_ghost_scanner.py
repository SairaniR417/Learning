import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import polars as pl
from fastapi.testclient import TestClient
import main
from scanner.strategies.ghost_rider import GhostRiderStrategy
from scanner.strategies.registry import StrategyRegistry
from scanner.strategies import registry as registry_module
from services.ghost_rider_overlay import calculate
from services import ghost_scanner

KEY='NSE_EQ|INE002A01018'


def fixture(count=300):
    return [dict(instrument_key=KEY,timestamp=datetime(2020,1,1,tzinfo=timezone.utc)+timedelta(minutes=i*5),
        open=100+math.sin(i/9)*5,close=100+math.sin(i/9)*5,high=101+math.sin(i/9)*5,low=99+math.sin(i/9)*5,volume=1000)
        for i in range(count)]


class SharedScannerTests(unittest.IsolatedAsyncioTestCase):
    def test_scanner_matches_option_pine_engine_and_does_not_need_250_bars(self):
        rows=fixture(70)
        overlay=calculate(rows,rows,5,2)
        result=GhostRiderStrategy().run(pl.DataFrame(rows),{KEY:dict(symbol='RELIANCE',exchange='NSE')},
            dict(_timeframe='5m',atr_multiplier=2,_five_minute_rows={KEY:rows}))[0]
        self.assertEqual(result['entry'],overlay['setup']['entry'])
        self.assertEqual(result['signalAt'],overlay['setup']['signalAt'])
        self.assertEqual(result['stopLoss'],overlay['setup']['stopLoss'])
        self.assertEqual(result['dashboard'],overlay['dashboard'])
        for target in overlay['setup']['targets']:
            self.assertEqual(result[f"tp{target['number']}"],target['price'])
            self.assertEqual(result[f"tp{target['number']}Hit"],target['hit'])

    def test_unfinished_candle_excluded(self):
        now=datetime.now(timezone.utc)
        rows=fixture(30)+[dict(fixture(1)[0],timestamp=now-timedelta(minutes=1),close=500,high=501)]
        self.assertEqual(len(ghost_scanner.completed_rows(rows,'5m',now)),30)

    async def test_registry_accepts_intraday_and_tracks_five_minute_revision(self):
        frame=pl.DataFrame(fixture())
        async def revision(timeframe): return 7 if timeframe=='5m' else 3
        with patch.object(registry_module,'get_candle_revision',AsyncMock(side_effect=revision)), \
             patch.object(registry_module,'get_cached_strategy_result',AsyncMock(return_value=None)), \
             patch.object(registry_module,'get_all_active_instruments',AsyncMock(return_value=[dict(key=KEY,symbol='RELIANCE',exchange='NSE')])), \
             patch.object(registry_module,'load_recent_candles_polars',AsyncMock(return_value=frame)), \
             patch.object(registry_module,'save_strategy_result_cache',AsyncMock()) as save:
            result=await StrategyRegistry().execute_scan('ghost_rider',timeframe='15m',params={'atr_multiplier':25})
        self.assertEqual(result['total_scanned'],1)
        self.assertTrue(result['results'])
        self.assertIn(':pine-v2:5m-v7',save.call_args.kwargs['cache_key'])
        self.assertEqual(save.call_args.kwargs['params'],{'atr_multiplier':25})

    async def test_stored_chart_has_same_overlay_without_broker_auth(self):
        frame=pl.DataFrame(fixture())
        with patch.object(ghost_scanner,'load_stock_candles',AsyncMock(return_value=frame)), \
             patch.object(main,'require_token',side_effect=AssertionError('No broker login needed')):
            client=TestClient(main.app)
            response=client.get('/api/stocks/ghost-rider',params={'instrument_key':KEY,'timeframe':'5m','atr_multiplier':2})
        self.assertEqual(response.status_code,200,response.text)
        body=response.json()
        self.assertEqual(len(body['candles']),300)
        self.assertEqual(body['ghostRider']['multiplier'],2)
        self.assertEqual(body['ghostRider']['dashboard'],calculate(fixture(),fixture(),5,2)['dashboard'])
        self.assertEqual(body['strategies'][0]['id'],'ghost_rider')
        self.assertEqual(client.get('/api/stocks/ghost-rider',params={'instrument_key':'NSE_EQ|OUTSIDE'}).status_code,400)
        self.assertEqual(client.get('/api/stocks/ghost-rider',params={'instrument_key':KEY,'timeframe':'1w'}).status_code,400)

    async def test_empty_history_is_reported(self):
        with patch.object(ghost_scanner,'load_stock_candles',AsyncMock(return_value=pl.DataFrame())):
            body=await ghost_scanner.stock_chart(KEY,'5m')
        self.assertEqual(body['strategies'][0]['status'],'NO_HISTORY')
        self.assertEqual(body['candles'],[])
