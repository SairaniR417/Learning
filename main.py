import os
import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlencode
from urllib.parse import quote as url_quote

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse

load_dotenv()

app = FastAPI(title="Market Desk API")
client_id = os.getenv("UPSTOX_CLIENT_ID", "")
client_secret = os.getenv("UPSTOX_CLIENT_SECRET", "")
redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "http://localhost:4200/oauth/callback")
frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:4200")
access_token: str | None = None
access_token_expires_at: datetime | None = None
pending_states: dict[str, datetime] = {}
instrument_key_pattern = re.compile(r"^[A-Z0-9_]+\|[A-Za-z0-9 ._-]+$")
HISTORICAL_INTERVALS = {
    "minutes": {1, 2, 3, 5, 10, 15, 30, 60},
    "hours": {1, 2, 3, 4, 5},
    "days": {1},
    "weeks": {1},
    "months": {1},
}


def next_token_expiry() -> datetime:
    india = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(india)
    expiry = now.replace(hour=3, minute=30, second=0, microsecond=0)
    if expiry <= now:
        expiry += timedelta(days=1)
    return expiry.astimezone(timezone.utc)


def require_token() -> str:
    if not access_token or not access_token_expires_at or access_token_expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Connect your Upstox account to continue.")
    return access_token


async def api_json_request(url: str, *, method: str = "GET", headers: dict | None = None, data=None, params=None):
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.request(method, url, headers=headers, data=data, params=params)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.is_success:
        errors = body.get("errors", []) if isinstance(body, dict) else []
        message = errors[0].get("message") if errors else body.get("message") if isinstance(body, dict) else None
        raise HTTPException(status_code=502, detail=message or f"Upstox returned HTTP {response.status_code}.")
    return body


@app.get("/api/status")
async def status():
    connected = bool(access_token and access_token_expires_at and access_token_expires_at > datetime.now(timezone.utc))
    return {"connected": connected, "configured": bool(client_id and client_secret), "expiresAt": access_token_expires_at.isoformat() if connected else None}


@app.get("/auth/upstox")
async def authorize():
    if not client_id or not client_secret:
        return RedirectResponse(f"{frontend_origin}/?setup=1")
    now = datetime.now(timezone.utc)
    expired_states = [state for state, expires_at in pending_states.items() if expires_at <= now]
    for state in expired_states:
        pending_states.pop(state, None)
    state = secrets.token_urlsafe(32)
    pending_states[state] = now + timedelta(minutes=10)
    query = urlencode({"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state})
    return RedirectResponse(f"https://api.upstox.com/v2/login/authorization/dialog?{query}")


@app.get("/oauth/callback")
async def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    global access_token, access_token_expires_at
    state_expiry = pending_states.pop(state or "", None)
    if error or not code or not state_expiry or state_expiry <= datetime.now(timezone.utc):
        return RedirectResponse(f"{frontend_origin}/?auth=failed")
    try:
        result = await api_json_request(
            "https://api.upstox.com/v2/login/authorization/token",
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data={"code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri, "grant_type": "authorization_code"},
        )
        if not result.get("access_token"):
            raise HTTPException(status_code=502, detail="Upstox did not return an access token.")
        access_token = result["access_token"]
        access_token_expires_at = next_token_expiry()
        return RedirectResponse(f"{frontend_origin}/?auth=connected")
    except (HTTPException, httpx.HTTPError) as exc:
        print(f"Upstox token exchange failed: {exc}")
        return RedirectResponse(f"{frontend_origin}/?auth=failed")


@app.get("/api/instruments")
async def search_instruments(q: str = Query(default="", max_length=50)):
    token = require_token()
    query = q.strip()
    if len(query) < 2:
        return {"instruments": []}
    result = await api_json_request(
        "https://api.upstox.com/v2/instruments/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"query": query, "exchanges": "NSE", "segments": "EQ,INDEX", "page_number": 1, "records": 10},
    )
    instruments = [
        {
            "key": item.get("instrument_key"),
            "symbol": item.get("trading_symbol") or item.get("short_name") or item.get("name"),
            "name": item.get("name") or item.get("short_name") or item.get("trading_symbol"),
            "exchange": item.get("segment"),
        }
        for item in result.get("data", [])
    ]
    return {"instruments": instruments}


@app.get("/api/quotes")
async def quotes(keys: str = Query(min_length=1)):
    token = require_token()
    instrument_keys = [key for key in keys.split(",") if key]
    if len(instrument_keys) > 50 or any(not instrument_key_pattern.fullmatch(key) for key in instrument_keys):
        raise HTTPException(status_code=400, detail="Provide between 1 and 50 valid Upstox instrument keys.")
    result = await api_json_request(
        "https://api.upstox.com/v3/market-quote/ltp",
        headers={"Authorization": f"Bearer {token}"},
        params={"instrument_key": ",".join(instrument_keys)},
    )
    return {"data": result.get("data", {}), "receivedAt": int(datetime.now(timezone.utc).timestamp() * 1000)}


@app.post("/api/logout")
async def logout():
    global access_token, access_token_expires_at
    access_token = None
    access_token_expires_at = None
    return {"connected": False}


@app.get("/api/historical")
async def historical_candles(
    instrument_key: str = Query(min_length=1),
    unit: str = Query(),
    interval: int = Query(gt=0),
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
):
    token = require_token()
    if not instrument_key_pattern.fullmatch(instrument_key):
        raise HTTPException(status_code=400, detail="Provide a valid Upstox instrument key.")
    if unit not in HISTORICAL_INTERVALS or interval not in HISTORICAL_INTERVALS[unit]:
        raise HTTPException(status_code=400, detail="Unsupported historical candle interval.")
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="The start date must be on or before the end date.")
    if to_date > datetime.now(timezone.utc).date():
        raise HTTPException(status_code=400, detail="The end date cannot be in the future.")

    earliest = date(2022, 1, 1) if unit in {"minutes", "hours"} else date(2000, 1, 1)
    if from_date < earliest:
        raise HTTPException(status_code=400, detail=f"{unit.title()} data is available from {earliest.isoformat()}.")

    if unit == "minutes" and interval <= 15:
        max_days = 31
    elif unit == "minutes":
        max_days = 92
    elif unit == "hours":
        max_days = 92
    elif unit == "days":
        max_days = 3653
    else:
        max_days = None
    if max_days is not None and (to_date - from_date).days > max_days:
        raise HTTPException(status_code=400, detail=f"The selected interval supports a maximum range of about {max_days} days.")

    encoded_key = url_quote(instrument_key, safe="")
    url = f"https://api.upstox.com/v3/historical-candle/{encoded_key}/{unit}/{interval}/{to_date.isoformat()}/{from_date.isoformat()}"
    result = await api_json_request(url, headers={"Authorization": f"Bearer {token}"})
    candles = [
        {"timestamp": row[0], "open": row[1], "high": row[2], "low": row[3], "close": row[4], "volume": row[5]}
        for row in result.get("data", {}).get("candles", [])
    ]
    return {"candles": candles, "instrument_key": instrument_key, "unit": unit, "interval": interval}