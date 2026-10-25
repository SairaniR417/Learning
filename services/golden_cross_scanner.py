"""Targeted chart with the same completed DB prefix used by the stock scan."""
import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException
from scanner.universe import require_fno_key, get_fno_stocks
from services.ghost_scanner import load_stock_candles, completed_rows, TIMEFRAMES
from services.golden_cross import resolve, calculate, strategy_card


async def stock_chart(key,timeframe='1d',settings=None):
    require_fno_key(key)
    if timeframe not in TIMEFRAMES: raise HTTPException(400,'Select daily, 1h, 15m or 5m stored candles.')
    try: config=resolve(settings)
    except (ValueError,TypeError) as exc: raise HTTPException(400,str(exc)) from exc
    frame=await load_stock_candles(key,timeframe)
    rows=completed_rows(frame.sort('timestamp').to_dicts(),timeframe) if not frame.is_empty() else []
    overlay=await asyncio.to_thread(calculate,rows,config)
    candles=[dict(r,timestamp=r['timestamp'].isoformat()) for r in rows]
    overlay['candles']=candles
    stock=next(s for s in get_fno_stocks() if s['key']==key)
    return dict(contract=dict(key=key,name=stock['name'],underlyingKey=key,expiry='',strike=0,side='CE'),interval=TIMEFRAMES[timeframe],
                candles=candles,strategies=[strategy_card(overlay,len(rows))],goldenCross=overlay,
                underlying=dict(trend='UNAVAILABLE',supportsPremium=None,asOf=None,description='Stored stock-price analysis.'),warnings=[],
                historyMessage=f'{len(rows)} completed {timeframe} candles. Counts depend on this loaded history.',
                asOf=candles[-1]['timestamp'] if candles else None,receivedAt=datetime.now(timezone.utc).isoformat())
