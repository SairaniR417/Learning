"""Validation and chronological normalization for market candles."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any


def normalize_candles(candles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return copied candles ordered oldest to newest, rejecting bad timestamps."""
    normalized: list[tuple[datetime, float, int, dict[str, Any]]] = []
    seen: set[datetime] = set()
    for position, candle in enumerate(candles):
        if not isinstance(candle, Mapping):
            raise ValueError("each candle must be an object")
        raw = candle.get("timestamp")
        if isinstance(raw, datetime):
            timestamp = raw
        elif isinstance(raw, str):
            try:
                timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("each candle must have a valid ISO timestamp") from exc
        else:
            raise ValueError("each candle must have a valid ISO timestamp")
        comparable = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
        if comparable in seen:
            raise ValueError("candle timestamps must be unique")
        seen.add(comparable)
        normalized.append((timestamp, comparable.timestamp(), position, dict(candle)))
    normalized.sort(key=lambda item: (item[1], item[2]))
    return [candle for _, _, _, candle in normalized]
