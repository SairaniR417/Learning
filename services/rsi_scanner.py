"""Targeted stored-stock chart for the shared Pine RSI engine."""
import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException
from scanner.universe import require_fno_key, get_fno_stocks
from services.ghost_scanner import load_stock_candles, completed_rows, TIMEFRAMES
from services.rsi_overlay import RsiConfig, calculate, strategy_card


async def stock_chart(key,timeframe='1d',settings=None):
    require_fno_key(key)
    if timeframe not in TIMEFRAMES: raise HTTPException(400,'Select stored daily, 1h, 15m or 5m candles.')
    try: config=RsiConfig.resolve(settings)
    except (TypeError,ValueError) as exc: raise HTTPException(400,str(exc)) from exc
    frame=await load_stock_candles(key,timeframe)
    rows=completed_rows(frame.sort('timestamp').to_dicts(),timeframe) if not frame.is_empty() else []
    indicator_interval=config.timeframe or TIMEFRAMES[timeframe]
    indicator_frame={5:'5m',15:'15m',60:'1h',1440:'1d',10080:'1d'}[indicator_interval]
    source=frame if indicator_frame==timeframe else await load_stock_candles(key,indicator_frame)
    raw=source.sort('timestamp').to_dicts() if not source.is_empty() else []
    now=datetime.now(timezone.utc)
    for row in raw:
        if row['timestamp'].tzinfo is None: row['timestamp']=row['timestamp'].replace(tzinfo=timezone.utc)
    raw=[r for r in raw if r['timestamp']<=now]
    selected=completed_rows(raw,indicator_frame,now) if config.wait_close else raw
    if indicator_interval==10080:
        from services.option_analysis import weekly_candles
        selected=weekly_candles(selected)
        if config.wait_close:
            from datetime import timedelta
            selected=[r for r in selected if r['timestamp']+timedelta(days=7)<=now]
    overlay=await asyncio.to_thread(calculate,selected,config)
    overlay['interval']=indicator_interval
    stock=next(s for s in get_fno_stocks() if s['key']==key)
    return dict(contract=dict(key=key,name=stock['name'],underlyingKey=key,expiry='',strike=0,side='CE'),interval=TIMEFRAMES[timeframe],
        candles=[{**{k:v for k,v in r.items() if k!='instrument_key'},'timestamp':r['timestamp'].isoformat()} for r in rows],
        strategies=[strategy_card(overlay,len(selected))],rsiDivergence=overlay,
        underlying=dict(trend='UNAVAILABLE',supportsPremium=None,asOf=None,description='Stored stock-price RSI analysis.'),warnings=[],
        historyMessage=f'{len(rows)} completed {timeframe} price candles; {len(selected)} RSI calculation candles. No broker requests.',
        asOf=rows[-1]['timestamp'].isoformat() if rows else None,receivedAt=now.isoformat())
