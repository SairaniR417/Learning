import unittest
from datetime import date, timedelta

from drishti.ema_alignment import AlignmentStatus, analyze_ema_alignment
from drishti.ema import calculate_ema
from drishti.market_data import normalize_candles


def candles(closes):
    start = date(2000, 1, 1)
    return [{"timestamp": (start + timedelta(days=index)).isoformat(), "close": close} for index, close in enumerate(closes)]


class EmaAlignmentTests(unittest.TestCase):
    def test_insufficient_history(self):
        result = analyze_ema_alignment(candles([10] * 199))
        self.assertEqual(result.status, AlignmentStatus.INSUFFICIENT_HISTORY)
        self.assertIsNone(result.ema.ema200)

    def test_newly_aligned_and_transition_index(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(7)]
        result = analyze_ema_alignment(candles(closes), symbol='TEST')
        self.assertEqual(result.status, AlignmentStatus.NEWLY_ALIGNED)
        self.assertTrue(result.bullishAlignment)
        self.assertEqual(result.transitionIndex, 206)
        self.assertEqual(result.transitionTimestamp, candles(closes)[206]['timestamp'])
        self.assertEqual(result.alignedSince, result.transitionTimestamp)

    def test_aligned_after_transition_candle(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(8)]
        result = analyze_ema_alignment(candles(closes))
        self.assertEqual(result.status, AlignmentStatus.ALIGNED)
        self.assertTrue(result.bullishAlignment)

    def test_price_below_ema_breaks_full_predicate(self):
        closes = list(range(300, 100, -1)) + [1000, 1]
        result = analyze_ema_alignment(candles(closes))
        self.assertEqual(result.status, AlignmentStatus.NOT_ALIGNED)
        self.assertFalse(result.conditions.priceAboveEma9)

    def test_ema_relationships_can_become_true_on_different_candles(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(7)]
        result = analyze_ema_alignment(candles(closes))
        self.assertIn(result.status, (AlignmentStatus.ALIGNED, AlignmentStatus.NEWLY_ALIGNED))
        self.assertTrue(result.conditions.ema9AboveEma20)
        self.assertTrue(result.conditions.ema20AboveEma50)
        self.assertTrue(result.conditions.ema50AboveEma200)
        at_200 = analyze_ema_alignment(candles(closes[:201]))
        self.assertTrue(at_200.conditions.ema9AboveEma20)
        self.assertTrue(at_200.conditions.ema20AboveEma50)
        self.assertFalse(at_200.conditions.ema50AboveEma200)
        self.assertEqual(result.transitionIndex, 206)

    def test_first_valid_ema200_is_not_a_confirmed_new_transition(self):
        closes = list(range(1, 200)) + [1000]
        result = analyze_ema_alignment(candles(closes))
        self.assertEqual(result.status, AlignmentStatus.ALIGNED)
        self.assertIsNone(result.transitionIndex)
        self.assertIsNone(result.transitionTimestamp)

    def test_each_rule_relationship_is_exposed(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(7)]
        result = analyze_ema_alignment(candles(closes))
        self.assertTrue(result.conditions.priceAboveEma9)
        self.assertTrue(result.conditions.priceAboveEma20)
        self.assertTrue(result.conditions.priceAboveEma50)
        self.assertTrue(result.conditions.priceAboveEma200)
        self.assertTrue(result.conditions.ema9AboveEma20)
        self.assertTrue(result.conditions.ema20AboveEma50)
        self.assertTrue(result.conditions.ema50AboveEma200)

    def test_history_values_have_no_lookahead(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(7)]
        longer = closes + [800]
        a = [calculate_ema(closes, period)[-1] for period in (9, 20, 50, 200)]
        b = [calculate_ema(longer, period)[len(closes) - 1] for period in (9, 20, 50, 200)]
        self.assertEqual(a, b)
        self.assertEqual(analyze_ema_alignment(candles(closes)).status, AlignmentStatus.NEWLY_ALIGNED)

    def test_transition_metadata_is_inactive_when_latest_candle_is_not_aligned(self):
        closes = list(range(300, 100, -1)) + [500 + index * 20 for index in range(7)] + [1]
        result = analyze_ema_alignment(candles(closes))
        self.assertEqual(result.status, AlignmentStatus.NOT_ALIGNED)
        self.assertIsNone(result.transitionIndex)
        self.assertIsNone(result.transitionTimestamp)
        self.assertIsNone(result.alignedSince)

    def test_second_alignment_phase_reports_latest_transition(self):
        closes = list(range(500, 100, -1)) + [100 + index * 8 for index in range(100)] + [1]
        closes += [1 + index * 10 for index in range(100)]
        result = analyze_ema_alignment(candles(closes))
        self.assertEqual(result.status, AlignmentStatus.ALIGNED)
        self.assertEqual(result.transitionIndex, 548)
        self.assertEqual(result.transitionTimestamp, candles(closes)[548]["timestamp"])
        self.assertEqual(result.alignedSince, result.transitionTimestamp)

    def test_history_quality_metadata(self):
        short = analyze_ema_alignment(candles([10] * 199))
        minimum = analyze_ema_alignment(candles([10] * 200))
        self.assertEqual((short.minimumHistory, short.recommendedHistory, short.historyStatus), (200, 400, "INSUFFICIENT"))
        self.assertEqual(minimum.historyStatus, "MINIMUM_ONLY")

    def test_normalization_orders_copies_and_rejects_duplicate_or_invalid_timestamps(self):
        original = candles([1, 2, 3])
        reversed_input = list(reversed(original))
        result = normalize_candles(reversed_input)
        self.assertEqual([item["close"] for item in result], [1, 2, 3])
        self.assertIsNot(result, reversed_input)
        self.assertEqual([item["close"] for item in reversed_input], [3, 2, 1])
        self.assertEqual(normalize_candles([]), [])
        unsorted = [original[2], original[0], original[1]]
        self.assertEqual([item["close"] for item in normalize_candles(unsorted)], [1, 2, 3])
        with self.assertRaisesRegex(ValueError, "unique"):
            normalize_candles([original[0], dict(original[0])])
        with self.assertRaisesRegex(ValueError, "timestamp"):
            normalize_candles([{"timestamp": "not-a-date", "close": 1}])


if __name__ == '__main__':
    unittest.main()
