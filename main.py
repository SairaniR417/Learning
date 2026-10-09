import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.parse import quote as url_quote
from typing import Literal

from contextlib import asynccontextmanager
import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from database.connection import init_db
from drishti.assistant import AssistantError, DEFAULT_MODEL, answer_question
from drishti.ema_alignment import EmaAlignmentResponse, analyze_ema_alignment
from scanner.ema_scanner import scan_ema_universe
from scanner.strategies import strategy_registry
from scanner.universe import get_nse_equity_universe
from services.market_sync import MarketSyncService, map_timeframe

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Market Desk API", lifespan=lifespan)
openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
drishti_openai_model = os.getenv("DRISHTI_OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
client_id = os.getenv("UPSTOX_CLIENT_ID", "")
client_secret = os.getenv("UPSTOX_CLIENT_SECRET", "")
configured_access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
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


class DrishtiChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class DrishtiChatRequest(BaseModel):
    messages: list[DrishtiChatMessage] = Field(min_length=1, max_length=24)


def upstox_is_configured() -> bool:
    placeholders = {"", "your_api_key", "your_api_secret"}
    token_is_configured = configured_access_token not in {"", "your_daily_access_token"}
    return token_is_configured or (client_id not in placeholders and client_secret not in placeholders)


def next_token_expiry() -> datetime:
    india = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(india)
    expiry = now.replace(hour=3, minute=30, second=0, microsecond=0)
    if expiry <= now:
        expiry += timedelta(days=1)
    return expiry.astimezone(timezone.utc)


# A manually generated token stays on the API server and expires daily.
if configured_access_token:
    access_token = configured_access_token
    access_token_expires_at = next_token_expiry()


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
    return {"connected": connected, "configured": upstox_is_configured(), "expiresAt": access_token_expires_at.isoformat() if connected else None}


@app.get("/auth/upstox")
async def authorize():
    if not upstox_is_configured():
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
async def search_instruments(q: str = Query(default="", max_length=50), market: str = Query(default="cash")):
    token = require_token()
    query = q.strip()
    if len(query) < 2:
        return {"instruments": []}
    if market == "cash":
        filters = {"exchanges": "NSE,BSE", "segments": "EQ,INDEX"}
    elif market == "commodities":
        filters = {"exchanges": "MCX", "segments": "COMM,FO", "instrument_types": "FUT"}
    else:
        raise HTTPException(status_code=400, detail="Market must be cash or commodities.")
    result = await api_json_request(
        "https://api.upstox.com/v2/instruments/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"query": query, **filters, "page_number": 1, "records": 10},
    )
    instruments = [
        {
            "key": item.get("instrument_key"),
            "symbol": item.get("trading_symbol") or item.get("short_name") or item.get("name"),
            "name": item.get("name") or item.get("short_name") or item.get("trading_symbol"),
            "exchange": item.get("exchange") or item.get("segment"),
            "segment": item.get("segment"),
            "isin": item.get("isin"),
            "lot_size": item.get("lot_size"),
            "tick_size": item.get("tick_size"),
            "instrument_type": item.get("instrument_type"),
        }
        for item in result.get("data", [])
    ]
    return {"instruments": instruments}


@app.get("/api/fundamentals/{isin}/corporate-actions")
async def corporate_actions(isin: str):
    token = require_token()
    if not re.fullmatch(r"IN[A-Z0-9]{10}", isin):
        raise HTTPException(status_code=400, detail="Provide a valid equity ISIN.")
    result = await api_json_request(
        f"https://api.upstox.com/v2/fundamentals/{isin}/corporate-actions",
        headers={"Authorization": f"Bearer {token}"},
    )
    return {"actions": result.get("data", [])}


@app.get("/api/fundamentals/{isin}/profile")
async def company_profile(isin: str):
    token = require_token()
    if not re.fullmatch(r"IN[A-Z0-9]{10}", isin):
        raise HTTPException(status_code=400, detail="Provide a valid equity ISIN.")
    result = await api_json_request(
        f"https://api.upstox.com/v2/fundamentals/{isin}/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    return result.get("data", {})


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


@app.post("/api/drishti/chat")
async def drishti_chat(request: DrishtiChatRequest):
    """Answer general questions through OpenAI without exposing server credentials."""
    if not openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI chat is not configured. Add OPENAI_API_KEY to the server .env file and restart the API.",
        )
    messages = request.messages[-12:]
    if messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="The last chat message must be from the user.")
    try:
        return await answer_question(
            [message.model_dump() for message in messages],
            api_key=openai_api_key,
            model=drishti_openai_model,
        )
    except AssistantError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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


@app.get("/api/drishti/ema-alignment", response_model=EmaAlignmentResponse)
async def drishti_ema_alignment(
    symbol: str = Query(min_length=1, max_length=50),
    instrument_key: str | None = Query(default=None, min_length=1, max_length=100),
    exchange: str | None = Query(default=None, max_length=30),
    unit: str = Query(default="days"),
    interval: int = Query(default=1, gt=0),
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
):
    """Analyze one instrument using authenticated Upstox history."""
    normalized_symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 .&_-]*", normalized_symbol):
        raise HTTPException(status_code=400, detail="Provide a valid instrument symbol.")

    timeframe = f"{unit}:{interval}"
    try:
        if not instrument_key:
            raise HTTPException(status_code=400, detail="Select an instrument from Upstox search.")
        if not instrument_key_pattern.fullmatch(instrument_key):
            raise HTTPException(status_code=400, detail="Provide a valid Upstox instrument key.")
        history = await historical_candles(
            instrument_key=instrument_key,
            unit=unit,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
        )
        candles = history["candles"]
        exchange = exchange or instrument_key.split("|", 1)[0]
    except HTTPException:
        raise
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Historical data contained malformed candle rows.") from exc

    try:
        return analyze_ema_alignment(
            candles, symbol=normalized_symbol, exchange=exchange or "", timeframe=timeframe
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Historical data contained malformed candle values.") from exc


market_sync_service = MarketSyncService(require_token)


class StrategyScanRequest(BaseModel):
    strategy_id: str
    timeframe: str = "1d"
    params: dict[str, Any] = Field(default_factory=dict)
    bypass_cache: bool = False


class CandleSyncRequest(BaseModel):
    unit: str = "days"
    interval: int = 1
    lookback_days: int = 730
    concurrency: int = 15


@app.get("/api/strategies")
async def get_available_strategies():
    """List all registered quantitative strategies with their configurable parameters."""
    return {"strategies": strategy_registry.list_strategies()}


@app.post("/api/strategies/scan")
async def scan_strategy(request: StrategyScanRequest):
    """Execute any strategy against the centralized multi-timeframe database with shared result caching."""
    require_token()
    try:
        return await strategy_registry.execute_scan(
            request.strategy_id,
            timeframe=request.timeframe,
            params=request.params,
            bypass_cache=request.bypass_cache,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/universe")
async def sync_universe():
    """Sync NSE cash equity universe master into central database."""
    require_token()
    count = await market_sync_service.sync_universe()
    return {"status": "success", "instruments_synced": count}


@app.post("/api/sync/candles")
async def sync_candles(request: CandleSyncRequest, background_tasks: BackgroundTasks):
    """Trigger delta synchronization of market candles in background."""
    require_token()
    # Run sync in background so HTTP response is returned immediately
    background_tasks.add_task(
        market_sync_service.sync_candles_for_universe,
        unit=request.unit,
        interval=request.interval,
        lookback_days=request.lookback_days,
        concurrency=request.concurrency,
    )
    return {
        "status": "sync_started",
        "message": f"Candle delta synchronization started for {request.unit}:{request.interval} in background.",
    }


@app.get("/api/scanner/universe")
async def scanner_universe():
    """Return the NSE cash-equity list from the cached Upstox instrument master."""
    instruments = await get_nse_equity_universe()
    stocks = sorted(instruments, key=lambda item: item["symbol"])
    return {"count": len(stocks), "stocks": stocks}


@app.get("/api/scanner/ema")
async def scanner_ema_alignment(
    unit: str = Query(default="days"),
    interval: int = Query(default=1, gt=0),
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
):
    """Scan NSE cash equities for bullish EMA 9/20/50/200 alignment with instant cached DB execution."""
    require_token()
    timeframe = map_timeframe(unit, interval)

    # Fast path: Vectorized scan from local/shared database with caching
    try:
        scan_output = await strategy_registry.execute_scan(
            "ema_sma_alignment",
            timeframe=timeframe,
            bypass_cache=False,
        )
        if scan_output.get("results") or scan_output.get("total_scanned", 0) > 0:
            return {
                "strategy": "CLOSE_ABOVE_EMA9_EMA20_SMA50_SMA200",
                "timeframe": timeframe,
                "scanned": scan_output.get("total_scanned", 0),
                "matched": scan_output.get("total_matched", 0),
                "results": scan_output.get("results", []),
                "cached": scan_output.get("cached", False),
                "errors": [],
            }
    except Exception as exc:
        print(f"Fast vectorized scan skipped to fallback: {exc}")

    # Fallback to direct Upstox scan if database has not been seeded yet
    instruments = await get_nse_equity_universe()

    async def fetch_history(key: str, candle_unit: str, candle_interval: int, start: date, end: date):
        return await historical_candles(
            instrument_key=key,
            unit=candle_unit,
            interval=candle_interval,
            from_date=start,
            to_date=end,
        )

    return await scan_ema_universe(
        instruments,
        fetch_history,
        unit=unit,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
        concurrency=10,
    )
