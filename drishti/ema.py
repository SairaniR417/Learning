"""EMA calculation with an SMA seed and no look-ahead."""

from collections.abc import Iterable
import math


def calculate_ema(closes: Iterable[float], period: int) -> list[float | None]:
    """Return one EMA value per close; values before the SMA seed are None."""
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError("period must be a positive integer")

    values = [float(value) for value in closes]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("closes must contain only finite numbers")
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result

    current = sum(values[:period]) / period
    result[period - 1] = current
    alpha = 2 / (period + 1)
    for index in range(period, len(values)):
        current = alpha * values[index] + (1 - alpha) * current
        result[index] = current
    return result
