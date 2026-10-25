"""Five-indicator decision support. Plans are rules, not calibrated forecasts."""
import asyncio
from datetime import datetime,timedelta,timezone,time as daytime
from math import isfinite
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter,HTTPException
from database.candle_repo import get_all_active_instruments,get_candle_revision,load_recent_candles_polars
from scanner.universe import require_fno_key
from services import golden_cross,suryavanshi,sutradhar
from services.ghost_rider_overlay import calculate as ghost_calculate
from services.rsi_overlay import calculate as rsi_calculate
from services.ghost_scanner import completed_rows
from services.market_sync import INDIA,nse_daily_closed
from services.option_market import SharedCache

router=APIRouter(prefix='/api/focused/plans',tags=['Focused plans'])
NAMES={'ghost_rider':'Ghost Rider','rsi_divergence':'RSI Divergence','sutradhar':'Sutradhar','suryavanshi':'Suryavanshi','golden_death_cross':'Golden / Death Cross'}
MODES={'intraday':('15m',15,8),'swing':('1h',60,35)}
_cache=SharedCache(capacity=4)
_jobs={}
_tasks={}


def utc(value):
    d=datetime.fromisoformat(value) if isinstance(value,str) else value
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def gate(row,now=None):
    """Re-evaluate at delivery, including cached plans; never promote stale levels."""
    now=(now or datetime.now(timezone.utc)).astimezone(INDIA)
    reasons=list(row.get('blockers',[]))
    if now.weekday()>4 or not daytime(9,15)<=now.time().replace(tzinfo=None)<daytime(15,20):
        reasons.append('Market closed: refresh during the next session before entering.')
    elif row['mode']=='intraday' and now.time().replace(tzinfo=None)>=daytime(15,0):
        reasons.append('New intraday entries stop at 15:00 IST; exit by 15:20.')
    if not row.get('asOf') or utc(row['asOf']).astimezone(INDIA).date()!=now.date() or now.astimezone(timezone.utc)>utc(row['validUntil']):
        reasons.append('Execution candles are stale. Refresh this stock before entering.')
    if row['mode']=='swing' and row['direction']=='SELL' and row.get('instrumentType','STOCK')=='STOCK':
        reasons.append('Bearish swing: check a PUT contract; do not carry an intraday cash short overnight.')
    row=dict(row,action='WAIT' if reasons else row['direction'],waitReasons=reasons)
    row['decision']=('WAIT — '+reasons[0]) if reasons else f"{row['direction']} setup: enter only near the reference entry; exit on stop or invalidation."
    return row


def evidence(rows,daily,five,interval,now):
    g=ghost_calculate(rows,five,interval)
    r=rsi_calculate(rows)
    s=suryavanshi.calculate(rows)
    levels=sutradhar.calculate(rows,daily,interval,session_opens=sutradhar.stored_session_open(rows))
    cross=golden_cross.calculate(daily)
    out=[];drivers={};n=len(rows);last=rows[-1]['close']
    def add(key,direction,state,reason,at=None):
        out.append(dict(id=key,name=NAMES[key],direction=direction,state=state,reason=reason,asOf=at))
    setup=g['setup']
    if setup and n-1-setup['index']<=5 and setup['stopLoss'] is not None:
        long=setup['signal']=='BUY';stop=setup['stopLoss']
        touched=any(x['low']<=stop if long else x['high']>=stop for x in rows[setup['index']:])
        valid=not touched and not setup['targets'][0]['hit']
        add('ghost_rider',setup['signal'] if valid else None,'ACTIVE' if valid else 'INVALIDATED',
            'Fresh EMA 9/21 setup; stop and first target untouched.' if valid else 'Original stop or first target touched; do not chase this entry.',setup['signalAt'])
        if valid: drivers['ghost_rider']=dict(direction=setup['signal'],entry=setup['entry'],stop=stop,index=setup['index'])
    else: add('ghost_rider',None,'NO_FRESH_SETUP','No usable Ghost Rider entry within five completed execution bars.')
    event=r['events'][-1] if r['events'] else None
    if event and n-1-event['detectedIndex']<=10:
        direction='BUY' if event['direction']=='BULLISH' else 'SELL'
        invalid=last<event['pivot2Price'] if direction=='BUY' else last>event['pivot2Price']
        add('rsi_divergence',None if invalid else direction,'INVALIDATED' if invalid else 'CONFIRMED',
            'Regular divergence confirmed five bars after its pivot; supporting evidence, not an entry by itself.',event['detectedAt'])
    else: add('rsi_divergence',None,'NO_FRESH_SETUP','No regular divergence confirmed within ten execution bars.')
    trade=s['activeTrade']
    if trade and trade['sl'] is not None and n-1-trade['index']<=5:
        direction='BUY' if trade['direction']=='long' else 'SELL'
        add('suryavanshi',direction,'ACTIVE','Active structure-break trade; source stop and target have not exited.',trade['timestamp'])
        drivers['suryavanshi']=dict(direction=direction,entry=trade['entry'],stop=trade['sl'],index=trade['index'])
    else: add('suryavanshi',None,'NO_FRESH_SETUP','No active Suryavanshi entry within five execution bars.')
    point=cross['points'][-1] if cross['points'] else None
    if point and point['sma50'] is not None and point['sma200'] is not None and point['sma50']!=point['sma200']:
        direction='BUY' if point['sma50']>point['sma200'] else 'SELL'
        add('golden_death_cross',direction,'DAILY_TREND','Daily SMA 50 is '+('above' if direction=='BUY' else 'below')+' SMA 200. Trend context; this does not mean a new cross today.',point['timestamp'])
    else: add('golden_death_cross',None,'UNAVAILABLE','At least 200 completed daily candles are needed for trend context.')
    level=levels['points'][-1] if levels['status']=='LEVELS_READY' else None
    add('sutradhar',None,levels['status'],'Daily-open reference levels locate nearby support/resistance; not an independent Buy/Sell vote.',rows[-1]['timestamp'].isoformat())
    return out,drivers,level


def build_plan(rows,daily,five,meta,mode='intraday',now=None,computed=None,instrument_type='STOCK'):
    now=now or datetime.now(timezone.utc)
    frame,interval,maxbars=MODES[mode]
    checks,drivers,levels=computed or evidence(rows,daily,five,interval,now)
    last=rows[-1];entry=float(last['close']);blockers=[]
    if not daily or now-utc(daily[-1]['timestamp'])>timedelta(days=7): blockers.append('Daily trend history is stale; refresh daily candles first.')
    buy=[v for v in checks if v['direction']=='BUY'];sell=[v for v in checks if v['direction']=='SELL']
    direction='BUY' if len(buy)>=len(sell) else 'SELL';agree=buy if direction=='BUY' else sell;opposing=sell if direction=='BUY' else buy
    if len(agree)<3: blockers.append('Need at least three of four directional indicators to agree.')
    if opposing: blockers.append('Directional indicators conflict; wait for alignment.')
    driver=next((drivers[k] for k in ('suryavanshi','ghost_rider') if k in drivers and drivers[k]['direction']==direction),None)
    if driver is None: blockers.append('No fresh Ghost Rider or Suryavanshi entry with an untouched stop.')
    if levels is None: blockers.append('Sutradhar levels unavailable; daily or execution history is incomplete.')
    elif (direction=='BUY' and entry<=levels['O']) or (direction=='SELL' and entry>=levels['O']):
        blockers.append('Price is on the wrong side of the Sutradhar daily open.')
    plan=None
    if driver is not None:
        stop=float(driver['stop']);sign=1 if direction=='BUY' else -1;risk=sign*(entry-stop)
        from scanner.strategies.ghost_rider import atr14
        atr=atr14(rows)[-1]
        if not atr or abs(entry-driver['entry'])>.5*atr: blockers.append('Price has moved more than 0.5 ATR from the entry signal; do not chase.')
        maxrisk=(.35 if mode=='intraday' else .50) if instrument_type=='OPTION' else (.03 if mode=='intraday' else .12)
        if risk<=0 or stop<=0 or risk/entry>maxrisk: blockers.append('Source stop is invalid or too far from this entry.')
        else:
            t1=entry+sign*2*risk;t2=entry+sign*3*risk
            obstacles=sorted({float(levels[k]) for k in ('Flow','Crest','Crown','Value','Base','Origin') if levels and sign*(float(levels[k])-entry)>0},reverse=direction=='SELL')
            if obstacles and sign*(obstacles[0]-t1)<0: t1=obstacles[0]
            rr=sign*(t1-entry)/risk
            if rr<1.5: blockers.append('Nearest Sutradhar barrier leaves less than 1.5R to the first target.')
            if t1<=0 or t2<=0: blockers.append('Target prices are invalid.')
            plan=dict(entry=round(entry,2),stopLoss=round(stop,2),target1=round(t1,2),target2=round(t2,2),riskPerUnit=round(risk,2),riskPct=round(risk/entry*100,2),rewardRisk=round(rr,2),
                entryMin=round(entry-.1*risk,2),entryMax=round(entry+.1*risk,2),
                basis='Source stop from '+('Suryavanshi' if 'suryavanshi' in drivers and drivers['suryavanshi'] is driver else 'Ghost Rider')+'. T1: nearer of 2R or the next Sutradhar barrier; T2: 3R projection. Recalculate if entry changes.')
    # A fresh intraday candle proves an actual session. Weekdays alone never prove a holiday is open.
    asof=utc(last['timestamp']);valid=asof+timedelta(minutes=interval*2,seconds=5)
    holding=('Review every 15 minutes; maximum 8 bars (2 hours) from entry. Exit by 15:20 IST.' if mode=='intraday' else 'Review every hour; maximum 5 trading sessions from entry.')
    exit_rule='Exit earlier at stop, target, an opposite execution signal, or loss of the Sutradhar daily open. After T1, protect remaining units at entry; no averaging down.'
    description=f"{len(agree)}/4 directional indicators support {'strength' if direction=='BUY' else 'weakness'}; "+('price is above' if levels and entry>levels['O'] else 'price is below' if levels else 'waiting for')+' the daily-open reference.'
    row=dict(instrumentKey=meta['key'],symbol=meta['symbol'],name=meta.get('name',meta['symbol']),instrumentType=instrument_type,mode=mode,timeframe=frame,direction=direction,
             action='WAIT',score=len(agree),maxScore=4,evidence=checks,blockers=blockers,qualified=not blockers,asOf=asof.isoformat(),validUntil=valid.isoformat(),
             close=entry,whatHappening=description,plan=plan,holding=holding,maxHoldingBars=maxbars,exitRule=exit_rule,
             liquidity=meta.get('liquidity',0),optionSide='CE' if direction=='BUY' else 'PE')
    return gate(row,now)


def analyze_snapshot(execution,daily,five,meta,mode,progress=None,now=None):
    now=now or datetime.now(timezone.utc);frame,interval,_=MODES[mode]
    def groups(df,tf):
        if df.is_empty(): return {}
        return {g['instrument_key'][0]:completed_rows(g.sort('timestamp').to_dicts(),tf,now) for g in df.partition_by('instrument_key')}
    eg,dg,fg=groups(execution,frame),groups(daily,'1d'),groups(five,'5m')
    rows=[];coverage=dict(total=len(meta),executionHistory=0,dailyHistory=0,liquidity=0)
    for i,(key,m) in enumerate(meta.items()):
        if progress and i%20==0: progress(f'Combining five indicators: {i+1}/{len(meta)} stocks')
        e,d=eg.get(key,[]),dg.get(key,[])
        if len(e)<60: coverage['executionHistory']+=1;continue
        if len(d)<200: coverage['dailyHistory']+=1;continue
        turnover=sum(float(r['close'])*float(r.get('volume') or 0) for r in d[-20:])/20
        if turnover<10_000_000 or e[-1]['close']<20 or not e[-1].get('volume'): coverage['liquidity']+=1;continue
        row=build_plan(e,d,fg.get(key,[]),dict(m,key=key,liquidity=turnover),mode,now)
        rows.append(row)
    rows.sort(key=lambda r:(r['action']=='WAIT',not r['qualified'],-r['score'],-r['liquidity'],r['symbol']))
    return dict(mode=mode,timeframe=frame,plans=rows,coverage=coverage,strategies=list(NAMES.values()),scannedAt=now.isoformat(),
                methodology='Three of four directional checks, a fresh source entry, no opposing direction, Sutradhar level validation and at least 1.5R. All five indicators are evaluated. Scores are agreement counts, not win probabilities.',
                policy='Rule-based, unvalidated trade plans. Holding windows are maximum review limits, not predictions. Levels exclude fees/slippage. WAIT means no new entry. SELL stock setups apply to held shares or permitted intraday shorts; option purchases use separate premium levels.')


async def scan(mode,progress=None):
    frame=MODES[mode][0]
    revisions=tuple(await asyncio.gather(*(get_candle_revision(f) for f in ('1d',frame,'5m'))))
    async def load():
        meta={i['key']:i for i in await get_all_active_instruments() if i.get('exchange')=='NSE'}
        if progress: progress('Reading stored daily, execution and 5-minute history')
        daily,execution,five=await asyncio.gather(*(load_recent_candles_polars(f,per_instrument=1000) for f in ('1d',frame,'5m')))
        return await asyncio.to_thread(analyze_snapshot,execution,daily,five,meta,mode,progress)
    result=await _cache.get(('five-plan-v1',mode,revisions),45,load)
    return dict(result,plans=[gate(r) for r in result['plans']])


async def run_job(job_id,mode):
    job=_jobs[job_id]
    try:
        def progress(stage): job['stage']=stage
        async with asyncio.timeout(240): result=await scan(mode,progress)
        job.update(status='complete',stage='Trade plans ready',result=result)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Focused five-indicator scan failed')
        job.update(status='failed',stage='Scan stopped',error='Could not build complete trade plans. Check stored history and retry.')


@router.post('/jobs')
async def start_job(mode:Literal['intraday','swing']='intraday'):
    task=_tasks.get(mode)
    if task and not task[1].done(): return dict(id=task[0])
    while len(_jobs)>=12:
        finished=next((k for k,v in _jobs.items() if v['status']!='running'),None)
        if finished is None: break
        del _jobs[finished]
    job_id=uuid4().hex
    _jobs[job_id]=dict(id=job_id,status='running',stage='Preparing five-indicator scan',result=None,error='')
    task=asyncio.create_task(run_job(job_id,mode));_tasks[mode]=(job_id,task)
    return dict(id=job_id)


@router.get('/jobs/{job_id}')
async def job_status(job_id:str):
    job=_jobs.get(job_id)
    if job is None: raise HTTPException(404,'Scan expired. Refresh Focused.')
    if job['result']:
        return dict(job,result=dict(job['result'],plans=[gate(r) for r in job['result']['plans']]))
    return job
