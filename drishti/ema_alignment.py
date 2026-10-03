"""Pure bullish EMA alignment analysis and typed API response models."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
import math
from typing import Any

from pydantic import BaseModel

from .ema import calculate_ema


class AlignmentStatus(StrEnum):
    ALIGNED = "ALIGNED"
    NEWLY_ALIGNED = "NEWLY_ALIGNED"
    NOT_ALIGNED = "NOT_ALIGNED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class EmaValues(BaseModel):
    ema9: float | None
    ema20: float | None
    ema50: float | None
    ema200: float | None


class AlignmentConditions(BaseModel):
    priceAboveEma9: bool
    priceAboveEma20: bool
    priceAboveEma50: bool
    priceAboveEma200: bool
    ema9AboveEma20: bool
    ema20AboveEma50: bool
    ema50AboveEma200: bool


class EmaAlignmentResponse(BaseModel):
    symbol: str
    exchange: str
    timeframe: str
    asOf: str | None
    close: float | None
    ema: EmaValues
    conditions: AlignmentConditions
    bullishAlignment: bool
    status: AlignmentStatus
    alignedSince: str | None = None
    transitionIndex: int | None = None
    transitionTimestamp: str | None = None
    candlesAnalyzed: int


def _timestamp(candle: Mapping[str, Any]) -> str | None:
    value = candle.get("timestamp")
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def analyze_ema_alignment(
    candles: Sequence[Mapping[str, Any]], *, symbol: str = "", exchange: str = "", timeframe: str = "days:1"
) -> EmaAlignmentResponse:
    """Analyze ordered OHLC candles. ``transitionIndex`` is zero-based."""
    closes: list[float] = []
    for candle in candles:
        try:
            close = float(candle["close"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("each candle must contain a numeric close") from exc
        if not math.isfinite(close):
            raise ValueError("candle closes must be finite numbers")
        closes.append(close)

    ema9, ema20, ema50, ema200 = (calculate_ema(closes, period) for period in (9, 20, 50, 200))
    aligned: list[bool | None] = []
    for index, close in enumerate(closes):
        values = (ema9[index], ema20[index], ema50[index], ema200[index])
        if any(value is None for value in values):
            aligned.append(None)
            continue
        e9, e20, e50, e200 = values
        aligned.append(bool(close > e9 and close > e20 and close > e50 and close > e200
                            and e9 > e20 and e20 > e50 and e50 > e200))

    transition_index = next(
        (index for index in range(1, len(aligned)) if aligned[index] is True and aligned[index - 1] is False),
        None,
    )
    latest_index = len(closes) - 1
    enough_history = latest_index >= 199
    latest_aligned = aligned[-1] if aligned else None
    previous_valid = aligned[-2] if len(aligned) >= 2 else None

    if not enough_history:
        status = AlignmentStatus.INSUFFICIENT_HISTORY
    elif latest_aligned is not True:
        status = AlignmentStatus.NOT_ALIGNED
    elif previous_valid is True:
        status = AlignmentStatus.ALIGNED
    elif previous_valid is False:
        status = AlignmentStatus.NEWLY_ALIGNED
    else:
        # The prior candle has no EMA 200, so this is not a confirmed transition.
        status = AlignmentStatus.ALIGNED

    conditions = AlignmentConditions(
        priceAboveEma9=bool(closes and ema9[-1] is not None and closes[-1] > ema9[-1]),
        priceAboveEma20=bool(closes and ema20[-1] is not None and closes[-1] > ema20[-1]),
        priceAboveEma50=bool(closes and ema50[-1] is not None and closes[-1] > ema50[-1]),
        priceAboveEma200=bool(closes and ema200[-1] is not None and closes[-1] > ema200[-1]),
        ema9AboveEma20=bool(closes and ema9[-1] is not None and ema20[-1] is not None and ema9[-1] > ema20[-1]),
        ema20AboveEma50=bool(closes and ema20[-1] is not None and ema50[-1] is not None and ema20[-1] > ema50[-1]),
        ema50AboveEma200=bool(closes and ema50[-1] is not None and ema200[-1] is not None and ema50[-1] > ema200[-1]),
    )
    transition_timestamp = _timestamp(candles[transition_index]) if transition_index is not None else None
    return EmaAlignmentResponse(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        asOf=_timestamp(candles[-1]) if candles else None,
        close=closes[-1] if closes else None,
        ema=EmaValues(ema9=ema9[-1] if closes else None, ema20=ema20[-1] if closes else None,
                      ema50=ema50[-1] if closes else None, ema200=ema200[-1] if closes else None),
        conditions=conditions,
        bullishAlignment=latest_aligned is True,
        status=status,
        alignedSince=transition_timestamp,
        transitionIndex=transition_index,
        transitionTimestamp=transition_timestamp,
        candlesAnalyzed=len(candles),
    )
