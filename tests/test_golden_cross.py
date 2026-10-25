import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock,patch
import polars as pl
from services.golden_cross import calculate,resolve,scan_row
from scanner.strategies.golden_death_cross import GoldenDeathCrossStrategy


def candles(prices):
    return [dict(instrument_key='NSE_EQ|INE002A01018',timestamp=datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=i),open=p,high=p+1,low=p-1,close=float(p),volume=1000) for i,p in enumerate(prices)]


class GoldenCrossTests(unittest.TestCase):
    def test_classic_default_and_input_validation(self):
        self.assertFalse(resolve()['require_confirmation'])
        for settings in ({'sma_medium':200,'sma_long':200},{'ema_fast':20,'ema_slow':9},{'require_confirmation':'false'},{'sma_long':True},{'volume_multiplier':float('nan')},[]):
            with self.assertRaises(ValueError): resolve(settings)

    def test_first_available_cross_before_old_250_bar_gate(self):
        rows=candles([100]*200+[110])
        o=calculate(rows)
        self.assertEqual(o['state'],'CROSS')
        self.assertEqual(o['events'][0]['index'],200)
        self.assertEqual(o['signal'],'BUY')
        self.assertTrue(o['scanMatch'])
        self.assertFalse(all(o['confirmationChecks'].values()))
        self.assertEqual(calculate(rows,{'require_confirmation':True})['state'],'WATCH')

    def test_death_cross_and_equality(self):
        o=calculate(candles([100]*200+[90]))
        self.assertEqual(o['signal'],'SELL')
        self.assertEqual(o['events'][0]['kind'],'DEATH_CROSS')
        self.assertFalse(calculate(candles([100]*230))['events'])

    def test_history_crosses_and_recent_scan_window(self):
        rows=candles([100]*200+[110]*40+[70]*80)
        o=calculate(rows,{'max_confirmation_bars':0})
        kinds=[e['kind'] for e in o['events']]
        self.assertIn('GOLDEN_CROSS',kinds);self.assertIn('DEATH_CROSS',kinds)
        self.assertFalse(o['scanMatch'])
        self.assertEqual(o,calculate(rows,{'max_confirmation_bars':0}))

    def test_custom_periods_match_manual_smas_and_no_lookahead(self):
        rows=candles([100]*50+[120]*10)
        p={'sma_medium':10,'sma_long':50}
        full=calculate(rows,p)
        self.assertEqual(full['points'][-1]['sma50'],120)
        self.assertEqual(full['points'][-1]['sma200'],104)
        self.assertEqual(full['events'][0]['index'],50)
        self.assertEqual(calculate(rows[:51],p)['events'],full['events'])

    def test_scan_result_matches_chart_and_ignores_forming_daily_bar(self):
        rows=candles([100]*200+[110])
        expected=scan_row(calculate(rows),rows,rows[0]['instrument_key'],{'symbol':'RELIANCE'})
        actual=GoldenDeathCrossStrategy().run(pl.DataFrame(rows),{rows[0]['instrument_key']:{'symbol':'RELIANCE'}},{'_timeframe':'1d'})[0]
        self.assertEqual(actual,expected)
        future=dict(rows[-1],timestamp=datetime.now(timezone.utc)+timedelta(days=1),close=1.,low=1.,high=2.)
        same=GoldenDeathCrossStrategy().run(pl.DataFrame(rows+[future]),{rows[0]['instrument_key']:{'symbol':'RELIANCE'}},{'_timeframe':'1d'})[0]
        self.assertEqual(same,expected)

    def test_insufficient_history_and_confirmation_expiry(self):
        self.assertEqual(calculate(candles([100]*200))['state'],'INSUFFICIENT_HISTORY')
        o=calculate(candles([100]*200+[110]*3),{'require_confirmation':True,'max_confirmation_bars':1})
        self.assertEqual(o['state'],'EXPIRED');self.assertFalse(o['scanMatch'])
        self.assertEqual(o['events'][0]['kind'],'GOLDEN_CROSS')

    def test_optional_confirmation_and_weakened_state(self):
        rows=candles([100]*200+[110+2*i for i in range(20)])
        rows[-1]['volume']=3000
        confirmed=calculate(rows,{'require_confirmation':True})
        self.assertEqual(confirmed['state'],'CONFIRMED')
        self.assertTrue(all(confirmed['confirmationChecks'].values()))
        self.assertEqual(confirmed['events'][-1]['kind'],'CONFIRMATION')
        rows.append(dict(rows[-1],timestamp=rows[-1]['timestamp']+timedelta(days=1),volume=1000))
        weakened=calculate(rows,{'require_confirmation':True})
        self.assertEqual(weakened['state'],'CONFIRMED_WEAKENED')
        self.assertEqual(weakened['confirmationTime'],confirmed['confirmationTime'])


class GoldenChartTests(unittest.IsolatedAsyncioTestCase):
    async def test_targeted_stored_chart_retains_inputs(self):
        from services import golden_cross_scanner as chart
        rows=candles([100]*200+[110])
        with patch.object(chart,'load_stock_candles',AsyncMock(return_value=pl.DataFrame(rows))) as fetch:
            result=await chart.stock_chart(rows[0]['instrument_key'],'1d',{'max_confirmation_bars':5})
        fetch.assert_awaited_once()
        self.assertEqual(result['goldenCross']['events'][0]['kind'],'GOLDEN_CROSS')
        self.assertEqual(result['goldenCross']['inputs']['max_confirmation_bars'],5)
        self.assertEqual(result['strategies'][0]['status'],'CROSS')
