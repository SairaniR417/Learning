"""Stored-stock Ghost Rider scans and charts share the supplied Pine engine."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
import polars as pl
from sqlalchemy import select
from database.connection import async_session_factory
from database.models import Instrument, MarketCandle
from scanner.universe import get_fno_stocks, require_fno_key
from services.ghost_rider_overlay import calculate, strategy_card
from services.market_sync import nse_daily_closed

TIMEFRAMES = {'1d': 1440, '1h': 60, '15m': 15, '5m': 5}


async def load_stock_candles(key, timeframe):
    query = (select(MarketCandle).join(Instrument,MarketCandle.instrument_id==Instrument.id)
             .where(Instrument.provider_instrument_key==key,Instrument.is_active.is_(True),MarketCandle.timeframe==timeframe)
             .order_by(MarketCandle.candle_time.desc()).limit(1000))
    async with async_session_factory() as session:
        records = (await session.scalars(query)).all()
    return pl.DataFrame([dict(instrument_key=key,timestamp=r.candle_time,
        **{field:float(getattr(r,field)) for field in ('open','high','low','close')},volume=r.volume) for r in reversed(records)])


def completed_rows(rows, timeframe, now=None):
    now = now or datetime.now(timezone.utc)
    interval = TIMEFRAMES[timeframe]
    result = []
    for row in rows:
        row = dict(row)
        timestamp = row['timestamp']
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        row['timestamp'] = timestamp
        if (nse_daily_closed(timestamp, now) if timeframe == '1d' else timestamp+timedelta(minutes=interval, seconds=5) <= now):
            result.append(row)
    return result[-1000:]


def scan_row(rows, five, metadata, timeframe, multiplier):
    overlay = calculate(rows, five, TIMEFRAMES[timeframe], multiplier)
    setup = overlay['setup']
    if not setup:
        return None
    latest = overlay['points'][-1]
    table = {r['title']: r['value'] for r in overlay['dashboard']}
    state = table['Status']
    # Stop touch is evidence only; it never cancels the Pine setup.
    after = rows[setup['index']:]
    stop = setup['stopLoss']
    stopped = stop is not None and any(r['low'] <= stop if setup['signal'] == 'BUY' else r['high'] >= stop for r in after)
    from scanner.strategies.ghost_rider import atr14
    atr = atr14(rows)
    result = dict(instrumentKey=rows[-1]['instrument_key'], symbol=metadata.get('symbol', ''), name=metadata.get('name', ''), exchange=metadata.get('exchange','NSE'),
                  entry=setup['entry'], stopLoss=stop, risk=setup['risk'], signal=setup['signal'], status=setup['signal'], state=state,
                  signalAt=setup['signalAt'], ageBars=len(rows)-1-setup['index'], close=rows[-1]['close'], volume=rows[-1]['volume'],
                  changePct=(rows[-1]['close']/rows[-2]['close']-1)*100 if len(rows)>1 else None,
                  stopTouched=stopped, atrAtSignal=atr[setup['index']], atr=atr[-1], ema9=latest['ema9'], ema21=latest['ema21'],
                  asOf=rows[-1]['timestamp'].isoformat(), candlesAnalyzed=len(rows), strategyId='ghost_rider',
                  bullPct=float(table['Pullers'].rstrip('%')), bearPct=float(table['Draggers'].rstrip('%')), bias=table['BIAS'],
                  rsi5m=None if table['5m RSI']=='n/a' else float(table['5m RSI']), dashboard=overlay['dashboard'])
    for target in setup['targets']:
        result[f"tp{target['number']}"] = target['price']
        result[f"tp{target['number']}Hit"] = target['hit']
    return result


async def stock_chart(key, timeframe='1d', multiplier=1.5):
    require_fno_key(key)
    if timeframe not in TIMEFRAMES:
        raise HTTPException(400, 'Ghost Rider supports daily, 1h, 15m and 5m stored candles.')
    # Targeted lookup avoids loading the whole universe when opening one chart.
    frame = await load_stock_candles(key,timeframe)
    five_frame = frame if timeframe=='5m' else await load_stock_candles(key,'5m')
    rows = completed_rows(frame.sort('timestamp').to_dicts(),timeframe) if not frame.is_empty() else []
    five = completed_rows(five_frame.sort('timestamp').to_dicts(),'5m') if not five_frame.is_empty() else []
    overlay = await asyncio.to_thread(calculate,rows,five,TIMEFRAMES[timeframe],multiplier)
    stock = next(s for s in get_fno_stocks() if s['key']==key)
    strategy = strategy_card(overlay,len(rows))
    if not rows:
        strategy['scenario']='No stored candles for this timeframe. Import or sync this timeframe first.'
    return dict(contract=dict(key=key,name=stock['name'],underlyingKey=key,expiry='',strike=0,side='CE'), interval=TIMEFRAMES[timeframe],
                candles=[{**{k:v for k,v in r.items() if k!='instrument_key'},'timestamp':r['timestamp'].isoformat()} for r in rows],
                strategies=[strategy],ghostRider=overlay,
                underlying=dict(trend=next((r['value'] for r in overlay['dashboard'] if r['title']=='BIAS'),'UNAVAILABLE'),supportsPremium=None,
                    description='Stored stock-price analysis. Dashboard votes do not filter crossover entries.',asOf=rows[-1]['timestamp'].isoformat() if rows else None),
                warnings=['5-minute RSI is n/a when corresponding stored 5m history is unavailable.'] if not five else [],
                historyMessage=f'{len(rows)} stored completed {timeframe} candles. No broker requests are made.',
                asOf=rows[-1]['timestamp'].isoformat() if rows else None,receivedAt=datetime.now(timezone.utc).isoformat())
