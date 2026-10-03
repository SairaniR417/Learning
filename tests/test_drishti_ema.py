import unittest

from drishti.ema import calculate_ema


class EmaTests(unittest.TestCase):
    def test_sma_seed_and_recursive_values(self):
        values = calculate_ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(values[:2], [None, None])
        self.assertAlmostEqual(values[2], 2.0)
        self.assertAlmostEqual(values[3], 3.0)
        self.assertAlmostEqual(values[4], 4.0)

    def test_insufficient_history_returns_unavailable_values(self):
        self.assertEqual(calculate_ema([10, 12], 3), [None, None])

    def test_prefix_result_does_not_depend_on_future_closes(self):
        prefix = [10, 11, 9, 12, 14, 13]
        later = prefix + [1000, -500]
        self.assertEqual(calculate_ema(prefix, 3), calculate_ema(later, 3)[:len(prefix)])

    def test_rejects_invalid_period_and_non_finite_values(self):
        with self.assertRaises(ValueError):
            calculate_ema([1, 2], 0)
        with self.assertRaises(ValueError):
            calculate_ema([1, float('nan')], 2)


if __name__ == '__main__':
    unittest.main()
