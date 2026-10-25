"""Selected-stock charts: stored history plus a temporary developing session."""
import asyncio
import hashlib
import math
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func
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
_last_request = 0.0


def parse_candles(rows, now):
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


async def provider_rows(key, unit, start, now, token):
    global _last_request
    base = 'https://api.upstox.com/v3/historical-candle'
    encoded = quote(key, safe='')
    yesterday = now.astimezone(INDIA).date()-timedelta(days=1)
    urls = []
    if start <= yesterday:
        urls.append(f'{base}/{encoded}/{unit}/1/{yesterday}/{start}')
    if unit == 'minutes' or now.astimezone(INDIA).hour >= 16:
        urls.append(f'{base}/intraday/{encoded}/{unit}/1')
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
            response = await client.get(url, headers={'Authorization': f'Bearer {token}'})
            response.raise_for_status()
            payload = response.json()
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
        stored = (await session.scalars(query.order_by(MarketCandle.timestamp))).all()
        daily_timestamps = list((await session.scalars(select(MarketCandle.timestamp).where(
            MarketCandle.instrument_id == instrument_id, MarketCandle.timeframe == '1d'))).all())
        last_minute = await session.scalar(select(func.max(MarketCandle.timestamp)).where(
            MarketCandle.instrument_id == instrument_id, MarketCandle.timeframe == '1m'))
    def utc(ts):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    rows = [dict(timestamp=utc(r.timestamp), **{k: float(getattr(r,k)) for k in ('open','high','low','close')}, volume=r.volume) for r in stored]
    daily_dates = {utc(ts).astimezone(INDIA).date() for ts in daily_timestamps}
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
                    start = today-timedelta(days=27)
                    if last_minute is not None:
                        start = max(start, utc(last_minute).astimezone(INDIA).date()-timedelta(days=2))
                    live = await provider_rows(instrument_key, 'minutes', start, now, token)
                    # Repair recent missed daily sessions without reloading the full DB history.
                    daily_start = max(today-timedelta(days=3650), max(daily_dates)-timedelta(days=2) if daily_dates else today-timedelta(days=27))
                    daily = await provider_rows(instrument_key, 'days', daily_start, now, token)
                    completed = [dict(r, instrument_key=instrument_key, timeframe='1m') for r in live if candle_closed(r['timestamp'], 'minutes', 1, now, 'NSE')]
                    # Existing daily rows may already be official BHAV values. Only fill gaps;
                    # the scheduled BHAV importer owns corrections to stored daily candles.
                    completed += [dict(r, instrument_key=instrument_key, timeframe='1d') for r in daily if r['timestamp'].astimezone(INDIA).date() not in daily_dates and candle_closed(r['timestamp'], 'days', 1, now, 'NSE')]
                    await upsert_candles(completed)
                    if len(_cache) >= 32:
                        _cache.pop(next(iter(_cache)))
                    _cache[cache_key] = (time.monotonic(), live, daily)
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                    live, daily = [], []
                    warning = 'Live candles unavailable. Showing stored history; reconnect Upstox or retry.'
        if timeframe == '1d':
            rows = daily + rows
            # A provider daily close takes precedence over an aggregate after market close.
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
    return dict(candles=[dict(r, timestamp=r['timestamp'].isoformat()) for r in chart], timeframe=timeframe,
                warning=warning, source='DB history + selected-stock Upstox candles' if token and not warning else 'Stored history',
                fetchedAt=now.isoformat())
