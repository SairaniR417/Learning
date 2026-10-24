import unittest
from datetime import datetime, timedelta, timezone

from services.ghost_rider_overlay import calculate, rsi, rma, adx14


def rows(closes, step=5, start=None):
    start = start or datetime(2026, 10, 20, 3, 45, tzinfo=timezone.utc)
    return [dict(timestamp=start+timedelta(minutes=step*i),open=c-.1,high=c+1,low=c-1,close=c,volume=100)
            for i,c in enumerate(closes)]


class PineOverlayTests(unittest.TestCase):
    def test_signal_close_levels_and_hit_detection_include_signal_bar(self):
        data=rows([100.]*20+[102.])
        result=calculate(data,data)
        self.assertEqual(result['setup']['signal'],'BUY')
        self.assertEqual(result['signals'][-1]['timestamp'],data[-1]['timestamp'].isoformat())
        self.assertEqual(result['points'][-1]['barColor'],'#363a45')
        self.assertEqual(result['setup']['entry'],102)
        # ATR seed 2; this bar TR=3, so Wilder ATR=(13*2+3)/14.
        risk=(13*2+3)/14*1.5
        self.assertAlmostEqual(result['setup']['stopLoss'],102-risk)
        for n,target in enumerate(result['setup']['targets'],1):
            self.assertAlmostEqual(target['price'],102+n*risk)
        wide=rows([100.]*20+[102.])
        wide[-1]['high']=500
        overlay=calculate(wide,wide)
        self.assertTrue(overlay['setup']['targets'][0]['hit'])
        self.assertEqual(overlay['levels'][2]['color'],'#40e0d0')
        self.assertEqual(overlay['levels'][2]['icon'],'🎯')

    def test_opposite_cross_resets_hits_negative_targets_are_retained(self):
        data=rows([100.]*20+[110.,120.,1.])
        data[-1]['low']=.1
        overlay=calculate(data,data)
        self.assertEqual(overlay['setup']['signal'],'SELL')
        self.assertLess(overlay['setup']['targets'][-1]['price'],0)
        self.assertEqual([l['label'] for l in overlay['levels']],['ENTRY','SL','TP1','TP2','TP3','TP4','TP5'])
        self.assertEqual([l['width'] for l in overlay['levels']],[2,2,1,1,1,2,3])
        self.assertFalse(any(t['hit'] for t in overlay['setup']['targets']))

    def test_stop_touch_does_not_cancel_setup_and_targets_remain_latched(self):
        data=rows([100.]*20+[110.,130.,125.])
        data[-1]['low']=1
        overlay=calculate(data,data)
        self.assertEqual(overlay['setup']['signal'],'BUY')
        self.assertEqual(overlay['setup']['entry'],110)
        self.assertTrue(overlay['setup']['targets'][-1]['hit'])
        self.assertEqual(next(r['value'] for r in overlay['dashboard'] if r['title']=='Status'),'WAIT')

    def test_retest_candle_is_orange_without_new_entry(self):
        data=rows([100.]*20+[110.,111.,112.])
        original=calculate(data,data)
        point=original['points'][-1]
        data[-1]['low']=(point['ema9']+point['ema21'])/2
        result=calculate(data,data)
        self.assertEqual(result['points'][-1]['barColor'],'#ff9800')
        self.assertEqual(result['signals'],original['signals'])

    def test_session_vwap_resets_and_uses_hlc3_volume(self):
        data=rows([100.,110.])
        data[0].update(high=104,low=99,volume=2)
        data[1].update(high=112,low=108,volume=1)
        data.append(dict(data[-1],timestamp=data[-1]['timestamp']+timedelta(days=1),close=50,high=52,low=48,open=50,volume=5))
        result=calculate(data,data)
        self.assertAlmostEqual(result['points'][1]['vwap'],((104+99+100)/3*2+110)/3)
        self.assertEqual(result['points'][2]['vwap'],50)

    def test_five_minute_rsi_is_last_closed_intrabar_not_future_value(self):
        five=rows([100+i%7 for i in range(60)])
        fifteen=[dict(five[i],timestamp=five[i]['timestamp']) for i in range(0,60,3)]
        result=calculate(fifteen,five,15)
        expected=rsi([r['close'] for r in five])[-1]
        actual=next(r['value'] for r in result['dashboard'] if r['title']=='5m RSI')
        self.assertAlmostEqual(float(actual),expected,delta=.051)
        future=rows([1.,500.],start=five[-1]['timestamp']+timedelta(minutes=5))
        self.assertEqual(calculate(fifteen,five+future,15)['dashboard'],result['dashboard'])

    def test_score_is_seven_votes_and_does_not_gate_crossover(self):
        data=rows([100+i for i in range(100)])
        data[-1]['volume']=1000
        result=calculate(data,data)
        table={r['title']:r['value'] for r in result['dashboard']}
        self.assertEqual(table['Pullers'],'100%')
        self.assertEqual(table['Draggers'],'0%')
        self.assertEqual(table['BIAS'],'STRONG BULL')
        self.assertEqual(table['Ghostrider'],'Bullet')
        self.assertEqual(len(result['dashboard']),16)
        missing=calculate(data,[])
        self.assertEqual(next(r['value'] for r in missing['dashboard'] if r['title']=='Pullers'),'86%')
        self.assertEqual(next(r['value'] for r in missing['dashboard'] if r['title']=='5m RSI'),'n/a')
        self.assertEqual(missing['signals'],result['signals'])

    def test_wilder_seed_and_multiplier_dont_change_signals(self):
        self.assertEqual(rma([None]+[2.]*15,14)[13:],[None,2.,2.])
        self.assertIsNone(rsi(list(range(20)))[13])
        self.assertEqual(rsi(list(range(20)))[14],100)
        data=rows([100+i for i in range(40)])
        self.assertIsNone(adx14(data)[26])
        self.assertAlmostEqual(adx14(data)[27],100)
        a,b=calculate(data,data,multiplier=1.5),calculate(data,data,multiplier=3)
        self.assertEqual(a['signals'],b['signals'])
        self.assertEqual(a['points'],b['points'])

    def test_empty_history_and_atr_warmup_do_not_invent_levels(self):
        self.assertEqual(calculate([],[])['levels'],[])
        data=rows([100.,101.])
        result=calculate(data,data)
        self.assertEqual(result['setup']['signal'],'BUY')
        self.assertIsNone(result['setup']['stopLoss'])
        self.assertEqual([l['label'] for l in result['levels']],['ENTRY'])
