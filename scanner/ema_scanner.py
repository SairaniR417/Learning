"""EMA alignment scanner built on Drishti's existing analysis function."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date
from typing import Any
import asyncio

from drishti.ema_alignment import analyze_ema_alignment

HistoryFetcher = Callable[[str, str, int, date, date], Awaitable[Mapping[str, Any]]]


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
    """Scan an NSE universe with bounded concurrency and collect aligned stocks."""
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
                candles = history.get("candles", [])
                if len(candles) < 200:
                    return None, None
                analysis = analyze_ema_alignment(
                    candles,
                    symbol=symbol,
                    exchange=str(instrument.get("exchange") or "NSE"),
                    timeframe=timeframe,
                )
                if not analysis.bullishAlignment:
                    return None, None
                return {
                    "symbol": analysis.symbol,
                    "instrumentKey": key,
                    "exchange": analysis.exchange,
                    "timeframe": analysis.timeframe,
                    "close": analysis.close,
                    "ema9": analysis.ema.ema9,
                    "ema20": analysis.ema.ema20,
                    "ema50": analysis.ema.ema50,
                    "ema200": analysis.ema.ema200,
                    "status": analysis.status.value,
                    "bullishAlignment": analysis.bullishAlignment,
                    "alignedSince": analysis.alignedSince,
                    "transitionTimestamp": analysis.transitionTimestamp,
                    "candlesAnalyzed": analysis.candlesAnalyzed,
                }, None
            except Exception as exc:
                return None, {"symbol": symbol, "error": str(exc)}

    scanned = await asyncio.gather(*(scan_one(instrument) for instrument in instruments))
    results = [result for result, _ in scanned if result is not None]
    errors = [error for _, error in scanned if error is not None]
    results.sort(key=lambda item: (item["status"] != "NEWLY_ALIGNED", item["symbol"]))
    return {
        "strategy": "EMA_ALIGNMENT",
        "timeframe": timeframe,
        "scanned": len(instruments),
        "matched": len(results),
        "results": results,
        "errors": errors,
    }
