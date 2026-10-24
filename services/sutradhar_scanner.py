# Derived from Sutradhar by © sairanir23, MPL-2.0; see docs/sutradhar.pine.
import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException
from scanner.universe import require_fno_key,get_fno_stocks
from services.ghost_scanner import load_stock_candles,completed_rows,TIMEFRAMES
from services.sutradhar import calculate,strategy_card,SutradharConfig,stored_session_open


async def stock_chart(key,timeframe='15m',settings=None):
    require_fno_key(key)
    if timeframe not in {'5m','15m','1h'}: raise HTTPException(400,'Sutradhar: Intraday charts only (5m, 15m or 1h stored candles).')
    try: config=SutradharConfig.resolve(settings)
    except (TypeError,ValueError) as exc: raise HTTPException(400,str(exc)) from exc
    frame=await load_stock_candles(key,timeframe)
    daily=await load_stock_candles(key,'1d')
    rows=completed_rows(frame.sort('timestamp').to_dicts(),timeframe) if not frame.is_empty() else []
    daily_rows=daily.sort('timestamp').to_dicts() if not daily.is_empty() else []
    overlay=await asyncio.to_thread(calculate,rows,daily_rows,TIMEFRAMES[timeframe],config,session_opens=stored_session_open(rows))
    stock=next(s for s in get_fno_stocks() if s['key']==key)
    return dict(contract=dict(key=key,name=stock['name'],underlyingKey=key,expiry='',strike=0,side='CE'),interval=TIMEFRAMES[timeframe],
        candles=[{**{k:v for k,v in r.items() if k!='instrument_key'},'timestamp':r['timestamp'].isoformat()} for r in rows],
        strategies=[strategy_card(overlay,len(rows))],sutradhar=overlay,
        underlying=dict(trend='UNAVAILABLE',supportsPremium=None,asOf=None,description='Sutradhar daily-open reference levels for this stock.'),warnings=[],
        historyMessage=f'{len(rows)} completed {timeframe} chart candles; {len(daily_rows)} daily source candles. Stored data only.',
        asOf=rows[-1]['timestamp'].isoformat() if rows else None,receivedAt=datetime.now(timezone.utc).isoformat())
