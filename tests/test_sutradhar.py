"""Sutradhar source formulas, causal daily alignment and on-demand integration."""
import asyncio
import json
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock,patch
import polars as pl
from fastapi.testclient import TestClient
from services import sutradhar,option_analysis,option_market,sutradhar_scanner
from scanner.strategies.sutradhar import SutradharStrategy


KEY='NSE_EQ|TEST'
def fixture():
    start=datetime.fromisoformat('2025-01-01T00:00:00+05:30').astimezone(timezone.utc)
    daily=[dict(instrument_key=KEY,timestamp=start+timedelta(days=i),open=100.+i,high=102.+2*i,low=99.,close=101.+i,volume=1000) for i in range(20)]
    intraday=[dict(instrument_key=KEY,timestamp=start+timedelta(days=19,hours=9,minutes=15+15*i),open=119.+i,high=125.,low=115.,close=120.+i,volume=1000) for i in range(3)]
    return intraday,daily


class SutradharTests(unittest.TestCase):
    def test_sma_prior_daily_ranges_and_all_eight_levels(self):
        rows,daily=fixture();result=sutradhar.calculate(rows,daily)
        self.assertEqual(result['status'],'LEVELS_READY')
        for point in result['points']:
            for period,upper,lower in [(14,'Flow','Value'),(7,'Crest','Base'),(5,'Crown','Origin')]:
                prior=daily[19-period:19]
                width=(sum(r['high'] for r in prior)-sum(r['low'] for r in prior))/period
                self.assertAlmostEqual(point[upper],119+width/2)
                self.assertAlmostEqual(point[lower],119-width/2)
            self.assertEqual(point['Mid'],119)
            self.assertEqual(point['O'],119)

    def test_current_daily_extremes_and_future_candles_cannot_leak(self):
        rows,daily=fixture();before=sutradhar.calculate(rows,daily)
        changed=[dict(r) for r in daily];changed[-1].update(high=10000.,low=.1,close=1000.)
        changed.append(dict(changed[-1],timestamp=changed[-1]['timestamp']+timedelta(days=1),open=2000.))
        after=sutradhar.calculate(rows,changed)
        self.assertEqual(before['points'],after['points'])
        # A prefix must agree with its own calculation before later daily bars arrive.
        yesterday=[dict(rows[0],timestamp=rows[0]['timestamp']-timedelta(days=1))]
        self.assertEqual(sutradhar.calculate(yesterday,daily)['points'],sutradhar.calculate(yesterday,daily[:-1])['points'])

    def test_ema_uses_pine_first_value_seed_and_shift(self):
        rows,daily=fixture()
        result=sutradhar.calculate(rows,daily,settings=dict(p1=3,p2=2,p3=1,use_ema=True))
        for period,upper,lower in [(3,'Flow','Value'),(2,'Crest','Base'),(1,'Crown','Origin')]:
            h,l=daily[0]['high'],daily[0]['low']
            for row in daily[1:19]:
                h+=(row['high']-h)*2/(period+1);l+=(row['low']-l)*2/(period+1)
            self.assertAlmostEqual(result['points'][-1][upper],119+(h-l)/2)
            self.assertAlmostEqual(result['points'][-1][lower],119-(h-l)/2)

    def test_warmup_preserves_partial_levels_and_never_assumes_midday_open(self):
        rows,daily=fixture()
        result=sutradhar.calculate(rows,daily[-8:])
        self.assertEqual(result['status'],'INSUFFICIENT_HISTORY')
        self.assertIsNone(result['points'][-1]['Flow'])
        self.assertIsNotNone(result['points'][-1]['Crown'])
        self.assertEqual(result['points'][-1]['O'],119)
        missing=sutradhar.calculate(rows,daily[:-1])
        self.assertIsNone(missing['points'][-1]['O'])
        self.assertEqual(sutradhar.stored_session_open(rows[1:]),{})
        opened=sutradhar.calculate(rows,daily[:-1],session_opens=sutradhar.stored_session_open(rows))
        self.assertEqual(opened['status'],'LEVELS_READY')
        self.assertEqual(opened['points'][-1]['O'],rows[0]['open'])
        self.assertEqual(opened['dailyCandles'],19)

    def test_intraday_guard_continuous_futures_and_config_validation(self):
        rows,daily=fixture()
        for interval in (1440,10080):self.assertEqual(sutradhar.calculate(rows,daily,interval)['status'],'UNSUPPORTED_TIMEFRAME')
        self.assertEqual(sutradhar.calculate(rows,daily,continuous_futures=True)['status'],'UNAVAILABLE')
        for params in [dict(p1=True),dict(p2=0),dict(p3=1.5),dict(use_ema=1),dict(extra=2)]:
            with self.assertRaises(ValueError):sutradhar.SutradharConfig.resolve(params)

    def test_stock_scanner_and_chart_share_engine_without_invented_trade_signal(self):
        rows,daily=fixture();expected=sutradhar.calculate(rows,daily)['points'][-1]
        results=SutradharStrategy().run(pl.DataFrame(rows),{KEY:dict(symbol='TEST')},{'_timeframe':'15m','_daily_rows':{KEY:daily}})
        self.assertEqual(len(results),1)
        for name in sutradhar.LEVELS:self.assertEqual(results[0][name],expected[name])
        self.assertNotIn('entry',results[0]);self.assertNotIn('signal',results[0]);self.assertNotIn('stopLoss',results[0])
        self.assertEqual(SutradharStrategy().run(pl.DataFrame(rows),{KEY:dict(symbol='TEST')},{'_timeframe':'1d'}),[])
        async def load(key,timeframe):return pl.DataFrame(daily if timeframe=='1d' else rows)
        with patch.object(sutradhar_scanner,'require_fno_key'),patch.object(sutradhar_scanner,'get_fno_stocks',return_value=[dict(key=KEY,name='Test')]),patch.object(sutradhar_scanner,'load_stock_candles',AsyncMock(side_effect=load)) as loader:
            chart=asyncio.run(sutradhar_scanner.stock_chart(KEY))
        self.assertEqual(loader.await_count,2)
        self.assertEqual(chart['sutradhar']['points'][-1],expected)
        self.assertEqual(chart['strategies'][0]['bias'],'neutral')

    def test_endpoint_validates_json_and_boolean_settings(self):
        import main
        client=TestClient(main.app)
        with patch.object(sutradhar_scanner,'stock_chart',AsyncMock(return_value={'ok':True})) as load:
            params=dict(instrument_key=KEY,sutradhar_settings=json.dumps(dict(use_ema=True,p1=10)))
            self.assertEqual(client.get('/api/stocks/sutradhar',params=params).status_code,200)
            load.assert_awaited_once_with(KEY,'15m',dict(use_ema=True,p1=10))
            for value in ('[]','null','not-json','{"use_ema":1}','{"p1":0}'):
                params['sutradhar_settings']=value
                self.assertEqual(client.get('/api/stocks/sutradhar',params=params).status_code,400)


class SutradharOptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_accepts_boolean_ema_and_invalidates_on_daily_revision(self):
        from scanner.strategies import registry as registry_module
        rows,daily=fixture();registry=registry_module.StrategyRegistry()
        async def load(timeframe,**kwargs):return pl.DataFrame(daily if timeframe=='1d' else rows)
        with patch.object(registry_module,'get_candle_revision',AsyncMock(return_value=1)) as revision,patch.object(registry_module,'get_cached_strategy_result',AsyncMock(return_value=None)),patch.object(registry_module,'get_all_active_instruments',AsyncMock(return_value=[dict(key=KEY,symbol='TEST',exchange='NSE')])),patch.object(registry_module,'load_recent_candles_polars',AsyncMock(side_effect=load)),patch.object(registry_module,'save_strategy_result_cache',AsyncMock()) as save:
            response=await registry.execute_scan('sutradhar',timeframe='15m',params={'use_ema':True})
            self.assertEqual(response['total_matched'],1)
            self.assertIn('daily-v1',save.call_args.kwargs['cache_key'])
            self.assertEqual(save.call_args.kwargs['params']['use_ema'],True)
            self.assertIn(('1d',),[c.args for c in revision.call_args_list])
            with self.assertRaisesRegex(ValueError,'boolean'):
                await registry.execute_scan('sutradhar',timeframe='15m',params={'use_ema':1})
            with self.assertRaisesRegex(ValueError,'Intraday'):
                await registry.execute_scan('sutradhar',timeframe='1d')

    async def test_daily_provider_history_only_loaded_when_selected_and_settings_partition_results(self):
        rows,daily=fixture();contract=dict(instrument_key='NSE_FO|123',trading_symbol='TEST CE')
        async def history(request,token,key,interval):
            return dict(candles=daily if interval==1440 else rows,formingCandles=[],invalidCandles=0)
        with patch.object(option_market,'cache',option_market.SharedCache()),patch.object(option_analysis,'resolve_contract',AsyncMock(return_value=contract)),patch.object(option_analysis,'history',AsyncMock(side_effect=history)) as loader:
            args=(AsyncMock(),'token',KEY,datetime(2027,1,1).date(),100,'CE',5)
            default=await option_analysis.analyze(*args)
            self.assertIsNone(default['sutradhar'])
            self.assertFalse(any(call.args[-1]==1440 for call in loader.call_args_list))
            sma=await option_analysis.analyze(*args,sutradhar_settings={})
            ema=await option_analysis.analyze(*args,sutradhar_settings=dict(use_ema=True))
            again=await option_analysis.analyze(*args,sutradhar_settings={})
            self.assertEqual(sma,again)
            self.assertNotEqual(sma['sutradhar']['points'][-1]['Flow'],ema['sutradhar']['points'][-1]['Flow'])
            self.assertEqual(sum(call.args[-1]==1440 for call in loader.call_args_list),2)
            self.assertEqual(sma['sutradhar']['status'],'LEVELS_READY')

    async def test_daily_source_failure_is_partial_and_weekly_is_explicitly_unsupported(self):
        rows,_=fixture();contract=dict(instrument_key='NSE_FO|123')
        async def history(request,token,key,interval):
            if interval==1440:
                from fastapi import HTTPException
                raise HTTPException(502,'Daily data missing')
            return dict(candles=rows,formingCandles=[],invalidCandles=0)
        with patch.object(option_market,'cache',option_market.SharedCache()),patch.object(option_analysis,'resolve_contract',AsyncMock(return_value=contract)),patch.object(option_analysis,'history',AsyncMock(side_effect=history)):
            args=(AsyncMock(),'token',KEY,datetime(2027,1,1).date(),100,'CE')
            partial=await option_analysis.analyze(*args,5,sutradhar_settings={})
            weekly=await option_analysis.analyze(*args,10080,sutradhar_settings={})
        self.assertEqual(partial['sutradhar']['status'],'INSUFFICIENT_HISTORY')
        self.assertTrue(partial['ghostRider']['points'])
        self.assertEqual(weekly['sutradhar']['status'],'UNSUPPORTED_TIMEFRAME')
