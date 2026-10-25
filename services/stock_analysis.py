from services import golden_cross
from services import suryavanshi
"""Shared stock/option strategy workspace, using selected-stock DB/live candles."""
import asyncio
from datetime import datetime, timedelta, timezone
from math import isfinite

from fastapi import HTTPException
from scanner.universe import require_fno_key, get_fno_stocks
from services import stock_chart, option_analysis, sutradhar
from services.market_sync import INDIA, nse_daily_closed
from services.ghost_rider_overlay import calculate as ghost_overlay, strategy_card as ghost_card
from services.rsi_overlay import calculate as rsi_overlay, strategy_card as rsi_card, RsiConfig

FRAMES = {1:'1m',5:'5m',15:'15m',30:'30m',60:'1h',1440:'1d',10080:'1w'}


async def analyze(key, timeframe='1d', atr_multiplier=1.5, rsi_settings=None, sutradhar_settings=None, suryavanshi_settings=None, golden_settings=None, stored_only=False):
    require_fno_key(key)
    if timeframe not in stock_chart.FRAMES or not isfinite(atr_multiplier) or atr_multiplier < .1:
        raise HTTPException(400,'Select a supported stock timeframe and ATR multiplier.')
    try:
        golden_config=golden_cross.resolve(golden_settings)
        sury_config=suryavanshi.Config.resolve(suryavanshi_settings)
        rsi_config=RsiConfig.resolve(rsi_settings)
        sutradhar_config=sutradhar.SutradharConfig.resolve(sutradhar_settings) if sutradhar_settings is not None else None
    except (ValueError,TypeError) as exc:
        raise HTTPException(400,str(exc)) from exc
    now=datetime.now(timezone.utc)
    interval=stock_chart.FRAMES[timeframe]
    loaded={}
    warnings=[]

    async def rows_for(frame):
        if frame in loaded:
            return loaded[frame]
        if frame=='1w':
            days=await rows_for('1d')
            rows=option_analysis.weekly_candles([r for r in days if not r['developing']])
            for row in rows:
                row['developing']=row['timestamp'].astimezone(INDIA).date()+timedelta(days=7)>now.astimezone(INDIA).date()
        else:
            if stored_only:
                from services.ghost_scanner import load_stock_candles
                data=await load_stock_candles(key,frame)
                response=dict(candles=[dict(r,timestamp=r['timestamp'].isoformat()) for r in data.sort('timestamp').to_dicts()] if not data.is_empty() else [],warning=None)
            else:
                response=await stock_chart.stock_chart(key,frame)
            if response.get('warning') and response['warning'] not in warnings:
                warnings.append(response['warning'])
            rows=[]
            for item in response['candles']:
                timestamp=datetime.fromisoformat(item['timestamp'])
                developing=bool(item.get('developing')) or (frame=='1d' and not nse_daily_closed(timestamp,now))
                rows.append(dict(item,timestamp=timestamp,instrument_key=key,developing=developing))
        loaded[frame]=rows
        return rows

    def plain(rows):
        return [{k:v for k,v in r.items() if k!='developing'} for r in rows]

    def serial(rows):
        return [dict(r,timestamp=r['timestamp'].isoformat()) for r in rows]

    all_rows=await rows_for(timeframe)
    candles=plain([r for r in all_rows if not r['developing']][-1000:])
    developing=plain(all_rows[-1000:])
    metadata=next(s for s in get_fno_stocks() if s['key']==key)
    contract=dict(instrument_key=key,trading_symbol=metadata['symbol'],name=metadata['name'],exchange='NSE')
    results=await asyncio.to_thread(option_analysis.evaluate,candles,contract,interval,stock=True,defer_overlays=True)
    five=plain((await rows_for('5m'))[-1000:])
    ghost=await asyncio.to_thread(ghost_overlay,developing,five,interval,atr_multiplier)
    ghost['candles']=serial(developing)
    ghost['developingBar']=any(r['developing'] for r in all_rows[-1:])
    rsi_frame=FRAMES[rsi_config.timeframe] if rsi_config.timeframe else timeframe
    rsi_rows=await rows_for(rsi_frame)
    rsi_rows=plain([r for r in rsi_rows if not r['developing'] or not rsi_config.wait_close][-1000:])
    rsi=await asyncio.to_thread(rsi_overlay,rsi_rows,rsi_config)
    rsi['interval']=rsi_config.timeframe or interval
    levels=None
    if sutradhar_config is not None:
        daily=plain(await rows_for('1d')) if interval<1440 else []
        levels=await asyncio.to_thread(sutradhar.calculate,developing,daily,interval,sutradhar_config,
                                       session_opens=sutradhar.stored_session_open(developing))
        levels['candles']=serial(developing)
    results=[ghost_card(ghost,len(developing)) if r['id']=='ghost_rider' else
             rsi_card(rsi,len(rsi_rows)) if r['id']=='rsi_divergence' else
             sutradhar.strategy_card(levels,len(developing)) if r['id']=='sutradhar' and levels is not None else r for r in results]
    sury_data=await asyncio.to_thread(suryavanshi.calculate,developing,sury_config)
    sury_data['candles']=serial(developing)
    results=[suryavanshi.strategy_card(sury_data,len(developing)) if r['id']=='suryavanshi' else r for r in results]
    golden_data=await asyncio.to_thread(golden_cross.calculate,candles,golden_config)
    golden_data['candles']=serial(candles)
    results=[golden_cross.strategy_card(golden_data,len(candles)) if r['id']=='golden_death_cross' else r for r in results]
    context=option_analysis.underlying_context(candles,'CE')
    context.update(supportsPremium=None,description='Stock close relative to EMA 20; strategy signals refer to the stock price.')
    if not five:
        warnings.append('5-minute history is unavailable; Ghost Rider 5m RSI remains n/a.')
    return dict(contract=dict(key=key,name=f"{metadata['symbol']} · {metadata['name']}",underlyingKey=key,expiry='',strike=0,side='CE'),
                interval=interval,candles=serial(candles),strategies=results,ghostRider=ghost,rsiDivergence=rsi,sutradhar=levels,suryavanshi=sury_data,goldenCross=golden_data,storedPreview=stored_only,
                underlying=context,warnings=warnings,asOf=candles[-1]['timestamp'].isoformat() if candles else None,
                receivedAt=now.isoformat(),historyMessage=f'{len(candles)} completed {timeframe} candles. '+('Stored history preview; current-session data is loading.' if stored_only else 'DB history plus selected-stock live data; developing bars are used only by Ghost Rider and explicitly configured overlays.'))
