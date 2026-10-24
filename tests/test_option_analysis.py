import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import main
from services import option_analysis as analysis, option_market as market

KEY = 'NSE_INDEX|Nifty 50'
CONTRACT = 'NSE_FO|123'


def candles(count, key=CONTRACT):
    start = datetime.now(timezone.utc) - timedelta(minutes=15 * (count + 1))
    rows = []
    for n in range(count):
        close = 100 + n * .02 + 5 * math.sin(n / 9)
        rows.append(dict(instrument_key=key, timestamp=start + timedelta(minutes=15 * n),
                         open=close - .1, high=close + 1, low=close - 1, close=close, volume=1000 + n))
    return rows


class CalculationTests(unittest.TestCase):
    def test_weekly_ohlcv_uses_local_monday_and_handles_year_boundary(self):
        rows = []
        for day,o,h,l,c,v in [('2026-12-31',10,14,9,12,100),('2027-01-01',12,16,11,15,200),('2027-01-04',15,18,14,17,300)]:
            rows.append(dict(instrument_key=CONTRACT,timestamp=datetime.fromisoformat(day+'T00:00:00+05:30'),open=o,high=h,low=l,close=c,volume=v))
        weeks=analysis.weekly_candles(list(reversed(rows)))
        self.assertEqual(len(weeks),2)
        self.assertEqual(weeks[0]['timestamp'].astimezone(market.option_chain.INDIA).date().isoformat(),'2026-12-28')
        self.assertEqual([weeks[0][k] for k in ['open','high','low','close','volume']],[10,16,9,15,300])

    def test_daily_exchange_close_and_mcx_date_boundary(self):
        timestamp=datetime.fromisoformat('2026-10-23T00:00:00+05:30')
        before=datetime.fromisoformat('2026-10-23T15:59:00+05:30')
        after=datetime.fromisoformat('2026-10-23T16:01:00+05:30')
        self.assertFalse(analysis.bar_closed(timestamp,CONTRACT,1440,before))
        self.assertTrue(analysis.bar_closed(timestamp,CONTRACT,1440,after))
        self.assertFalse(analysis.bar_closed(timestamp,'MCX_FO|123',1440,after))
        self.assertTrue(analysis.bar_closed(timestamp,'MCX_FO|123',1440,after+timedelta(days=1)))

    def test_only_completed_candles_deduplicated_and_invalid_bars_break_history(self):
        now = datetime(2026, 10, 24, 10, tzinfo=timezone.utc)
        raw = [[(now - timedelta(minutes=m)).isoformat(), 10, 12, 9, close, 100]
               for m, close in [(20, 11), (15, 10), (10, 11), (5, 11), (0, 11)]]
        raw.append([raw[1][0], 10, 12, 9, 11.5, 200])
        result, invalid = analysis.completed_candles(raw, CONTRACT, 5, now)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1]['close'], 11.5)
        self.assertEqual(invalid, 0)
        raw.append([raw[1][0], 0, 0, 0, 0, 0])
        result, invalid = analysis.completed_candles(raw, CONTRACT, 5, now)
        self.assertEqual(len(result), 1)
        self.assertEqual(invalid, 1)

    def test_all_strategies_evaluate_real_intraday_frame(self):
        results = analysis.evaluate(candles(400), {'instrument_key': CONTRACT, 'trading_symbol': 'NIFTY CE', 'exchange': 'NSE'}, 15)
        self.assertEqual(len(results), 7)
        self.assertEqual(next(r for r in results if r['id']=='sutradhar')['status'],'NOT_LOADED')
        self.assertFalse(any(r['status'] in {'UNAVAILABLE', 'INSUFFICIENT_HISTORY'} for r in results), results)
        ghost = next(r for r in results if r['id'] == 'ghost_rider')
        self.assertIn(ghost['status'], {'BUY', 'SELL'})
        self.assertTrue(ghost['levels'])
        self.assertTrue(ghost['signalAt'])

    def test_short_history_is_explicit_and_underlying_context_reverses_for_put(self):
        rows = candles(10)
        results = analysis.evaluate(rows, {'instrument_key': CONTRACT}, 5)
        self.assertTrue(all(r['status'] == 'INSUFFICIENT_HISTORY' for r in results if r['id'] not in {'ghost_rider','sutradhar'}))
        self.assertNotEqual(next(r for r in results if r['id']=='ghost_rider')['status'],'UNAVAILABLE')
        rows = candles(100)
        for n, row in enumerate(rows):
            row['close'] = 100 + n
        self.assertTrue(analysis.underlying_context(rows, 'CE')['supportsPremium'])
        self.assertFalse(analysis.underlying_context(rows, 'PE')['supportsPremium'])


class AnalysisApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_timeframes_use_supported_provider_units(self):
        provider=AsyncMock(return_value={'status':'success','data':{'candles':[]}})
        for interval,unit in [(60,'hours'),(1440,'days'),(10080,'days')]:
            with patch.object(market,'limited_request',provider):
                result=await analysis.history(AsyncMock(),'token',CONTRACT,interval)
            self.assertEqual(result['candles'],[])
            self.assertIn('/'+unit+'/1/',provider.call_args_list[-2].args[1])
            self.assertTrue(provider.call_args_list[-1].args[1].endswith('/'+unit+'/1'))

    async def asyncSetUp(self):
        self.patch = patch.object(market, 'cache', market.SharedCache())
        self.patch.start()
        self.expiry = datetime.now(market.option_chain.INDIA).date() + timedelta(days=10)

    async def asyncTearDown(self):
        self.patch.stop()

    async def test_resolves_exact_tuple_and_rejects_unknown_contract(self):
        provider = AsyncMock(return_value={'status': 'success', 'data': [dict(underlying_key=KEY,
            expiry=self.expiry.isoformat(), strike_price=25000, instrument_type='CE', instrument_key=CONTRACT)]})
        async def passthrough(request, *args, **kwargs):
            return await request(*args, **kwargs)
        with patch.object(market, 'limited_request', side_effect=passthrough):
            contract = await analysis.resolve_contract(provider, 'token', KEY, self.expiry, 25000, 'CE')
            self.assertEqual(contract['instrument_key'], CONTRACT)
            with self.assertRaises(HTTPException) as caught:
                await analysis.resolve_contract(provider, 'token', KEY, self.expiry, 25000, 'PE')
            self.assertEqual(caught.exception.status_code, 400)

    async def test_selected_option_analysis_cached_and_underlying_failure_is_partial(self):
        contract = dict(instrument_key=CONTRACT, name='NIFTY', trading_symbol='NIFTY CE', exchange='NSE')
        async def history(request, token, key, interval):
            if key == KEY:
                raise HTTPException(502, 'Unavailable')
            return {'candles': candles(300), 'invalidCandles': 0}
        with patch.object(analysis, 'resolve_contract', AsyncMock(return_value=contract)), \
             patch.object(analysis, 'history', AsyncMock(side_effect=history)) as loader:
            first = await analysis.analyze(AsyncMock(), 'token', KEY, self.expiry, 25000, 'CE', 5)
            second = await analysis.analyze(AsyncMock(), 'token', KEY, self.expiry, 25000, 'CE', 5)
        self.assertEqual(first, second)
        self.assertEqual(loader.await_count, 2)
        self.assertEqual(first['underlying']['trend'], 'UNAVAILABLE')
        self.assertEqual(len(first['strategies']), 7)
        self.assertEqual(first['contract']['key'], CONTRACT)

    def test_route_validates_timeframe_auth_and_query(self):
        client = TestClient(main.app)
        with patch.object(main, 'require_token', return_value='token'), patch.object(main.option_analysis, 'analyze', AsyncMock(return_value={'ok': True})) as run:
            response = client.get('/api/options/analysis', params={'instrument_key': KEY, 'expiry': str(self.expiry), 'strike': '25000', 'side': 'PE', 'interval': '15'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(run.call_args.args[-2:], (15, 1.5))
        with patch.object(main, 'require_token', side_effect=HTTPException(401, 'Connect Upstox')):
            self.assertEqual(client.get('/api/options/analysis', params={'instrument_key': KEY, 'expiry': str(self.expiry), 'strike': 25000}).status_code, 401)

    async def test_invalid_timeframe_rejected_before_provider_call(self):
        request = AsyncMock()
        with self.assertRaises(HTTPException):
            await analysis.analyze(request, 'token', KEY, self.expiry, 25000, 'CE', 10)
        request.assert_not_called()

    async def test_developing_bar_is_ghost_only_and_risk_has_separate_cache(self):
        contract = dict(instrument_key=CONTRACT, name='NIFTY', trading_symbol='NIFTY CE', exchange='NSE')
        complete = candles(300)
        forming = dict(complete[-1], timestamp=complete[-1]['timestamp']+timedelta(minutes=5), close=150, high=151, low=99, open=100)
        data = {'candles':complete, 'formingCandles':[forming], 'invalidCandles':0}
        with patch.object(analysis,'resolve_contract',AsyncMock(return_value=contract)), patch.object(analysis,'history',AsyncMock(return_value=data)):
            first = await analysis.analyze(AsyncMock(),'token',KEY,self.expiry,25000,'CE',5,1.5)
            second = await analysis.analyze(AsyncMock(),'token',KEY,self.expiry,25000,'CE',5,2)
        self.assertEqual(len(first['candles']),300)
        self.assertEqual(len(first['ghostRider']['candles']),301)
        self.assertTrue(first['ghostRider']['developingBar'])
        self.assertEqual(first['ghostRider']['multiplier'],1.5)
        self.assertEqual(second['ghostRider']['multiplier'],2)
        self.assertEqual(first['ghostRider']['signals'],second['ghostRider']['signals'])
        self.assertEqual(first['ghostRider']['setup']['entry'],second['ghostRider']['setup']['entry'])
