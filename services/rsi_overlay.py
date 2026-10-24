"""Port of docs/rsi-divergence.pine. All live RSI Divergence views use this engine."""
from dataclasses import dataclass, asdict
from math import isfinite, sqrt

SOURCES = ('close','open','high','low','hl2','hlc3','ohlc4','hlcc4')
MA_TYPES = ('None','SMA','SMA + Bollinger Bands','EMA','SMMA (RMA)','WMA','VWMA')


@dataclass(frozen=True)
class RsiConfig:
    period: int = 14
    source: str = 'close'
    calculate_divergence: bool = True  # Application preset matches the supplied screenshot.
    ma_type: str = 'SMA'
    ma_length: int = 14
    bb_mult: float = 2.0
    timeframe: int = 0
    wait_close: bool = True

    @classmethod
    def resolve(cls, params=None):
        params = params or {}
        if set(params)-set(cls.__dataclass_fields__):
            raise ValueError('Unknown RSI setting.')
        c=cls(**params)
        for name in ('period','ma_length'):
            if type(getattr(c,name)) is not int or not 1<=getattr(c,name)<=1000:
                raise ValueError('RSI and smoothing lengths must be integers from 1 to 1000.')
        if c.source not in SOURCES or c.ma_type not in MA_TYPES:
            raise ValueError('Unsupported RSI source or smoothing type.')
        if type(c.calculate_divergence) is not bool or type(c.wait_close) is not bool:
            raise ValueError('RSI switches must be boolean.')
        if type(c.timeframe) is not int or c.timeframe not in (0,5,15,60,1440,10080):
            raise ValueError('Select Chart, 5m, 15m, 1h, 1d or 1w RSI calculation timeframe.')
        if isinstance(c.bb_mult,bool) or not isinstance(c.bb_mult,(int,float)) or not isfinite(c.bb_mult) or not .001<=c.bb_mult<=50:
            raise ValueError('BB StdDev must be between 0.001 and 50.')
        return c


def source_value(row,source):
    if source in ('close','open','high','low'): return row[source]
    if source=='hl2': return (row['high']+row['low'])/2
    if source=='hlc3': return (row['high']+row['low']+row['close'])/3
    if source=='hlcc4': return (row['high']+row['low']+2*row['close'])/4
    return sum(row[k] for k in ('open','high','low','close'))/4


def rma(values,length):
    result=[]; seed=[]; previous=None
    for value in values:
        if value is not None:
            if previous is None:
                seed.append(value)
                if len(seed)==length: previous=sum(seed)/length
            else: previous=(previous*(length-1)+value)/length
        result.append(previous)
    return result


def pine_rsi(values,length):
    changes=[None]+[values[i]-values[i-1] for i in range(1,len(values))] if values else []
    up=rma([None if v is None else max(v,0) for v in changes],length)
    down=rma([None if v is None else max(-v,0) for v in changes],length)
    # Pine tests down==0 first: a flat warmed-up series is 100, not 50.
    return [None if u is None or d is None else 100.0 if d==0 else 0.0 if u==0 else 100-100/(1+u/d) for u,d in zip(up,down)]


def smoothing(values,volumes,c):
    if c.ma_type=='None': return [None]*len(values)
    if c.ma_type=='SMMA (RMA)': return rma(values,c.ma_length)
    result=[]; window=[]; previous=None
    for i,value in enumerate(values):
        if value is None: result.append(None); continue
        if c.ma_type=='EMA':
            previous=value if previous is None else previous+2/(c.ma_length+1)*(value-previous)
            result.append(previous); continue
        window.append((value,volumes[i])); window=window[-c.ma_length:]
        if len(window)<c.ma_length: result.append(None); continue
        if c.ma_type=='WMA': result.append(sum(v*(n+1) for n,(v,_) in enumerate(window))/(c.ma_length*(c.ma_length+1)/2))
        elif c.ma_type=='VWMA':
            total=sum(v for _,v in window)
            result.append(sum(x*v for x,v in window)/total if total else None)
        else: result.append(sum(x for x,_ in window)/c.ma_length)
    return result


def pivot_events(rows,values):
    """RSI pivots L=R=5; barssince(found[1]) yields pivot separation minus one."""
    previous={True:None,False:None}; events=[]
    for known in range(10,len(rows)):
        p=known-5; v=values[p]
        if v is None: continue
        left=values[p-5:p]; right=values[p+1:p+6]
        if any(x is None for x in left+right): continue
        for low in (True,False):
            # Pine chooses the rightmost equal extremum on a plateau.
            found=(v<=min(left) and v<min(right)) if low else (v>=max(left) and v>max(right))
            if not found: continue
            old=previous[low]; previous[low]=p
            if old is None or not 5<=p-old-1<=60: continue
            field='low' if low else 'high'
            if not ((v>values[old] and rows[p][field]<rows[old][field]) if low else (v<values[old] and rows[p][field]>rows[old][field])): continue
            events.append(dict(divergenceType='REGULAR_BULLISH' if low else 'REGULAR_BEARISH',direction='BULLISH' if low else 'BEARISH',
                pivot1Index=old,pivot2Index=p,detectedIndex=known,
                pivot1At=rows[old]['timestamp'].isoformat(),pivot2At=rows[p]['timestamp'].isoformat(),detectedAt=rows[known]['timestamp'].isoformat(),
                pivot1Price=rows[old][field],pivot2Price=rows[p][field],pivot1Rsi=values[old],pivot2Rsi=v))
    return events


def calculate(rows,config=None):
    c=config if isinstance(config,RsiConfig) else RsiConfig.resolve(config)
    values=pine_rsi([source_value(r,c.source) for r in rows],c.period)
    ma=smoothing(values,[r.get('volume',0) for r in rows],c)
    points=[]
    for i,row in enumerate(rows):
        std=None
        window=values[max(0,i-c.ma_length+1):i+1]
        if c.ma_type=='SMA + Bollinger Bands' and len(window)==c.ma_length and all(v is not None for v in window):
            mean=sum(window)/len(window); std=sqrt(sum((v-mean)**2 for v in window)/len(window))*c.bb_mult
        points.append(dict(timestamp=row['timestamp'].isoformat(),rsi=values[i],ma=ma[i],bbUpper=ma[i]+std if std is not None else None,bbLower=ma[i]-std if std is not None else None))
    return dict(points=points,events=pivot_events(rows,values) if c.calculate_divergence else [],settings=asdict(c))


def strategy_card(overlay,count):
    events=overlay['events']; event=events[-1] if events else None
    minimum=overlay['settings']['period']+17
    status=event['divergenceType'] if event else 'INSUFFICIENT_HISTORY' if count<minimum else 'NO_SETUP'
    return dict(id='rsi_divergence',name='RSI Divergence',minimumCandles=minimum,availableCandles=count,status=status,
        bias=event['direction'].lower() if event else 'neutral',signalAt=event['detectedAt'] if event else None,
        metrics=([dict(label=label,value=event[key]) for key,label in [('pivot1Rsi','First pivot RSI'),('pivot2Rsi','Second pivot RSI'),('pivot1Price','First pivot price'),('pivot2Price','Second pivot price')]]+[dict(label='Confirmation age (bars)',value=count-1-event['detectedIndex'])]) if event else [],
        checks=[],markers=[],levels=[],scenario=(f"{event['direction'].title()} divergence confirmed five bars after the RSI pivot. Label is placed on the pivot; confirmation time is shown separately. This script has no breakout, stop or target rules." if event else 'No regular RSI divergence detected in the loaded history.' if overlay['settings']['calculate_divergence'] else 'Calculate Divergence is disabled.'))
