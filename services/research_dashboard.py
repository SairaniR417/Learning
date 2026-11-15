"""Read-only research screens from stored cash-equity candles.

No exchange participant identities, futures OI, IV history or fundamentals are
inferred from OHLCV. Pivot sources always precede the observation period.
"""
import asyncio
import calendar
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import DBAPIError
from database.candle_repo import load_recent_candles_polars
from scanner.universe import get_fno_stocks
from scanner.strategies.ghost_rider import ema
from scanner.strategies.institution_transaction import finished, pressure_view
from services.market_session import clean, utc
from services.market_sync import INDIA
from services.option_market import cache
from services.sutradhar import calculate as sutradhar, stored_session_open

router = APIRouter(prefix='/api/research', tags=['research'])


def bars(rows, frame, now):
    unique = {utc(r['timestamp']):dict(r,timestamp=utc(r['timestamp'])) for r in rows}
    complete = finished(sorted(unique.values(),key=lambda r:r['timestamp']),frame,now)
    # A bad candle breaks continuity rather than silently bridging a hole.
    invalid = max((i for i,r in enumerate(complete) if not clean(r)),default=-1)
    return complete[invalid+1:]


def period_start(stamp, period):
    d = utc(stamp).astimezone(INDIA).replace(hour=0,minute=0,second=0,microsecond=0)
    if period=='weekly': return d-timedelta(days=d.weekday())
    if period=='monthly': return d.replace(day=1)
    return d.replace(day=1,month=(d.month-1)//3*3+1)


def period_end(start, period):
    if period=='weekly': end = start+timedelta(days=4)
    else:
        month = start.month if period=='monthly' else start.month+2
        end = start.replace(month=month,day=calendar.monthrange(start.year,month)[1])
        while end.weekday()>4: end-=timedelta(days=1)
    return end.replace(hour=15,minute=30)


def aggregate(rows, period, now):
    grouped=defaultdict(list)
    for r in rows: grouped[period_start(r['timestamp'],period)].append(r)
    result=[]
    for start, group in sorted(grouped.items()):
        if period_end(start,period)>now: continue
        result.append(dict(timestamp=start,open=group[0]['open'],high=max(r['high'] for r in group),
                           low=min(r['low'] for r in group),close=group[-1]['close'],
                           volume=sum(r['volume'] for r in group),sourceAsOf=group[-1]['timestamp']))
    # A bounded history request can begin part-way through a period.
    return result[1:]


def trend(rows):
    if len(rows)<20: return dict(bias='UNAVAILABLE',bars=len(rows),ema20=None,asOf=rows[-1]['timestamp'].isoformat() if rows else None)
    average=ema([float(r['close']) for r in rows],20)[-1]
    close=rows[-1]['close']
    return dict(bias='BULLISH' if close>average else 'BEARISH' if close<average else 'NEUTRAL',bars=len(rows),ema20=average,asOf=rows[-1]['timestamp'].isoformat())


def pivots(source, price):
    if not source or price is None: return None
    h,l,c = (float(source[k]) for k in ('high','low','close'))
    pivot=(h+l+c)/3
    bc=(h+l)/2
    lower,upper=sorted((bc,2*pivot-bc))
    r=h-l
    position='ABOVE' if price>upper else 'BELOW' if price<lower else 'INSIDE'
    return dict(pivot=pivot,bc=lower,tc=upper,widthPct=(upper-lower)/pivot*100,
                narrow=(upper-lower)/pivot*100<=.25,position=position,
                r3=c+r*1.1/4,r4=c+r*1.1/2,s3=c-r*1.1/4,s4=c-r*1.1/2,
                camPosition='ABOVE R4' if price>c+r*1.1/2 else 'BELOW S4' if price<c-r*1.1/2 else 'INSIDE',
                sourceAt=source.get('sourceAsOf',source['timestamp']).isoformat())


def trendline(rows, side):
    key='low' if side=='support' else 'high'
    piv=[]
    for i in range(2,len(rows)-2):
        neighbors=rows[i-2:i]+rows[i+1:i+3]
        if all(rows[i][key]<r[key] if side=='support' else rows[i][key]>r[key] for r in neighbors): piv.append(i)
    if len(piv)<2: return None
    # Try the most recent pair first. Only confirmed pivots are anchors.
    for b in reversed(piv[-5:]):
        for a in reversed([i for i in piv if i<b][-5:]):
            slope=(rows[b][key]-rows[a][key])/(b-a)
            if side=='support' and slope<=0 or side=='resistance' and slope>=0: continue
            tolerance=mean(r['high']-r['low'] for r in rows[-14:])*.35
            line=lambda i: rows[a][key]+slope*(i-a)
            if any(rows[i][key]<line(i)-tolerance if side=='support' else rows[i][key]>line(i)+tolerance for i in range(a,len(rows))): continue
            touches=sum(abs(rows[i][key]-line(i))<=tolerance for i in piv if i>=a)
            return dict(side=side,touches=touches,points=[dict(timestamp=rows[i]['timestamp'].isoformat(),value=line(i)) for i in (a,len(rows)-1)],
                        value=line(len(rows)-1),note='Candidate line through two confirmed pivots; tolerance = 0.35 × mean 14-bar range. Not a guaranteed level.')
    return None


def serialize(rows, count=90):
    return [dict(timestamp=r['timestamp'].isoformat(),**{k:float(r[k]) for k in ('open','high','low','close','volume')}) for r in rows[-count:]]


def build_stock(meta, daily, hourly, now):
    daily,hourly=bars(daily,'1d',now),bars(hourly,'1h',now)
    weekly,monthly,quarterly=(aggregate(daily,p,now) for p in ('weekly','monthly','quarterly'))
    observation=hourly[-1] if hourly and (not daily or hourly[-1]['timestamp']>daily[-1]['timestamp']) else daily[-1] if daily else None
    price=observation['close'] if observation else None
    observed_day=observation['timestamp'].astimezone(INDIA).date() if observation else None
    # Daily source must be strictly before the observation session.
    prior=[r for r in daily if r['timestamp'].astimezone(INDIA).date()<observed_day] if observed_day else []
    levels={'daily':pivots(prior[-1] if prior else None,price)}
    for name,rows in [('weekly',weekly),('monthly',monthly)]:
        reference=[r for r in rows if observation and period_start(r['timestamp'],name)<period_start(observation['timestamp'],name)]
        levels[name]=pivots(reference[-1] if reference else None,price)
    sut=sutradhar(hourly[-1:],daily,60,session_opens=stored_session_open(hourly))['points'] if hourly else []
    sut=sut[-1] if sut else {}
    sut_ready=(sut.get('Flow') is not None and sut.get('Value') is not None and
               hourly[-1]['timestamp'].astimezone(INDIA).date()==observed_day)
    sut_position='ABOVE' if sut_ready and price>sut['Flow'] else 'BELOW' if sut_ready and price<sut['Value'] else 'INSIDE' if sut_ready else 'UNAVAILABLE'
    regimes={name:trend(rows) for name,rows in [('hourly',hourly),('daily',daily),('weekly',weekly),('monthly',monthly),('quarterly',quarterly)]}
    directional=[v['bias'] for name,v in regimes.items() if name in ('daily','weekly','monthly') and v['bias'] in ('BULLISH','BEARISH')]
    bias='BULLISH' if len(directional)>=2 and all(v=='BULLISH' for v in directional) else 'BEARISH' if len(directional)>=2 and all(v=='BEARISH' for v in directional) else 'MIXED' if directional else 'UNAVAILABLE'
    pressures={f:pressure_view(rows,f,now=now) for f,rows in [('1d',daily),('1h',hourly)]}
    latest=daily[-1] if daily else None
    change=(latest['close']/daily[-2]['close']-1)*100 if len(daily)>1 else None
    avgvol=mean(r['volume'] for r in daily[-21:-1]) if len(daily)>=21 else None
    old=bool(observation and now-observation['timestamp']>timedelta(days=4))
    return dict(**{k:meta.get(k,'') for k in ('key','symbol','name','exchange')},sector=meta.get('sector') or 'Unclassified',
                industry=meta.get('industry') or 'Unclassified',price=price,changePct=change,
                asOf=observation['timestamp'].isoformat() if observation else None,oldData=old,
                bias=bias,regimes=regimes,levels=levels,sutradhar=sut,sutradharPosition=sut_position,
                relativeVolume=latest['volume']/avgvol if latest and avgvol else None,pressure=pressures,
                charts={f:serialize(rows) for f,rows in [('daily',daily),('hourly',hourly),('weekly',weekly),('monthly',monthly)]},
                trendlines={f:[v for side in ('support','resistance') if (v:=trendline(rows[-90:],side))] for f,rows in [('weekly',weekly),('monthly',monthly)]},
                fundamentals=None,futuresOi=None,institutionalDisclosure='Not connected')


def build(stocks, daily_map, hourly_map, now):
    rows=[build_stock(s,daily_map.get(s['key'],[]),hourly_map.get(s['key'],[]),now) for s in stocks]
    sectors=defaultdict(list)
    for row in rows: sectors[row['sector']].append(row)
    sector_rows=[]
    for name,items in sorted(sectors.items()):
        available=[r for r in items if r['changePct'] is not None]
        changes=[r['changePct'] for r in available]
        sector_rows.append(dict(name=name,count=len(items),bullish=sum(r['bias']=='BULLISH' for r in items),bearish=sum(r['bias']=='BEARISH' for r in items),
                                changePct=mean(changes) if changes else None,coverage=len(available),
                                method='Equal-weight mean of latest stored daily close changes; not a sector index or money-flow measure.'))
    return dict(stocks=rows,sectors=sector_rows,fetchedAt=now.isoformat(),source='Stored cash-equity candles',
                availability=dict(institutional='Not connected',futuresOi='Not connected',ivHistory='Not connected',fundamentals='Not connected',participantPositioning='Not connected'),
                methodology='Trend: close versus EMA 20, minimum 20 completed candles per timeframe. Aligned bias requires at least two agreeing daily/weekly/monthly trends and no opposing available trend. CPR/Camarilla use a strictly preceding period. CPR narrow threshold: 0.25% of pivot. Hourly pressure is a price/volume proxy, not institutional identity. Aggregated periods exclude the first potentially partial period. No holiday calendar; old-data check is conservative after four calendar days.')


@router.get('/dashboard')
async def dashboard():
    async def load():
        daily,hourly=await asyncio.gather(load_recent_candles_polars('1d',per_instrument=800),load_recent_candles_polars('1h',per_instrument=500))
        def group(frame):
            return {str(g['instrument_key'][0]):g.sort('timestamp').to_dicts() for g in frame.partition_by('instrument_key')} if not frame.is_empty() else {}
        return await asyncio.to_thread(build,get_fno_stocks(),group(daily),group(hourly),datetime.now(timezone.utc))
    try: return await cache.get(('research-dashboard-v1',),30,load)
    except DBAPIError as exc: raise HTTPException(503,'Stored research data could not be read. Check the database and retry.') from exc
