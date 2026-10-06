"""NSE equity universe loaded from Upstox's daily instrument master."""

import gzip
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException

NSE_INSTRUMENT_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
_cached_universe: list[dict[str, Any]] = []
_cache_expires_at: datetime | None = None


async def get_nse_equity_universe() -> list[dict[str, Any]]:
    """Return distinct NSE cash equities, refreshing the public master once daily."""
    global _cached_universe, _cache_expires_at
    now = datetime.now(timezone.utc)
    if _cached_universe and _cache_expires_at and _cache_expires_at > now:
        return _cached_universe

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(NSE_INSTRUMENT_MASTER_URL)
            response.raise_for_status()
        payload = response.content
        try:
            rows = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            rows = json.loads(gzip.decompress(payload))
    except (httpx.HTTPError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Unable to load the Upstox NSE instrument master.") from exc

    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Upstox returned an invalid NSE instrument master.")

    unique: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get("segment") != "NSE_EQ" or item.get("instrument_type") != "EQ":
            continue
        key = item.get("instrument_key")
        symbol = item.get("trading_symbol")
        if not key or not symbol:
            continue
        unique[key] = {
            "key": key,
            "symbol": symbol,
            "name": item.get("name") or symbol,
            "exchange": "NSE",
            "segment": item.get("segment"),
            "isin": item.get("isin"),
            "instrument_type": item.get("instrument_type"),
        }

    if not unique:
        raise HTTPException(status_code=502, detail="The Upstox NSE master contained no cash equities.")
    _cached_universe = list(unique.values())
    _cache_expires_at = now + timedelta(hours=24)
    return _cached_universe
