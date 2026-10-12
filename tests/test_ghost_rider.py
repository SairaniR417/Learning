import unittest
from datetime import datetime, timedelta, timezone
import polars as pl
from scanner.strategies.ghost_rider import GhostRiderStrategy, atr14


class GhostRiderTests(unittest.TestCase):
    def scan(self, closes, wide_last=False):
        rows = [dict(instrument_key='TEST', timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=i), open=c, high=c+1, low=c-1, close=c, volume=1000) for i, c in enumerate(closes)]
        if wide_last:
            rows[-1]['high'] = 500
        return GhostRiderStrategy().run(pl.DataFrame(rows), {'TEST': {'symbol': 'TEST'}}, {'atr_multiplier': 1.5})[0]

    def test_new_buy_and_atr_levels(self):
        row = self.scan([100.] * 260 + [102.])
        self.assertEqual((row['signal'], row['state']), ('BUY', 'NEW'))
        self.assertEqual(row['entry'], 102)
        for n in range(1, 6):
            self.assertAlmostEqual(row[f'tp{n}'], row['entry'] + n * row['risk'])
        self.assertAlmostEqual(row['stopLoss'], row['entry'] - row['risk'])

    def test_wait_retains_signal_prices_and_hits(self):
        a = self.scan([100.] * 260 + [102.])
        b = self.scan([100.] * 260 + [102., 120., 115.])
        self.assertEqual(b['state'], 'WAIT')
        self.assertEqual(b['entry'], a['entry'])
        self.assertEqual(b['tp5'], a['tp5'])
        self.assertTrue(b['tp5Hit'])

    def test_opposite_signal_resets_targets(self):
        row = self.scan([100.] * 260 + [102., 120., 115., 90., 70.])
        self.assertEqual(row['signal'], 'SELL')
        self.assertLess(row['tp5'], row['entry'])
        self.assertGreater(row['stopLoss'], row['entry'])
        self.assertFalse(row['tp5Hit'])

    def test_signal_candle_hits_match_supplied_script(self):
        row = self.scan([100.] * 260 + [102.], wide_last=True)
        self.assertTrue(row['tp5Hit'])

    def test_atr_wilder_seed(self):
        rows = [dict(high=101., low=99., close=100.) for _ in range(15)]
        values = atr14(rows)
        self.assertIsNone(values[12])
        self.assertEqual(values[13:], [2., 2.])


if __name__ == '__main__':
    unittest.main()
