import unittest
from unittest.mock import AsyncMock,patch
from datetime import datetime,timedelta,timezone
from services.suryavanshi import Config,calculate
import polars as pl


def rows():
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    data=[dict(timestamp=start+timedelta(minutes=15*i),open=100.,high=101.,low=99.,close=100.,volume=100) for i in range(19)]
    data[14]['high']=110
    data[16]['high']=108
    data[18].update(high=109,close=104)
    return data


class PineSemantics(unittest.TestCase):
    def test_defaults_and_validation(self):
        self.assertEqual(Config.resolve().length,20)
        self.assertEqual(Config.resolve({'rr_ratio':-1}).rr_ratio,-1)
        for values in ({'length':True},{'length':-1},{'rr_ratio':float('nan')},{'candle_type':'Bodies'},{'unknown':1}):
            with self.assertRaises(ValueError): Config.resolve(values)

    def test_first_pivot_ignored_second_changed_pivot_arms(self):
        data=rows()
        result=calculate(data,Config(length=1))
        self.assertEqual([a['index'] for a in result['alerts']],[18])
        self.assertEqual(result['lines'][0]['x1'],16)
        self.assertEqual(result['labels'][0]['text'],'CHoCH')
        self.assertEqual(result['activeTrade']['direction'],'long')

    def test_body_is_close_only_and_pivots_still_wicks(self):
        data=rows()
        self.assertFalse(calculate(data,Config(length=1,candle_type='Body'))['alerts'])
        data[18]['close']=108.5
        self.assertEqual(calculate(data,Config(length=1,candle_type='Body'))['alerts'][0]['index'],18)

    def test_equal_pivot_does_not_rearm(self):
        data=rows();data[16]['high']=110;data[18]['high']=111
        self.assertFalse(calculate(data,Config(length=1))['alerts'])

    def test_entry_bar_checks_both_exits_and_loss_color_wins(self):
        data=rows();data[18].update(high=150,low=50,close=104)
        result=calculate(data,Config(length=1,rr_ratio=.1,sl_type='High/Low'))
        # Stop is below the entry bar low because it includes ATR: a same-bar
        # double hit is instead possible through simultaneous long/short signals.
        self.assertTrue(result['trades'][0]['won'])
        data=rows();data[14]['low']=90;data[16]['low']=92;data[18].update(low=91,close=100)
        result=calculate(data,Config(length=1,sl_type='High/Low'))
        self.assertEqual([a['title'] for a in result['alerts']],['BUY','Sell'])
        self.assertEqual(result['trades'][0]['direction'],'short')
        self.assertEqual(result['trades'][0]['state'],'BOTH')
        self.assertEqual((result['winningTrades'],result['losingTrades']),(1,1))
        self.assertEqual(result['labels'][-1]['state'],'STOP')

    def test_active_trade_consumes_opposite_break_and_does_not_reverse(self):
        data=rows();data[14]['low']=90;data[16]['low']=92
        data.append(dict(data[-1],timestamp=data[-1]['timestamp']+timedelta(minutes=15),high=104,low=91,close=100))
        result=calculate(data,Config(length=1))
        self.assertEqual(len(result['trades']),1)
        self.assertEqual(result['trades'][0]['direction'],'long')
        self.assertFalse(result['points'][-1]['sell'])

    def test_target_and_optional_stop_extend_and_freeze(self):
        data=rows();data.append(dict(data[-1],timestamp=data[-1]['timestamp']+timedelta(minutes=15),high=200,close=105))
        result=calculate(data,Config(length=1,show_sl=True))
        self.assertEqual(result['trades'][0]['endIndex'],19)
        self.assertEqual(result['lines'][-1]['kind'],'stop')
        self.assertEqual(result['lines'][-2]['x2'],19)
        self.assertEqual(result['labels'][-1]['x'],20)
        self.assertIsNone(result['activeTrade'])

    def test_volume_includes_breakout_excludes_pivot_and_doji_total(self):
        data=rows();data[16]['volume']=1000000
        data[17].update(open=99,close=100,volume=60)
        data[18].update(open=104,close=104,volume=40)
        self.assertEqual(calculate(data,Config(length=1))['labels'][0]['sign'],'green')
        data[17]['volume']=55;data[18]['volume']=45
        self.assertEqual(calculate(data,Config(length=1))['labels'][0]['sign'],'yellow')

    def test_atr_warmup_is_not_silently_skipped_and_replay_is_pure(self):
        data=rows()[12:]
        result=calculate(data,Config(length=1))
        self.assertIsNone(result['activeTrade']['tp'])
        self.assertEqual(result,calculate(data,Config(length=1)))
        self.assertEqual(result['winningTrades'],0)

    def test_retained_objects_have_independent_pine_limits(self):
        data=rows()*100
        for i,r in enumerate(data): data[i]=dict(r,timestamp=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(minutes=15*i))
        result=calculate(data,Config(length=1,rr_ratio=-1,show_sl=True))
        self.assertEqual(len(result['lines']),500)
        self.assertLessEqual(len(result['labels']),500)

    def test_scanner_result_uses_same_trade_and_settings(self):
        from scanner.strategies.suryavanshi import SuryavanshiStrategy
        key='NSE_EQ|INE002A01018'
        data=[dict(r,instrument_key=key) for r in rows()]
        overlay=calculate(data,Config(length=1))
        matches=SuryavanshiStrategy().run(pl.DataFrame(data),{key:dict(symbol='RELIANCE')},{'length':1,'_timeframe':'15m'})
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['entry'],overlay['activeTrade']['entry'])
        self.assertEqual(matches[0]['stopLoss'],overlay['activeTrade']['sl'])
        self.assertEqual(matches[0]['tp1'],overlay['activeTrade']['tp'])
        self.assertEqual(matches[0]['status'],'BUY')


class StoredChartTests(unittest.IsolatedAsyncioTestCase):
    async def test_chart_matches_scanner_without_broker_requests(self):
        from services import suryavanshi_scanner as chart
        key='NSE_EQ|INE002A01018'
        data=[dict(r,instrument_key=key) for r in rows()]
        with patch.object(chart,'load_stock_candles',AsyncMock(return_value=pl.DataFrame(data))) as load:
            result=await chart.stock_chart(key,'15m',{'length':1,'show_sl':True})
        load.assert_awaited_once_with(key,'15m')
        self.assertEqual(result['suryavanshi']['inputs']['length'],1)
        self.assertEqual(result['strategies'][0]['status'],'BUY')
        self.assertEqual(result['suryavanshi']['lines'][-1]['kind'],'stop')


if __name__=='__main__': unittest.main()
