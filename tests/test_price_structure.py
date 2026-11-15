import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from services import price_structure as s

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def bars(values, start=None, volume=100):
    start = start or NOW - timedelta(days=len(values)+1)
    return [dict(timestamp=start+timedelta(days=i), open=v, high=v+1, low=v-1, close=v, volume=volume) for i, v in enumerate(values)]


class StructureTests(unittest.TestCase):
    def test_calendar_windows_and_leap_day(self):
        self.assertEqual(s.months_before(NOW.date().replace(day=30), 9).isoformat(), '2026-02-28')
        self.assertEqual(s.months_before(datetime(2024, 2, 29).date(), 12).isoformat(), '2023-02-28')
        daily = bars([100]*500)
        views = s.build(daily, [], NOW)
        self.assertEqual([v['label'] for v in views], ['12 Months', '3 Months', '1 Month', '1 Week', '1 Day', '1 Hour'])
        for months, view in zip((12, 3, 1), views):
            cutoff = s.months_before(NOW.astimezone(s.INDIA).date(), months)
            expected = sum(r['timestamp'].astimezone(s.INDIA).date() >= cutoff for r in daily)
            self.assertEqual(view['count'], expected)
        self.assertEqual(views[-1]['trend'], 'Unavailable')

    def test_clean_excludes_developing_future_invalid_and_duplicates(self):
        row = bars([100])[0]
        future = dict(row, timestamp=NOW+timedelta(days=1))
        invalid = dict(row, low=200)
        developing = dict(row, timestamp=row['timestamp']+timedelta(days=1), developing=True)
        result, bad, dev = s.clean([row, row, future, invalid, developing], '1d', NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(bad, 2)
        self.assertEqual(dev, 1)

    def test_weekly_ohlcv_and_open_week_excluded(self):
        monday = datetime(2026, 11, 9, 0, tzinfo=s.INDIA)
        rows = bars([100, 110, 90, 105, 108], monday)
        self.assertEqual(s.weekly(rows, monday+timedelta(days=3)), [])
        result = s.weekly(rows, NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]['open'], result[0]['high'], result[0]['low'], result[0]['close'], result[0]['volume']), (100, 111, 89, 108, 500))

    def test_two_sided_pivots_and_higher_structure(self):
        rows = bars([100, 102, 110, 105, 100, 105, 115, 109, 104, 110, 120, 116, 111, 117, 123])
        view = s.analyze(rows, 'Test', '1d', NOW, 'Test')
        self.assertEqual(view['trend'], 'Higher highs / higher lows')
        self.assertTrue(all(p['index'] <= len(rows)-3 for p in view['swings']))
        self.assertTrue(view['trendlines'])
        self.assertTrue(all(z['price'] < view['close'] for z in view['supports']))
        self.assertTrue(all(z['price'] >= view['close'] for z in view['resistances']))

    def test_support_loss_does_not_report_healthy_uptrend(self):
        rows = bars([100, 102, 110, 105, 100, 105, 115, 109, 104, 110, 120, 116, 111, 117, 90])
        view = s.analyze(rows, 'Test', '1d', NOW, 'Test')
        self.assertEqual(view['trend'], 'Rising structure / support lost')

    def test_volume_uses_previous_bars_not_itself(self):
        rows = bars([100]*21)
        rows[-1]['volume'] = 250
        view = s.analyze(rows, 'Test', '1h', NOW, 'Test')
        self.assertEqual(view['volume']['ratio'], 2.5)
        self.assertIn('time-of-day', view['volume']['description'])
        self.assertIsNone(s.analyze(rows[:20], 'Test', '1d', NOW, '')['volume']['ratio'])

    def test_range_extrema_not_claimed_as_confirmed_swings(self):
        view = s.analyze(bars([100, 105]), 'Test', '1d', NOW, '')
        self.assertEqual(view['trend'], 'Insufficient confirmed swings')
        self.assertEqual(view['swings'], [])
        self.assertEqual(view['supports'][0]['origin'], 'Observed range extreme')

    def test_recovery_chronology_and_no_retest_prediction(self):
        view = s.analyze(bars([400, 350, 200, 114, 200, 300, 365]), 'Test', '1d', NOW, '')
        self.assertTrue(any('Fell from' in line and 'subsequent move' in line for line in view['narrative']))
        self.assertTrue(any('watch whether' in line for line in view['watch']))

    def test_empty_history(self):
        view = s.analyze([], 'Test', '1d', NOW, '')
        self.assertIsNone(view['close'])
        self.assertEqual(view['supports'], [])
        self.assertIn('No completed history', view['narrative'][0])

    def test_final_short_hour_closes_at_session_end(self):
        now = datetime(2026, 11, 13, 15, 31, tzinfo=s.INDIA)
        row = dict(timestamp=now.replace(hour=15, minute=15), open=100, high=101, low=99, close=100, volume=100)
        result, _, _ = s.clean([row], '1h', now)
        self.assertEqual(len(result), 1)

    def test_weekly_close_date_is_last_session_not_monday(self):
        monday = datetime(2026, 11, 9, tzinfo=s.INDIA)
        weekly = s.weekly(bars([100]*5, monday), NOW)
        view = s.analyze(weekly, 'Weekly', '1w', NOW, '')
        self.assertEqual(datetime.fromisoformat(view['asOf']).date().isoformat(), '2026-11-13')


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_stock_only_and_partial_history(self):
        key = s.get_fno_stocks()[0]['key']
        async def load(selected, frame):
            self.assertEqual(selected, key)
            if frame == '1h':
                raise s.HTTPException(504, 'Timed out')
            return dict(candles=bars([100]*30), source='Stored history', staleData=True)
        with patch.object(s.stock_chart, 'stock_chart', side_effect=load) as mocked:
            result = await s.structure(key)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(len(result['views']), 6)
        self.assertGreater(result['views'][4]['count'], 0)
        self.assertEqual(result['views'][5]['count'], 0)
        self.assertTrue(any('Timed out' in w for w in result['warnings']))

    async def test_invalid_history_is_not_bridged(self):
        key = s.get_fno_stocks()[0]['key']
        rows = bars([100]*30)
        rows[10]['close'] = float('nan')
        with patch.object(s.stock_chart, 'stock_chart', AsyncMock(return_value=dict(candles=rows))):
            result = await s.structure(key)
        self.assertTrue(all(v['count'] == 0 for v in result['views']))
        self.assertTrue(any('corrupt' in w for w in result['warnings']))

    async def test_outside_universe_rejected_before_load(self):
        with patch.object(s.stock_chart, 'stock_chart', AsyncMock()) as mocked:
            with self.assertRaises(s.HTTPException):
                await s.structure('NSE_INDEX|Nifty 50')
            mocked.assert_not_awaited()
