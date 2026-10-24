"""Supplied Pine semantics, distinct from the archived price-pivot event study."""
import asyncio
import math
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch,AsyncMock
import polars as pl
from fastapi.testclient import TestClient
from services.rsi_overlay import RsiConfig,pine_rsi,pivot_events,calculate,smoothing
from scanner.strategies.rsi_divergence import RsiDivergenceStrategy


def fixture(gap=10,bull=True):
    size=gap+16;start=datetime(2025,1,1,tzinfo=timezone.utc)
    rows=[dict(instrument_key='NSE_EQ|TEST',timestamp=start+timedelta(minutes=5*i),open=100.,high=105.,low=95.,close=100.,volume=100+i) for i in range(size)]
    values=[50.]*size
    a,b=10,10+gap;values[a],values[b]=(20.,30.) if bull else (80.,70.)
    field='low' if bull else 'high';rows[a][field],rows[b][field]=(90.,85.) if bull else (110.,115.)
    return rows,values


class PineRsiTests(unittest.TestCase):
    def test_wilder_seed_and_flat_branch_order(self):
        prices=[44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28]
        actual=pine_rsi(prices,14)
        self.assertTrue(all(x is None for x in actual[:14]))
        self.assertAlmostEqual(actual[14],70.464135,places=5)
        self.assertEqual(pine_rsi([1.]*20,14)[-1],100)
        self.assertEqual(pine_rsi(list(range(20,0,-1)),14)[-1],0)
        self.assertEqual(pine_rsi([2,3,2],1),[None,100.,0.])

    def test_pivots_are_rsi_pivots_with_five_bar_confirmation_and_no_future_leak(self):
        for bull in (True,False):
            rows,values=fixture(bull=bull)
            event=pivot_events(rows,values)[0]
            self.assertEqual(event['detectedIndex'],25)
            self.assertEqual(event['pivot2Index'],20)
            self.assertEqual(event['direction'],'BULLISH' if bull else 'BEARISH')
            self.assertEqual(pivot_events(rows[:25],values[:25]),[])
            # Prices on neighbouring bars may exceed the pivot price: Pine pivots RSI.
            rows[19]['low' if bull else 'high']=80 if bull else 120
            self.assertEqual(pivot_events(rows,values),[event])
            self.assertEqual(pivot_events(rows,values),pivot_events(rows+rows[-1:],values+[50]))

    def test_shifted_barssince_range_is_separation_minus_one(self):
        for gap,expected in [(5,0),(6,1),(60,1),(61,1),(62,0)]:
            rows,values=fixture(gap)
            self.assertEqual(len(pivot_events(rows,values)),expected,gap)

    def test_regular_only_and_equal_rsi_is_not_divergence(self):
        rows,values=fixture();values[20]=20
        self.assertEqual(pivot_events(rows,values),[])
        values[20]=10;rows[20]['low']=92 # hidden bullish must not be emitted
        self.assertEqual(pivot_events(rows,values),[])

    def test_plateau_uses_rightmost_equal_extremum(self):
        rows,values=fixture();values[21]=values[20];rows[21]['low']=84
        events=pivot_events(rows+[dict(rows[-1],timestamp=rows[-1]['timestamp']+timedelta(minutes=5))],values+[50])
        self.assertEqual(events[0]['pivot2Index'],21)
        self.assertEqual(events[0]['detectedIndex'],26)

    def test_smoothing_and_population_bollinger_bands(self):
        values=[None,10.,20.,30.];volumes=[0,1,2,3]
        for kind,last in [('SMA',25),('SMA + Bollinger Bands',25),('EMA',25.5555555556),('SMMA (RMA)',22.5),('WMA',80/3),('VWMA',26)]:
            c=RsiConfig(ma_type=kind,ma_length=2)
            self.assertAlmostEqual(smoothing(values,volumes,c)[-1],last,places=7)
        rows,_=fixture()
        with patch('services.rsi_overlay.pine_rsi',return_value=[float(i) for i in range(len(rows))]):
            data=calculate(rows,dict(ma_type='SMA + Bollinger Bands',ma_length=2))
        self.assertEqual(data['points'][-1]['bbUpper']-data['points'][-1]['ma'],1)
        self.assertTrue(all(x is None for x in smoothing(values,volumes,RsiConfig(ma_type='None'))))

    def test_source_and_divergence_switch(self):
        rows,_=fixture()
        rows[-1]['high']=120
        close=calculate(rows);hl2=calculate(rows,dict(source='hl2',calculate_divergence=False))
        self.assertNotEqual(close['points'][-1]['rsi'],hl2['points'][-1]['rsi'])
        self.assertEqual(hl2['events'],[])
        for params in [dict(period=True),dict(period=0),dict(ma_length=1.5),dict(bb_mult=math.nan),dict(source='invalid'),dict(calculate_divergence=1),dict(timeframe=10)]:
            with self.assertRaises(ValueError): RsiConfig.resolve(params)

    def test_scanner_uses_same_events_without_breakout_or_250_bar_gate(self):
        rows,values=fixture()
        with patch('services.rsi_overlay.pine_rsi',return_value=values):
            expected=calculate(rows)['events'][-1]
            actual=RsiDivergenceStrategy().run(pl.DataFrame(rows),{'NSE_EQ|TEST':dict(symbol='TEST')},{'_timeframe':'5m'})
        self.assertEqual(len(actual),1)
        for k,v in expected.items(): self.assertEqual(actual[0][k],v)
        self.assertEqual(actual[0]['state'],'DETECTED')
        self.assertNotIn('triggerPrice',actual[0])

    def test_stock_chart_uses_targeted_stored_history_and_settings(self):
        from services import rsi_scanner
        rows,_=fixture()
        with patch.object(rsi_scanner,'require_fno_key'),patch.object(rsi_scanner,'get_fno_stocks',return_value=[dict(key='NSE_EQ|TEST',name='Test')]),patch.object(rsi_scanner,'load_stock_candles',AsyncMock(return_value=pl.DataFrame(rows))) as loader:
            result=asyncio.run(rsi_scanner.stock_chart('NSE_EQ|TEST','5m',dict(period=7,ma_type='EMA')))
        self.assertEqual(loader.await_count,1)
        self.assertEqual(result['rsiDivergence']['settings']['period'],7)
        self.assertEqual(result['strategies'][0]['id'],'rsi_divergence')

    def test_rsi_api_settings_are_validated_and_forwarded(self):
        import json
        import main
        client=TestClient(main.app)
        with patch('services.rsi_scanner.stock_chart',AsyncMock(return_value={'ok':True})) as load:
            params=dict(instrument_key='NSE_EQ|TEST',timeframe='5m',rsi_settings=json.dumps(dict(period=7,ma_type='VWMA')))
            self.assertEqual(client.get('/api/stocks/rsi-divergence',params=params).status_code,200)
            load.assert_awaited_once_with('NSE_EQ|TEST','5m',dict(period=7,ma_type='VWMA'))
            for value in ('not-json','[]','{"period":true}','{"bb_mult":100}'):
                params['rsi_settings']=value
                self.assertEqual(client.get('/api/stocks/rsi-divergence',params=params).status_code,400)
            self.assertEqual(load.await_count,1)

    def test_option_results_cache_isolated_by_rsi_inputs_but_uses_same_history(self):
        from services import option_analysis,option_market
        rows,_=fixture()
        async def run():
            contract=dict(instrument_key='NSE_FO|123',trading_symbol='TEST CE')
            async def history(*args):return dict(candles=rows,formingCandles=[],invalidCandles=0)
            with patch.object(option_market,'cache',option_market.SharedCache()),patch.object(option_analysis,'resolve_contract',AsyncMock(return_value=contract)),patch.object(option_analysis,'history',AsyncMock(side_effect=history)):
                args=(AsyncMock(),'token','NSE_EQ|TEST',datetime(2027,1,1).date(),100,'CE',5)
                a=await option_analysis.analyze(*args,rsi_settings=dict(period=7))
                b=await option_analysis.analyze(*args,rsi_settings=dict(period=14))
                again=await option_analysis.analyze(*args,rsi_settings=dict(period=7))
            self.assertEqual(a['rsiDivergence']['settings']['period'],7)
            self.assertEqual(b['rsiDivergence']['settings']['period'],14)
            self.assertEqual(a,again)
        asyncio.run(run())

