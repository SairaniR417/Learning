"""Active front-month commodity futures from Upstox's MCX instrument master."""

import gzip
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException

MCX_INSTRUMENT_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/MCX.json.gz"
_cached_universe: list[dict[str, Any]] = []
_cache_expires_at: datetime | None = None
_DASHBOARD_COMMODITIES = {
    "GOLD", "GOLDM", "SILVER", "SILVERM", "CRUDEOIL", "CRUDEOILM",
    "NATURALGAS", "NATGASMINI", "COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL",
}


def _expiry_date(value: Any) -> date | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


async def get_mcx_front_month_universe() -> list[dict[str, Any]]:
    """Return the nearest unexpired futures contract for each dashboard commodity."""
    global _cached_universe, _cache_expires_at
    now = datetime.now(timezone.utc)
    if _cached_universe and _cache_expires_at and _cache_expires_at > now:
        return _cached_universe

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(MCX_INSTRUMENT_MASTER_URL)
            response.raise_for_status()
        try:
            rows = response.json()
        except (ValueError, UnicodeDecodeError):
            rows = json.loads(gzip.decompress(response.content))
    except (httpx.HTTPError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Unable to load the Upstox MCX instrument master.") from exc

    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Upstox returned an invalid MCX instrument master.")

    today = now.date()
    nearest: dict[str, tuple[date, dict[str, Any]]] = {}
    for item in rows:
        if not isinstance(item, dict) or item.get("segment") != "MCX_FO" or item.get("instrument_type") != "FUT":
            continue
        underlying = str(item.get("underlying_symbol") or "").upper()
        key = item.get("instrument_key")
        expiry = _expiry_date(item.get("expiry"))
        if underlying not in _DASHBOARD_COMMODITIES or not key or not expiry or expiry < today:
            continue
        current = nearest.get(underlying)
        if current is None or expiry < current[0]:
            symbol = item.get("trading_symbol") or item.get("short_name") or underlying
            nearest[underlying] = (expiry, {
                "key": key,
                "symbol": underlying,
                "name": item.get("name") or underlying,
                "exchange": "MCX",
                "segment": "MCX_FO",
                "instrument_type": "FUT",
                "expiry": expiry.isoformat(),
                "trading_symbol": symbol,
            })

    _cached_universe = [instrument for _, instrument in sorted(nearest.values(), key=lambda entry: entry[1]["symbol"])]
    _cache_expires_at = now + timedelta(hours=12)
    if not _cached_universe:
        raise HTTPException(status_code=502, detail="The Upstox MCX master contained no active commodity futures.")
    return _cached_universe
