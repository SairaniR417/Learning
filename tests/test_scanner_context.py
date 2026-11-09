"""Session-open arithmetic, executable context gates and opening-range hold boundaries."""
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import polars as pl
from services.market_sync import INDIA
from services.market_session import opening_range, session_context
from services.ghost_assessment import assess
from scanner.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy

START = datetime(2026, 11, 9, 9, 15, tzinfo=INDIA)


def bars(closes):
    return [dict(instrument_key='A', timestamp=START + timedelta(minutes=i * 5),
                 open=100., high=max(100., float(c)) + 1, low=min(100., float(c)) - 1,
                 close=float(c), volume=1000) for i, c in enumerate(closes)]


class OpeningRangeTests(unittest.TestCase):
    def evaluate(self, closes, minutes=15, hold=2):
        rows = bars(closes)
        return opening_range(rows, minutes, hold, rows[-1]['timestamp'] + timedelta(minutes=5, seconds=6))

    def test_bull_and_bear_hold_against_range_extremes(self):
        for tail, direction in (([102, 103], 'BULLISH'), ([98, 97], 'BEARISH')):
            result = self.evaluate([100] * 3 + tail)
            self.assertEqual(result['orbState'], direction)
            self.assertEqual(result['orbHigh'], 101)
            self.assertEqual(result['orbLow'], 99)
            self.assertEqual(result['orbHeldBars'], 2)

    def test_one_close_is_watch_and_return_inside_invalidates(self):
        self.assertEqual(self.evaluate([100, 100, 100, 102])['orbState'], 'WATCH')
        self.assertEqual(self.evaluate([100, 100, 100, 102, 103, 100])['orbState'], 'INSIDE')

    def test_30_and_60_minute_ranges(self):
        for minutes in (30, 60):
            result = self.evaluate([100] * (minutes // 5) + [102, 103], minutes)
            self.assertEqual(result['orbState'], 'BULLISH')
            self.assertEqual(result['orbMinutes'], minutes)

    def test_missing_opening_bar_never_estimates_range(self):
        rows = bars([100, 100, 100, 102, 103]); rows.pop(1)
        result = opening_range(rows, now=START + timedelta(hours=1))
        self.assertEqual(result['orbState'], 'INCOMPLETE')
        self.assertIsNone(result['orbHigh'])

    def test_gap_breaks_the_hold_and_bad_bar_does_not_confirm(self):
        rows = bars([100] * 3 + [102, 103, 104]); rows.pop(-2)
        result = opening_range(rows, now=START + timedelta(hours=1))
        self.assertEqual(result['orbState'], 'WATCH')
        self.assertEqual(result['orbHeldBars'], 1)
        rows[-1]['volume'] = -1
        self.assertNotIn(opening_range(rows, now=START + timedelta(hours=1))['orbState'], ('BULLISH', 'BEARISH'))

    def test_developing_bar_does_not_confirm_and_range_can_be_building(self):
        rows = bars([100, 100, 100, 102, 103])
        result = opening_range(rows, now=rows[-1]['timestamp'] + timedelta(minutes=1))
        self.assertEqual(result['orbState'], 'WATCH')
        self.assertEqual(opening_range(rows, now=START + timedelta(minutes=11))['orbState'], 'BUILDING')

    def test_previous_session_does_not_supply_missing_open(self):
        yesterday = bars([100, 100, 100, 102, 103])
        yesterday = [dict(r, timestamp=r['timestamp'] - timedelta(days=1)) for r in yesterday]
        today = bars([100] * 8)[4:]
        result = opening_range(yesterday + today, now=START + timedelta(hours=1))
        self.assertEqual(result['orbState'], 'INCOMPLETE')
        self.assertEqual(result['sessionDate'], '2026-11-09')
        self.assertIsNone(result['dayOpen'])

    def test_invalid_parameters(self):
        for minutes, hold in ((10, 2), (15, 0), (60, 7), (15, True)):
            with self.assertRaises(ValueError):
                opening_range([], minutes, hold)

    def test_strategy_filters_holds_and_labels_historical_data(self):
        rows = bars([100] * 3 + [102, 103])
        strategy = OpeningRangeBreakoutStrategy()
        with patch('scanner.strategies.opening_range_breakout.datetime') as clock:
            clock.now.return_value = START + timedelta(days=1)
            clock.fromisoformat.side_effect = datetime.fromisoformat
            result = strategy.run(pl.DataFrame(rows), {'A': dict(symbol='AAA')}, {'_timeframe':'5m'})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['decision'], 'HISTORICAL')
        self.assertEqual(result[0]['orbState'], 'BULLISH')
        with self.assertRaises(ValueError):
            strategy.run(pl.DataFrame(rows), {}, {'_timeframe':'1h'})


class AssessmentTests(unittest.TestCase):
    def fixture(self, sell=False):
        rows = bars([100] * 40)
        sign = -1 if sell else 1
        setup = dict(signal='SELL' if sell else 'BUY', index=38, entry=100., stopLoss=100. - sign * 2,
                     risk=2., targets=[dict(number=n, price=100. + sign * n * 2, hit=False) for n in range(1, 6)])
        overlay = dict(setup=setup, fiveMinuteAsOf=rows[-1]['timestamp'].isoformat(),
                       points=[dict(vwap=99., ema9=100., ema21=99.)],
                       dashboardMetrics=dict(bull=0. if sell else 100., bear=100. if sell else 0., adx=30., rsi=40. if sell else 60.,
                                             rsi5=40. if sell else 60., macd=2., macdSignal=1., highVol=True, relativeVolume=1.8, atr=2.))
        now = rows[-1]['timestamp'] + timedelta(minutes=5, seconds=6)
        return rows, overlay, now

    def test_day_open_and_extremes_are_signed_and_midday_is_not_open(self):
        rows = bars([100, 105, 98, 103])
        context = session_context(rows, 5)
        self.assertAlmostEqual(context['fromOpenPct'], 3)
        self.assertAlmostEqual(context['dayHighPct'], 6)
        self.assertAlmostEqual(context['dayLowPct'], -3)
        self.assertIsNone(session_context(rows[2:], 5)['dayOpen'])
        daily = [dict(rows[-1], open=100., timestamp=START.replace(hour=0, minute=0))]
        self.assertAlmostEqual(session_context(daily, 1440)['fromOpenPct'], 3)

    def test_candidates_are_symmetric_and_rr_uses_tp2_not_tp1(self):
        for sell, decision in ((False, 'BUY CANDIDATE'), (True, 'SELL CANDIDATE')):
            rows, overlay, now = self.fixture(sell)
            result = assess(rows, rows, overlay, 5, now)
            self.assertEqual(result['decision'], decision, result['decisionReason'])
            self.assertEqual(result['remainingRR'], 2)
            self.assertEqual(result['rrTarget'], 'TP2')
            self.assertEqual(result['nextTarget'], 'TP1')
            self.assertEqual(result['stopDistancePct'], 2)

    def test_stop_touch_and_weak_adx_block_entry_without_altering_pine_setup(self):
        rows, overlay, now = self.fixture()
        original = deepcopy(overlay['setup'])
        rows[-1]['low'] = 97
        overlay['dashboardMetrics']['adx'] = 18.4
        result = assess(rows, rows, overlay, 5, now)
        self.assertTrue(result['stopTouched'])
        self.assertEqual(result['decision'], 'WAIT')
        self.assertEqual(result['strength'], 'WEAK BULLISH')
        self.assertIn('ADX', result['decisionReason'])
        self.assertEqual(overlay['setup'], original)

    def test_old_or_developing_data_is_wait(self):
        rows, overlay, now = self.fixture()
        for options in (dict(now=now + timedelta(days=1)), dict(now=now, developing=True)):
            result = assess(rows, rows, overlay, 5, **options)
            self.assertEqual(result['decision'], 'WAIT')

    def test_no_future_five_minute_bars_or_midday_open_invention(self):
        rows, overlay, now = self.fixture()
        overlay['fiveMinuteAsOf'] = (now + timedelta(hours=1)).isoformat()
        result = assess(rows[5:], rows[5:], overlay, 5, now)
        self.assertIsNone(result['dayOpen'])
        self.assertEqual(result['decision'], 'WAIT')

    def test_price_proximity_and_reward_gate_are_direction_aware(self):
        for sell in (False, True):
            rows, overlay, now = self.fixture(sell)
            rows[-1].update(close=101.9 if not sell else 98.1, high=102. if not sell else 101., low=99. if not sell else 98.)
            result = assess(rows, rows, overlay, 5, now)
            self.assertEqual(result['nearestLevel'], 'Near TP1')
            self.assertAlmostEqual(result['nearestLevelPct'], .1 / rows[-1]['close'] * 100)
            self.assertLess(result['remainingRR'], 1.5)
            self.assertEqual(result['decision'], 'WAIT')

    def test_displayed_developing_price_is_used_for_open_move(self):
        rows, overlay, now = self.fixture()
        five = deepcopy(rows[:-1])
        rows[-1].update(close=104., high=105.)
        result = assess(rows, five, overlay, 5, now, developing=True)
        self.assertAlmostEqual(result['fromOpenPct'], 4)
        self.assertAlmostEqual(result['dayHighPct'], 5)


if __name__ == '__main__':
    unittest.main()
