"""Stored stock history and dated news; independent of broker authentication."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse
import xml.etree.ElementTree as ET

import httpx
from sqlalchemy import select, func
from fastapi import APIRouter, Query, HTTPException
from database.connection import async_session_factory
from database.models import Instrument, MarketCandle

router = APIRouter(prefix="/api/stocks")
_news_cache = {}


@router.get("/history")
async def stock_history(instrument_key: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    async with async_session_factory() as session:
        instrument = await session.scalar(select(Instrument).where(Instrument.instrument_key == instrument_key))
        if instrument is None:
            raise HTTPException(404, "This instrument has not been imported into the local database.")
        condition = (MarketCandle.instrument_id == instrument.id, MarketCandle.timeframe == "1d")
        count, earliest, latest, high, low, volume = (await session.execute(select(
            func.count(), func.min(MarketCandle.timestamp), func.max(MarketCandle.timestamp),
            func.max(MarketCandle.high), func.min(MarketCandle.low), func.sum(MarketCandle.volume)
        ).where(*condition))).one()
        rows = (await session.scalars(select(MarketCandle).where(*condition).order_by(
            MarketCandle.timestamp.desc()).offset((page - 1) * page_size).limit(page_size))).all()
        chart = (await session.scalars(select(MarketCandle).where(*condition)
                    .order_by(MarketCandle.timestamp))).all() if page == 1 else []
        def candle(row):
            return {"timestamp": row.timestamp.isoformat(), **{key: float(getattr(row, key)) for key in ("open", "high", "low", "close")}, "volume": row.volume}
        return {"total": count, "page": page, "pageSize": page_size,
                "earliest": earliest.isoformat() if earliest else None, "latest": latest.isoformat() if latest else None,
                "high": float(high) if high is not None else None, "low": float(low) if low is not None else None,
                "totalVolume": volume or 0, "candles": [candle(row) for row in rows],
                "chart": [candle(row) for row in chart],
                "source": "Stored daily candles", "addedAt": None}


def parse_news(payload: bytes):
    items = []
    for item in ET.fromstring(payload).findall("./channel/item")[:20]:
        url = item.findtext("link", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "news.google.com":
            continue
        items.append({"title": item.findtext("title", ""), "url": url,
                      "publishedAt": item.findtext("pubDate", ""), "source": item.findtext("source", "")})
    return items


@router.get("/news")
async def stock_news(symbol: str = Query(min_length=1, max_length=100), name: str = Query("", max_length=200)):
    query = f'"{name or symbol}" "{symbol}" stock India'
    now = datetime.now(timezone.utc)
    cached = _news_cache.get(query)
    if cached and cached[0] > now:
        return cached[1]
    url = "https://news.google.com/rss/search?" + urlencode({"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(url)
            response.raise_for_status()
        result = {"items": parse_news(response.content), "fetchedAt": now.isoformat(), "source": "Google News RSS"}
    except (httpx.HTTPError, ET.ParseError):
        raise HTTPException(502, "News is temporarily unavailable. Please retry.")
    if len(_news_cache) >= 256:
        _news_cache.clear()
    _news_cache[query] = (now + timedelta(minutes=15), result)
    return result
