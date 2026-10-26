"""Selected-stock charts: stored history plus a temporary developing session."""
import asyncio
import hashlib
import json
import math
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from database.connection import async_session_factory
from database.models import Instrument, MarketCandle, StockChartSelection
from database.candle_repo import upsert_candles, _insert_fn
from scanner.universe import require_fno_key
from services.market_sync import INDIA, candle_closed

router = APIRouter(prefix="/api/stocks")
get_token = lambda: None
FRAMES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}
_cache = {}
_history_cache = {}
_lock = asyncio.Lock()
_chart_slots = asyncio.Semaphore(4)
CHART_TIMEOUT_SECONDS = 45
_last_request = 0.0


def parse_candles(rows, now):
    if len(rows) > 2000:
        raise ValueError('Chart provider returned too many candles')
    result = {}
    for row in rows:
        ts = datetime.fromisoformat(row[0].replace("Z", "+00:00")).astimezone(timezone.utc)
        o, h, l, c = map(float, row[1:5])
        volume = int(row[5])
        if not all(math.isfinite(v) for v in (o, h, l, c)) or not 0 < l <= min(o, c) <= max(o, c) <= h or volume < 0:
            raise ValueError("Invalid provider OHLCV")
        if ts <= now:
            result[ts] = dict(timestamp=ts, open=o, high=h, low=l, close=c, volume=volume)
    return sorted(result.values(), key=lambda r: r['timestamp'])


def aggregate(rows, timeframe, now):
    """Anchor intraday buckets at 09:15 IST, including the short closing bucket."""
    buckets = {}
    for row in sorted(rows, key=lambda r: r['timestamp']):
        local = row['timestamp'].astimezone(INDIA)
        start = local.replace(hour=9, minute=15, second=0, microsecond=0)
        end = local.replace(hour=15, minute=30, second=0, microsecond=0)
        if not start <= local < end:
            continue
        minutes = FRAMES[timeframe]
        bucket = local.replace(hour=0, minute=0, second=0, microsecond=0) if timeframe == '1d' else start + timedelta(minutes=int((local-start).total_seconds() // (minutes*60))*minutes)
        ts = bucket.astimezone(timezone.utc)
        if ts not in buckets:
            buckets[ts] = dict(row, timestamp=ts)
        else:
            item = buckets[ts]
            item.update(high=max(item['high'], row['high']), low=min(item['low'], row['low']), close=row['close'], volume=item['volume']+row['volume'])
        closes = local.replace(hour=16, minute=0, second=0, microsecond=0) if timeframe == '1d' else min(bucket+timedelta(minutes=minutes), end)+timedelta(seconds=5)
        buckets[ts]['developing'] = now < closes
    return list(buckets.values())


async def provider_rows(key, unit, start, now, token, interval=1, include_today=True):
    global _last_request
    base = 'https://api.upstox.com/v3/historical-candle'
    encoded = quote(key, safe='')
    yesterday = now.astimezone(INDIA).date()-timedelta(days=1)
    urls = []
    if start <= yesterday:
        urls.append(f'{base}/{encoded}/{unit}/{interval}/{yesterday}/{start}')
    if include_today and (unit in {'minutes', 'hours'} or now.astimezone(INDIA).hour >= 16):
        urls.append(f'{base}/intraday/{encoded}/{unit}/{interval}')
    result = []
    async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
        for url in urls:
            history_key = (url, hashlib.sha256(token.encode()).hexdigest())
            historical = '/intraday/' not in url
            cached = _history_cache.get(history_key) if historical else None
            if cached and time.monotonic()-cached[0] < 900:
                result.extend(cached[1])
                continue
            await asyncio.sleep(max(0, 1.05-(time.monotonic()-_last_request)))
            _last_request = time.monotonic()
            async with client.stream('GET', url, headers={'Authorization': f'Bearer {token}'}) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    if len(body) + len(chunk) > 2 * 1024 * 1024:
                        raise ValueError('Chart provider response exceeds size limit')
                    body.extend(chunk)
                payload = json.loads(body)
            if payload.get('status') != 'success':
                raise ValueError('Provider history unavailable')
            parsed = parse_candles(payload['data']['candles'], now)
            if unit == 'days':
                parsed = [dict(r, timestamp=r['timestamp'].astimezone(INDIA).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)) for r in parsed]
            result.extend(parsed)
            if historical:
                if len(_history_cache) >= 64:
                    _history_cache.pop(next(iter(_history_cache)))
                _history_cache[history_key] = (time.monotonic(), parsed)
    return result


@router.get('/chart')
async def stock_chart(instrument_key: str, timeframe: str = '1d'):
    try:
        async with asyncio.timeout(CHART_TIMEOUT_SECONDS):
            async with _chart_slots:
                return await _stock_chart(instrument_key, timeframe)
    except TimeoutError:
        raise HTTPException(504, 'Chart request timed out. Please retry.')


async def _stock_chart(instrument_key: str, timeframe: str = '1d'):
    require_fno_key(instrument_key)
    if timeframe not in FRAMES:
        raise HTTPException(400, 'Unsupported chart timeframe')
    now = datetime.now(timezone.utc)
    today = now.astimezone(INDIA).date()
    source_frame = '1d' if timeframe == '1d' else '1m'
    async with async_session_factory() as session:
        instrument = await session.scalar(select(Instrument).where(Instrument.instrument_key == instrument_key))
        if instrument is None:
            raise HTTPException(404, 'Import the saved stock universe first.')
        instrument_id = instrument.id
        selection = _insert_fn()(StockChartSelection).values(instrument_id=instrument_id, last_viewed_at=now)
        await session.execute(selection.on_conflict_do_update(index_elements=['instrument_id'], set_={'last_viewed_at': now}))
        await session.commit()
        query = select(MarketCandle).where(MarketCandle.instrument_id == instrument_id, MarketCandle.timeframe == source_frame)
        if source_frame == '1m':
            query = query.where(MarketCandle.timestamp >= now-timedelta(days=28))
        stored = (await session.scalars(query.order_by(MarketCandle.timestamp.desc()).limit(20000))).all()
        native = []
        if timeframe != source_frame:
            native = (await session.scalars(select(MarketCandle).where(
                MarketCandle.instrument_id == instrument_id, MarketCandle.timeframe == timeframe)
                .order_by(MarketCandle.timestamp.desc()).limit(5000))).all()
    def utc(ts):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    stored.reverse()
    rows = [dict(timestamp=utc(r.timestamp), **{k: float(getattr(r,k)) for k in ('open','high','low','close')}, volume=r.volume) for r in stored]
    native_rows = [dict(timestamp=utc(r.timestamp), **{k: float(getattr(r,k)) for k in ('open','high','low','close')}, volume=r.volume) for r in native]
    history_warning = None
    warning = None
    try:
        token = get_token()
    except HTTPException:
        token = None
    if token:
        # One shared fetch across timeframe switches and concurrent viewers; bounded memory.
        cache_key = (instrument_key, hashlib.sha256(token.encode()).hexdigest())
        async with _lock:
            cached = _cache.get(cache_key)
            if cached and time.monotonic()-cached[0] < 55:
                live, daily = cached[1:]
            else:
                try:
                    # Historical candles come exclusively from the DB. Only today's
                    # session is requested from the provider, shared across timeframes.
                    async with asyncio.timeout(30):
                        live = await provider_rows(instrument_key, 'minutes', today, now, token)
                    daily = []
                    completed = [dict(r, instrument_key=instrument_key, timeframe='1m') for r in live if candle_closed(r['timestamp'], 'minutes', 1, now, 'NSE')]
                    await upsert_candles(completed)
                    if len(_cache) >= 32:
                        _cache.pop(next(iter(_cache)))
                    _cache[cache_key] = (time.monotonic(), live, daily)
                except (httpx.HTTPError, TimeoutError, ValueError, KeyError, IndexError, TypeError):
                    live, daily = [], []
                    warning = 'Live candles unavailable. Showing stored history; reconnect Upstox or retry.'
        # Hydrate only the selected timeframe if no historical candles are stored.
        # Each window stays below 2,000 bars; later opens reuse the persisted rows.
        if not any(r['timestamp'].astimezone(INDIA).date() < today for r in rows + native_rows):
            unit, interval, days = {'1m':('minutes',1,7), '5m':('minutes',5,20),
                '15m':('minutes',15,28), '30m':('minutes',30,89),
                '1h':('hours',1,89), '1d':('days',1,730)}[timeframe]
            try:
                async with _lock:
                    async with asyncio.timeout(15):
                        history = await provider_rows(instrument_key, unit, today-timedelta(days=days), now, token,
                                                      interval=interval, include_today=False)
                        history = [r for r in history if r['timestamp'].astimezone(INDIA).date() < today]
                        await upsert_candles([dict(r, instrument_key=instrument_key, timeframe=timeframe) for r in history])
                if timeframe == source_frame:
                    rows = history + rows
                else:
                    native_rows = history + native_rows
            except (httpx.HTTPError, TimeoutError, ValueError, KeyError, IndexError, TypeError):
                history_warning = 'Historical candles could not be loaded. Showing available stored and current-session data.'
        if timeframe == '1d':
            rows = daily + rows
            # Official stored daily candles take precedence over today's aggregate.
            if not any(r['timestamp'].astimezone(INDIA).date() == today for r in rows):
                rows += aggregate([r for r in live if r['timestamp'].astimezone(INDIA).date() == today], '1d', now)
        else:
            rows += live
    else:
        warning = 'Connect Upstox for current-session candles. Showing stored history.'
    # Daily timestamps normalize to IST midnight so BHAV and provider rows cannot duplicate a date.
    merged = {}
    for r in rows:
        ts = r['timestamp']
        if timeframe == '1d':
            ts = ts.astimezone(INDIA).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        merged[ts] = dict(r, timestamp=ts)
    chart = sorted(merged.values(), key=lambda r:r['timestamp'])
    if timeframe != '1d':
        chart = aggregate(chart, timeframe, now)
        if native_rows:
            # Keep complete stored bars when minute history covers only part of an old bucket.
            combined = {r['timestamp']: dict(r, developing=False) for r in native_rows}
            for row in chart:
                if row['timestamp'].astimezone(INDIA).date() == today:
                    combined[row['timestamp']] = row
                else:
                    combined.setdefault(row['timestamp'], row)
            chart = sorted(combined.values(), key=lambda row: row['timestamp'])[-5000:]
    return dict(candles=[dict(r, timestamp=r['timestamp'].isoformat()) for r in chart], timeframe=timeframe,
                staleData=bool(warning), dataAsOf=chart[-1]['timestamp'].isoformat() if chart else None,
                historyWarning=history_warning, warning=warning, source='DB history + selected-stock Upstox candles' if token and not warning else 'Stored history',
                fetchedAt=now.isoformat())
