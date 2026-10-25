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
