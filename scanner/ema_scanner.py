"""EMA alignment scanner built on Drishti's existing analysis function."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date
from typing import Any
import asyncio
import math

from drishti.ema import calculate_ema
from drishti.market_data import normalize_candles

HistoryFetcher = Callable[[str, str, int, date, date], Awaitable[Mapping[str, Any]]]


def _simple_moving_average(closes: list[float], period: int) -> list[float | None]:
    values: list[float | None] = [None] * len(closes)
    rolling_sum = sum(closes[:period])
    for index in range(period - 1, len(closes)):
        if index >= period:
            rolling_sum += closes[index] - closes[index - period]
        values[index] = rolling_sum / period
    return values


async def scan_ema_universe(
    instruments: Sequence[Mapping[str, Any]],
    fetch_history: HistoryFetcher,
    *,
    unit: str,
    interval: int,
    from_date: date,
    to_date: date,
    concurrency: int = 10,
) -> dict[str, Any]:
    """Scan an NSE universe for closes above EMA 9/20 and SMA 50/200."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    semaphore = asyncio.Semaphore(concurrency)
    timeframe = f"{unit}:{interval}"

    async def scan_one(instrument: Mapping[str, Any]):
        symbol = str(instrument.get("symbol") or "UNKNOWN")
        key = str(instrument.get("key") or "")
        async with semaphore:
            try:
                history = await fetch_history(key, unit, interval, from_date, to_date)
                candles = normalize_candles(history.get("candles", []))
                if len(candles) < 200:
                    return None, None
                closes = [float(candle["close"]) for candle in candles]
                if any(not math.isfinite(close) for close in closes):
                    raise ValueError("candle closes must be finite numbers")
                ema9, ema20 = (calculate_ema(closes, period) for period in (9, 20))
                sma50 = _simple_moving_average(closes, 50)
                sma200 = _simple_moving_average(closes, 200)
                matches: list[bool | None] = []
                for close, ema9_value, ema20_value, sma50_value, sma200_value in zip(
                    closes, ema9, ema20, sma50, sma200
                ):
                    if None in (ema9_value, ema20_value, sma50_value, sma200_value):
                        matches.append(None)
                    else:
                        matches.append(
                            close > ema9_value
                            and close > ema20_value
                            and close > sma50_value
                            and close > sma200_value
                        )
                if matches[-1] is not True:
                    return None, None
                match_start = len(matches) - 1
                while match_start > 0 and matches[match_start - 1] is True:
                    match_start -= 1
                return {
                    "symbol": symbol,
                    "instrumentKey": key,
                    "exchange": str(instrument.get("exchange") or "NSE"),
                    "timeframe": timeframe,
                    "close": closes[-1],
                    "ema9": ema9[-1],
                    "ema20": ema20[-1],
                    "sma50": sma50[-1],
                    "sma200": sma200[-1],
                    "status": "NEWLY_ALIGNED" if matches[-2] is False else "ALIGNED",
                    "matches": True,
                    "matchedSince": candles[match_start]["timestamp"],
                    "candlesAnalyzed": len(candles),
                }, None
            except Exception as exc:
                return None, {"symbol": symbol, "error": str(exc)}

    scanned = await asyncio.gather(*(scan_one(instrument) for instrument in instruments))
    results = [result for result, _ in scanned if result is not None]
    errors = [error for _, error in scanned if error is not None]
    results.sort(key=lambda item: (item["status"] != "NEWLY_ALIGNED", item["symbol"]))
    return {
        "strategy": "CLOSE_ABOVE_EMA9_EMA20_SMA50_SMA200",
        "timeframe": timeframe,
        "scanned": len(instruments),
        "matched": len(results),
        "results": results,
        "errors": errors,
    }
