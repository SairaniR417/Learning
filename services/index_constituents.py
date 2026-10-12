"""Official index membership for heatmap filters, refreshed daily."""
import csv
import gzip
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/market")
INDEXES = {
    "nifty50": ("Nifty 50", "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"),
    "banknifty": ("Bank Nifty", "https://www.niftyindices.com/IndexConstituent/ind_niftybanklist.csv"),
    "midcap100": ("Nifty Midcap 100", "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap100list.csv"),
    "sensex": ("Sensex", "https://www.bseindices.com/AsiaIndexAPI/api/Codewise_Indices/w?code=16"),
}
BSE_MASTER = "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz"
_cache = {}


def parse_nifty_csv(payload: str):
    members = []
    for row in csv.DictReader(io.StringIO(payload.lstrip('\ufeff'))):
        symbol = (row.get("Symbol") or "").strip()
        isin = (row.get("ISIN Code") or "").strip()
        if symbol and re.fullmatch(r"IN[A-Z0-9]{10}", isin):
            members.append({"symbol": symbol, "isin": isin})
    if not members:
        raise ValueError("Empty or invalid constituent CSV")
    return list({m["isin"]: m for m in members}.values())


def parse_sensex(payload: dict, instruments: list):
    # BSE equity types are trading groups (A/B/X), and scrip codes are exchange tokens.
    mapping = {str(item.get("exchange_token", "")): item
               for item in instruments if item.get("segment") == "BSE_EQ"}
    rows = payload.get("Table", [])
    members = []
    for row in rows:
        instrument = mapping.get(str(row.get("SCRIP_CODE")), {})
        isin = instrument.get("isin", "")
        if not re.fullmatch(r"IN[A-Z0-9]{10}", isin):
            raise ValueError("Unable to map a Sensex constituent to its equity ISIN")
        members.append({"symbol": instrument.get("trading_symbol", ""), "isin": isin})
    if len({m["isin"] for m in members}) != 30:
        raise ValueError("Expected 30 distinct Sensex constituents")
    return members


@router.get("/index-constituents/{index_id}")
async def index_constituents(index_id: Literal["nifty50", "banknifty", "midcap100", "sensex"]):
    now = datetime.now(timezone.utc)
    cached = _cache.get(index_id)
    if cached and cached[0] > now:
        return cached[1]
    name, url = INDEXES[index_id]
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0", "Accept": "application/json,text/csv,*/*"
        }) as client:
            response = await client.get(url)
            response.raise_for_status()
            if index_id == "sensex":
                master = await client.get(BSE_MASTER)
                master.raise_for_status()
                try:
                    instruments = master.json()
                except (ValueError, UnicodeDecodeError):
                    instruments = json.loads(gzip.decompress(master.content))
                members = parse_sensex(response.json(), instruments)
            else:
                members = parse_nifty_csv(response.text)
                expected = {"nifty50": 50, "midcap100": 100}
                if index_id in expected and len(members) != expected[index_id]:
                    raise ValueError("Unexpected constituent count")
        result = {"id": index_id, "name": name, "members": members, "source": url, "fetchedAt": now.isoformat()}
    except (httpx.HTTPError, ValueError, OSError, TypeError, AttributeError) as exc:
        raise HTTPException(502, f"Could not load official {name} constituents. Please retry.") from exc
    _cache[index_id] = (now + timedelta(hours=24), result)
    return result
