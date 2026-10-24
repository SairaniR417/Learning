from datetime import datetime, timedelta, timezone
from dataclasses import replace
import unittest
from unittest.mock import patch

import polars as pl

from scanner.strategies.golden_death_cross import GoldenDeathCrossStrategy
from scanner.rsi_divergence_legacy import DivergenceConfig, RsiDivergenceStrategy, detect_events, valid_segments
from scanner.backtest_rsi_divergence import simulate


def fixture(kind='REGULAR_BULLISH', size=269):
    up = kind == 'HIDDEN_BULLISH'
    down = kind == 'HIDDEN_BEARISH'
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(size):
        close = 100 + i * .1 if up else 200 - i * .1 if down else 100.0
        rows.append({'instrument_key': 'NSE_EQ|TEST', 'timestamp': start + timedelta(days=i),
                     'open': close, 'high': close + 2, 'low': close - 2, 'close': close, 'volume': 1000})
    rsi = [50.0] * size
    low = kind.endswith('BULLISH')
    field = 'low' if low else 'high'
    prices = {'REGULAR_BULLISH': (90, 85), 'REGULAR_BEARISH': (110, 115),
              'HIDDEN_BULLISH': (120, 122), 'HIDDEN_BEARISH': (180, 178)}[kind]
    oscillators = {'REGULAR_BULLISH': (35, 40), 'REGULAR_BEARISH': (65, 60),
                  'HIDDEN_BULLISH': (45, 40), 'HIDDEN_BEARISH': (55, 60)}[kind]
    for i, price, oscillator in zip((255, 265), prices, oscillators):
        if i < size:
            rows[i][field] = price
            rsi[i] = oscillator
    return rows, rsi


class RsiDivergenceTests(unittest.TestCase):
    def events(self, rows, rsi, config=DivergenceConfig()):
        with patch.object(GoldenDeathCrossStrategy, '_rsi', return_value=rsi):
            return detect_events(rows, config)

    def test_wilder_seed_and_boundaries(self):
        prices = [44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28]
        self.assertAlmostEqual(GoldenDeathCrossStrategy._rsi(prices, 14)[14], 70.464135, places=5)
        self.assertEqual(GoldenDeathCrossStrategy._rsi([1.] * 20, 14)[-1], 50)
        self.assertEqual(GoldenDeathCrossStrategy._rsi(list(range(1, 21)), 14)[-1], 100)
        self.assertEqual(GoldenDeathCrossStrategy._rsi(list(range(20, 0, -1)), 14)[-1], 0)

    def test_all_four_patterns(self):
        for kind in ('REGULAR_BULLISH', 'REGULAR_BEARISH', 'HIDDEN_BULLISH', 'HIDDEN_BEARISH'):
            with self.subTest(kind=kind):
                rows, rsi = fixture(kind)
                events = self.events(rows, rsi)
                self.assertEqual([e['divergenceType'] for e in events], [kind])
                self.assertEqual(events[0]['detectedIndex'], 268)
                self.assertEqual(events[0]['pivot2Index'], 265)
                self.assertIsNone(events[0]['confirmedIndex'])

    def test_pivot_not_available_until_right_bars(self):
        rows, rsi = fixture()
        self.assertEqual(self.events(rows[:268], rsi[:268]), [])
        self.assertEqual(len(self.events(rows, rsi)), 1)

    def test_future_never_changes_already_known_detection(self):
        rows, rsi = fixture(size=280)
        full = self.events(rows, rsi)
        for length in range(269, 281):
            prefix = self.events(rows[:length], rsi[:length])
            for event in prefix:
                same = next(e for e in full if e['detectedIndex'] == event['detectedIndex'])
                for field in ('divergenceType', 'pivot1At', 'pivot2At', 'detectedAt', 'triggerPrice', 'invalidationPrice'):
                    self.assertEqual(event[field], same[field])

    def test_thresholds_and_equal_plateaus(self):
        rows, rsi = fixture()
        self.assertEqual(self.events(rows, rsi, replace(DivergenceConfig(), min_rsi_delta=6)), [])
        self.assertEqual(self.events(rows, rsi, replace(DivergenceConfig(), min_price_pct=6)), [])
        rows[266]['low'] = rows[265]['low']
        self.assertEqual(self.events(rows, rsi), [])

    def test_hidden_requires_matching_trend(self):
        rows, rsi = fixture('HIDDEN_BULLISH')
        for row in rows:
            row.update(open=130., close=130., high=132.)
        self.assertEqual(self.events(rows, rsi), [])

    def test_breakout_and_invalidation(self):
        rows, rsi = fixture(size=273)
        rows[270].update(close=105., high=106.)
        event = self.events(rows, rsi)[0]
        self.assertEqual(event['confirmedIndex'], 270)
        rows[269]['low'] = 84.
        event = self.events(rows, rsi)[0]
        self.assertEqual(event['invalidatedIndex'], 269)
        self.assertIsNone(event['confirmedIndex'])

    def test_scan_watch_confirmed_and_broken_pattern_removed(self):
        rows, rsi = fixture(size=273)
        strategy = RsiDivergenceStrategy()
        instruments = {'NSE_EQ|TEST': {'symbol': 'TEST', 'exchange': 'NSE'}}
        def run():
            with patch.object(GoldenDeathCrossStrategy, '_rsi', side_effect=lambda values, period: rsi[:len(values)]):
                return strategy.run(pl.DataFrame(rows), instruments, {})
        self.assertEqual(run()[0]['state'], 'WATCH')
        rows[270].update(close=105., high=106.)
        self.assertEqual(run()[0]['state'], 'CONFIRMED')
        rows[272]['low'] = 84.
        self.assertEqual(run(), [])

    def test_old_detection_is_not_presented_as_new(self):
        rows, rsi = fixture(size=280)
        with patch.object(GoldenDeathCrossStrategy, '_rsi', return_value=rsi):
            self.assertEqual(RsiDivergenceStrategy().run(pl.DataFrame(rows), {'NSE_EQ|TEST': {'exchange':'NSE'}}, {}), [])

    def test_bad_data_and_action_jump_reset_history(self):
        rows, _ = fixture()
        rows[260].update(open=200., high=202., low=198., close=200.)
        self.assertEqual([len(s) for s in valid_segments(rows)], [260, 1, 8])
        rows[260]['close'] = float('nan')
        self.assertEqual([len(s) for s in valid_segments(rows)], [260, 8])
        rows[260] = rows[259].copy()
        self.assertGreater(len(list(valid_segments(rows))), 1)

    def test_parameter_relationship(self):
        with self.assertRaises(ValueError):
            DivergenceConfig.resolve({'min_gap': 30, 'max_gap': 10})

    def test_current_session_is_excluded(self):
        rows, rsi = fixture()
        rows[-1]['timestamp'] = datetime.now(timezone.utc)
        with patch.object(GoldenDeathCrossStrategy, '_rsi', side_effect=lambda values, period: rsi[:len(values)]):
            self.assertEqual(RsiDivergenceStrategy().run(pl.DataFrame(rows), {'NSE_EQ|TEST': {'exchange':'NSE'}}, {}), [])

    def test_registry_registration_and_daily_only(self):
        import asyncio
        from scanner.strategies.registry import StrategyRegistry
        registry = StrategyRegistry()
        from scanner.strategies.rsi_divergence import RsiDivergenceStrategy as PineStrategy
        self.assertIsInstance(registry.get('rsi_divergence'), PineStrategy)
        with self.assertRaisesRegex(ValueError, 'stored'):
            asyncio.run(registry.execute_scan('rsi_divergence', timeframe='1w'))

    def test_backtest_next_open_cost_and_ambiguous_stop_first(self):
        rows, rsi = fixture(size=280)
        event = self.events(rows, rsi)[0]
        rows[269].update(open=101., high=140., low=80., close=100.)
        trade = simulate(rows, event, 268)
        self.assertEqual(trade['entryIndex'], 269)
        self.assertEqual(trade['reason'], 'STOP')
        self.assertAlmostEqual(trade['netPct'], (85 * .999 / 101 - 1) * 100 - .2)
        self.assertIsNone(simulate(rows[:275], {**event, 'segmentEndIndex':274}, 268))

    def test_target_gap_fills_before_later_intrabar_stop(self):
        rows, rsi = fixture(size=280)
        event = self.events(rows, rsi)[0]
        rows[270].update(open=140., high=145., low=80., close=100.)
        trade = simulate(rows, event, 268)
        self.assertEqual(trade['reason'], 'TARGET')
        self.assertEqual(trade['exitIndex'], 270)


if __name__ == '__main__':
    unittest.main()
