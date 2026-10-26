import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock,patch
import polars as pl
from services import focused_plans as f,focused_options as o

NOW=datetime(2026,10,26,11,1,tzinfo=f.INDIA)
KEY='NSE_EQ|INE002A01018'


def rows(count=100,price=100,interval=15):
    last=NOW.replace(hour=10,minute=45,second=0)
    return [dict(timestamp=last-timedelta(minutes=interval*(count-1-i)),instrument_key=KEY,open=price,high=price+1,low=price-1,close=float(price),volume=1000000) for i in range(count)]


def daily():
    return [dict(r,timestamp=NOW.replace(hour=0,minute=0)-timedelta(days=201-i)) for i,r in enumerate(rows(200))]


def computed(direction='BUY'):
    checks=[dict(id=k,name=v,direction=direction if k in ('ghost_rider','suryavanshi','golden_death_cross') else None,state='ACTIVE',reason='test',asOf=NOW.isoformat()) for k,v in f.NAMES.items()]
    stop=99 if direction=='BUY' else 101
    drivers={'suryavanshi':dict(direction=direction,entry=100,stop=stop,index=99)}
    levels=dict(O=99 if direction=='BUY' else 101,Flow=104,Crest=106,Crown=108,Value=96,Base=94,Origin=92)
    return checks,drivers,levels


def plan(direction='BUY',mode='intraday',now=NOW):
    return f.build_plan(rows(),daily(),[],dict(key=KEY,symbol='RELIANCE'),mode,now,computed(direction))


class DecisionTests(unittest.TestCase):
    def test_aligned_plan_levels_and_five_checks(self):
        r=plan();self.assertEqual(r['action'],'BUY');self.assertEqual(len(r['evidence']),5)
        p=r['plan'];self.assertEqual((p['entry'],p['stopLoss'],p['target1'],p['target2']),(100,99,102,103))
        self.assertEqual(p['rewardRisk'],2);self.assertIn('15:20',r['holding'])
        self.assertIn('Source stop from Suryavanshi',p['basis'])

    def test_bearish_intraday_is_ordered_but_swing_short_waits(self):
        r=plan('SELL');p=r['plan'];self.assertEqual(r['action'],'SELL')
        self.assertTrue(p['target2']<p['target1']<p['entry']<p['stopLoss'])
        r=plan('SELL','swing');self.assertEqual(r['action'],'WAIT');self.assertTrue(r['qualified'])
        self.assertTrue(any('cash short' in s for s in r['waitReasons']))

    def test_conflicts_and_missing_sutradhar_never_buy(self):
        c,d,l=computed();c[1]['direction']='SELL'
        r=f.build_plan(rows(),daily(),[],dict(key=KEY,symbol='TEST'),'intraday',NOW,(c,d,l))
        self.assertEqual(r['action'],'WAIT');self.assertFalse(r['qualified'])
        r=f.build_plan(rows(),daily(),[],dict(key=KEY,symbol='TEST'),'intraday',NOW,(*computed()[:2],None))
        self.assertEqual(r['action'],'WAIT');self.assertTrue(any('Sutradhar' in x for x in r['blockers']))

    def test_stale_and_closed_market_gate_cached_results(self):
        r=plan()
        self.assertEqual(f.gate(r,NOW+timedelta(hours=1))['action'],'WAIT')
        self.assertEqual(f.gate(r,NOW+timedelta(days=5))['action'],'WAIT')
        self.assertEqual(f.gate(r,NOW.replace(hour=15,minute=5))['action'],'WAIT')
        self.assertEqual(f.gate(r,NOW.replace(hour=8))['action'],'WAIT')

    def test_near_barrier_bad_stop_and_chasing_are_waits(self):
        for variant in ('barrier','stop','chase'):
            c,d,l=computed()
            if variant=='barrier': l['Flow']=100.5
            elif variant=='stop': d['suryavanshi']['stop']=105
            else: d['suryavanshi']['entry']=95
            r=f.build_plan(rows(),daily(),[],dict(key=KEY,symbol='TEST'),'intraday',NOW,(c,d,l))
            self.assertEqual(r['action'],'WAIT',variant)

    def test_daily_context_staleness_and_insufficient_history(self):
        old=[dict(r,timestamp=r['timestamp']-timedelta(days=30)) for r in daily()]
        r=f.build_plan(rows(),old,[],dict(key=KEY,symbol='TEST'),'intraday',NOW,computed())
        self.assertEqual(r['action'],'WAIT');self.assertIn('Daily trend',r['blockers'][0])
        response=f.analyze_snapshot(pl.DataFrame(rows(10)),pl.DataFrame(daily()),pl.DataFrame(),{KEY:dict(symbol='TEST')},'intraday',now=NOW)
        self.assertEqual(response['plans'],[]);self.assertEqual(response['coverage']['executionHistory'],1)

    def test_real_engines_have_five_checks_and_no_forced_trade(self):
        checks,drivers,levels=f.evidence(rows(),daily(),[],15,NOW)
        self.assertEqual({x['id'] for x in checks},set(f.NAMES))
        result=f.build_plan(rows(),daily(),[],dict(key=KEY,symbol='TEST'),'intraday',NOW)
        self.assertEqual(result['action'],'WAIT')
        self.assertIsNone(result['plan'])


class SourceSignalTests(unittest.TestCase):
    def test_selected_timeframe_controls_engine_and_expiry(self):
        for frame,minutes in f.TIMEFRAMES.items():
            with self.subTest(frame=frame),patch.object(f,'evidence',return_value=computed()) as calculate:
                result=f.build_plan(rows(),daily(),[],dict(key=KEY,symbol='TEST'),'intraday',NOW,timeframe=frame)
                self.assertEqual(result['timeframe'],frame)
                self.assertEqual(calculate.call_args.args[3],minutes)
                self.assertEqual(f.utc(result['validUntil'])-f.utc(result['asOf']),timedelta(minutes=minutes*2,seconds=5))

    def test_one_minute_completion_keeps_developing_bar_out(self):
        source=[dict(rows(1)[0],timestamp=NOW-timedelta(seconds=65)),dict(rows(1)[0],timestamp=NOW-timedelta(seconds=30))]
        self.assertEqual(len(f.completed_rows(source,'1m',NOW)),1)

    def test_daily_snapshot_uses_completed_daily_candles(self):
        response=f.analyze_snapshot(pl.DataFrame(daily()),pl.DataFrame(daily()),pl.DataFrame(),{KEY:dict(symbol='TEST')},'swing',now=NOW,timeframe='1d')
        self.assertEqual(response['timeframe'],'1d')
        self.assertEqual(response['plans'][0]['timeframe'],'1d')
        self.assertEqual(response['plans'][0]['action'],'WAIT')

    def test_source_levels_survive_a_blocked_combined_plan(self):
        setup=dict(signal='BUY',signalAt=NOW.isoformat(),index=99,entry=100,stopLoss=90,
                   targets=[dict(price=110,hit=False)])
        trade=dict(direction='short',timestamp=NOW.isoformat(),index=99,entry=103,sl=108,tp=97,state='TARGET')
        with patch.object(f,'ghost_calculate',return_value={'setup':setup}), \
             patch.object(f.suryavanshi,'calculate',return_value={'activeTrade':None,'trades':[trade]}):
            checks,drivers,levels=f.evidence(rows(),daily(),[],15,NOW)
        by_id={c['id']:c for c in checks}
        self.assertEqual(by_id['ghost_rider']['entry'],100)
        self.assertEqual(by_id['ghost_rider']['stopLoss'],90)
        self.assertEqual(by_id['ghost_rider']['targets'],[110])
        self.assertEqual(by_id['suryavanshi']['signal'],'SELL')
        self.assertEqual(by_id['suryavanshi']['signalState'],'TARGET')
        self.assertIsNone(by_id['suryavanshi']['direction'])
        result=f.build_plan(rows(),daily(),[],dict(key=KEY,symbol='TEST'),'intraday',NOW,(checks,drivers,levels))
        self.assertEqual(result['action'],'WAIT')
        self.assertEqual(result['evidence'][0]['signal'],'BUY')

    def test_daily_trend_does_not_invent_an_execution_cross(self):
        trend=dict(points=[dict(sma50=110,sma200=100,timestamp=NOW.isoformat())])
        no_cross=dict(latestCross=None)
        with patch.object(f.golden_cross,'calculate',side_effect=[trend,no_cross]):
            checks,_,_=f.evidence(rows(),daily(),[],15,NOW)
        cross=next(c for c in checks if c['id']=='golden_death_cross')
        self.assertEqual(cross['direction'],'BUY')
        self.assertNotIn('signal',cross)

    def test_execution_cross_has_its_own_direction_and_no_invented_levels(self):
        trend=dict(points=[dict(sma50=110,sma200=100,timestamp=NOW.isoformat())])
        execution=dict(latestCross=dict(direction='SELL',timestamp=NOW.isoformat(),kind='DEATH_CROSS'),
                       barsSinceCross=2,confirmationTime=None,state='CROSS_ACTIVE',signal='SELL')
        with patch.object(f.golden_cross,'calculate',side_effect=[trend,execution]):
            checks,_,_=f.evidence(rows(),daily(),[],15,NOW)
        cross=next(c for c in checks if c['id']=='golden_death_cross')
        self.assertEqual((cross['direction'],cross['signal'],cross['signalState']),('BUY','SELL','CROSS_ACTIVE'))
        self.assertEqual(cross['timeframe'],'15m')
        self.assertNotIn('entry',cross)

    def test_bse_style_eight_bar_ghost_buy_is_not_hidden_by_fresh_entry_window(self):
        setup=dict(signal='BUY',signalAt='2026-10-12T00:00:00+05:30',index=91,entry=3330.2,
                   stopLoss=3169.44,targets=[dict(price=3490.96,hit=False)])
        trend=dict(points=[dict(sma50=90,sma200=100,timestamp=NOW.isoformat())])
        execution=dict(latestCross=dict(direction='SELL',timestamp='2026-10-14T00:00:00+05:30',kind='DEATH_CROSS'),
                       barsSinceCross=6,confirmationTime=None,state='CROSS_ACTIVE',signal='SELL')
        with patch.object(f,'ghost_calculate',return_value={'setup':setup}), \
             patch.object(f.golden_cross,'calculate',side_effect=[trend,execution]):
            checks,drivers,_=f.evidence(rows(),daily(),[],1440,NOW)
        by_id={c['id']:c for c in checks}
        self.assertEqual(by_id['ghost_rider']['signal'],'BUY')
        self.assertEqual(by_id['ghost_rider']['signalState'],'CURRENT_SETUP')
        self.assertEqual(by_id['ghost_rider']['ageBars'],8)
        self.assertFalse(by_id['ghost_rider']['entryEligible'])
        self.assertIsNone(by_id['ghost_rider']['direction'])
        self.assertNotIn('ghost_rider',drivers)
        self.assertEqual(by_id['golden_death_cross']['signal'],'SELL')

    def test_unconfirmed_cross_does_not_invent_a_sell_signal(self):
        trend=dict(points=[])
        execution=dict(latestCross=dict(direction='SELL',timestamp=NOW.isoformat(),kind='DEATH_CROSS'),
                       barsSinceCross=2,confirmationTime=None,state='WATCH',signal=None)
        with patch.object(f.golden_cross,'calculate',side_effect=[trend,execution]):
            checks,_,_=f.evidence(rows(),daily(),[],15,NOW)
        cross=next(c for c in checks if c['id']=='golden_death_cross')
        self.assertIsNone(cross['signal'])
        self.assertEqual(cross['signalState'],'WATCH')


class QuoteTests(unittest.TestCase):
    def quote(self):
        return dict(timestamp=str(NOW.timestamp()*1000),last_trade_time=str(NOW.timestamp()*1000),depth={'buy':[dict(price=9.9,quantity=500)],'sell':[dict(price=10,quantity=500)]},volume=1000,oi=1000)

    def test_valid_quote_stale_quote_spread_and_missing_depth(self):
        q,error=o.liquid_quote(self.quote(),100,NOW);self.assertIsNone(error);self.assertEqual(q['ask'],10)
        for variant in ('stale','spread','depth','quantity'):
            q=self.quote()
            if variant=='stale': q['last_trade_time']=str((NOW-timedelta(minutes=5)).timestamp()*1000)
            elif variant=='spread': q['depth']['sell'][0]['price']=15
            elif variant=='quantity': q['depth']['buy'][0]['quantity']=0
            else: q.pop('depth')
            self.assertIsNotNone(o.liquid_quote(q,100,NOW)[1],variant)


class OptionPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_option_check_passes_selected_frame_to_underlying_plan(self):
        async def chart(key,frame):
            return dict(candles=[dict(r,timestamp=r['timestamp'].isoformat()) for r in (daily() if frame=='1d' else rows(100,interval=1))])
        with patch.object(o.stock_chart,'stock_chart',AsyncMock(side_effect=chart)) as history, \
             patch.object(o.plans,'build_plan',return_value=dict(qualified=False,blockers=['test'])) as build:
            result=await o.option_plan(KEY,'intraday',AsyncMock(),'token',NOW,timeframe='1m')
        self.assertEqual(result['action'],'WAIT')
        self.assertEqual(build.call_args.kwargs['timeframe'],'1m')
        self.assertIn('1m',[call.args[1] for call in history.call_args_list])

    async def test_closed_market_never_fetches_contracts(self):
        with patch.object(o.option_market,'expiries',AsyncMock()) as fetch:
            result=await o.option_plan(KEY,'intraday',AsyncMock(),'token',NOW+timedelta(days=5))
        self.assertEqual(result['action'],'WAIT');fetch.assert_not_awaited()

    async def test_actual_contract_premium_levels_are_independent_from_stock(self):
        expiry=(NOW.date()+timedelta(days=20)).isoformat();contract='NSE_FO|123'
        parent=plan();premium=dict(parent,direction='BUY',action='BUY',symbol='RELIANCE CE',plan=dict(parent['plan'],entry=10,entryMin=9.9,entryMax=10.1,stopLoss=9,target1=12,target2=13))
        quote=QuoteTests().quote();quote['instrument_token']=contract
        async def chart(key,frame): return dict(candles=[dict(r,timestamp=r['timestamp'].isoformat()) for r in (daily() if frame=='1d' else rows())])
        chain=dict(spot=100,rows=[dict(strike=100,call=dict(bid_price=9.9,ask_price=10,volume=1000,oi=1000))])
        with patch.object(o.stock_chart,'stock_chart',AsyncMock(side_effect=chart)), \
             patch.object(o.plans,'build_plan',side_effect=[parent,premium]), \
             patch.object(o.plans,'evidence',return_value=computed()), \
             patch.object(o.option_market,'expiries',AsyncMock(return_value={'expiries':[expiry]})), \
             patch.object(o.option_market,'chain',AsyncMock(return_value=chain)), \
             patch.object(o.option_analysis,'resolve_contract',AsyncMock(return_value=dict(instrument_key=contract,trading_symbol='RELIANCE CE',lot_size=100))), \
             patch.object(o.option_analysis,'history',AsyncMock(return_value=dict(candles=rows(100,10)))), \
             patch.object(o.option_market,'limited_request',AsyncMock(return_value=dict(status='success',data={'x':quote}))):
            result=await o.option_plan(KEY,'intraday',AsyncMock(),'token',NOW)
        self.assertEqual(result['action'],'BUY CE');self.assertEqual(result['plan']['entry'],10)
        self.assertEqual(result['plan']['stopLoss'],9);self.assertEqual(result['contract']['key'],contract)
        self.assertEqual(result['plannedRiskPerLot'],100);self.assertEqual(result['maximumPremiumLossPerLot'],1000)
