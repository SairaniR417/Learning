"""Deterministic, sequential translation of the user supplied Pine v5 indicator.

Replayed from the loaded prefix on every request, including an unconfirmed last
bar. This deliberately preserves Pine's independent TP/SL checks and pivot state.
"""
from dataclasses import dataclass, asdict
from math import isfinite, floor


@dataclass(frozen=True)
class Config:
    length: int = 20
    candle_type: str = 'Wicks'
    rr_ratio: float = 1.1
    sl_type: str = 'Close'
    show_sl: bool = False

    @classmethod
    def resolve(cls, settings=None):
        values = {} if settings is None else settings
        if not isinstance(values, dict) or set(values)-set(cls.__dataclass_fields__):
            raise ValueError('Unknown Suryavanshi input.')
        c = cls(**values)
        if type(c.length) is not int or c.length < 0 or c.length > 5000:
            raise ValueError('Suryavanshi Length must be an integer from 0 to 5000.')
        if isinstance(c.rr_ratio, bool) or not isinstance(c.rr_ratio, (int,float)) or not isfinite(c.rr_ratio):
            raise ValueError('Suryavanshi RR Ratio must be finite.')
        if c.candle_type not in ('Wicks','Body') or c.sl_type not in ('Close','High/Low') or type(c.show_sl) is not bool:
            raise ValueError('Invalid Suryavanshi Type, SL Type or Show SL.')
        return c


def calculate(rows, config=None):
    c = config or Config()
    points, lines, labels, trades, alerts = [], [], [], [], []
    last_pivot = [None,None]
    updated = [None,None]
    anchors = [None,None]
    armed = [False,False]
    hbreak = False
    active = None
    wins = losses = 0
    atr = None
    tr_seed = []

    def stamp(row):
        t=row['timestamp']
        return t.isoformat() if hasattr(t,'isoformat') else t

    def line(kind,x1,y1,x2,y2,direction=None):
        obj=dict(kind=kind,x1=x1,y1=y1,x2=x2,y2=y2,direction=direction)
        lines.append(obj)
        if len(lines)>500: del lines[0]
        return obj

    def label(kind,x,y,**kw):
        obj=dict(kind=kind,x=x,y=y,**kw)
        labels.append(obj)
        if len(labels)>500: del labels[0]
        return obj

    for i,r in enumerate(rows):
        o,h,l,close=(float(r[k]) for k in ('open','high','low','close'))
        prev=float(rows[i-1]['close']) if i else close
        tr=max(h-l,abs(h-prev),abs(l-prev))
        if atr is None:
            tr_seed.append(tr)
            if len(tr_seed)==14: atr=sum(tr_seed)/14
        else: atr=(atr*13+tr)/14
        p=c.length
        if i>=2*p:
            j=i-p
            for side,field in enumerate(('high','low')):
                value=float(rows[j][field])
                left=[float(x[field]) for x in rows[j-p:j]]
                right=[float(x[field]) for x in rows[j+1:i+1]]
                pivot=(all(value>=x for x in left) and all(value>x for x in right)) if side==0 else (all(value<=x for x in left) and all(value<x for x in right))
                if pivot:
                    # change(fixnan(PH/PL)): the first and equal pivots do not arm.
                    if last_pivot[side] is not None and value!=last_pivot[side]:
                        updated[side],anchors[side],armed[side]=value,j,True
                    last_pivot[side]=value
        prices=(h,l) if c.candle_type=='Wicks' else (close,close)
        raw=[armed[0] and prices[0]>updated[0],armed[1] and prices[1]<updated[1]]
        for side in range(2):
            if raw[side]: armed[side]=False
        signals=[bool(v and active is None) for v in raw]
        # Vol is constructed afresh each bar, but shared by both calls this bar.
        scr=[]; green=[]; red=[]; total=[]
        for side,fire in enumerate(signals):
            if not fire: continue
            count=abs(anchors[side]-i)
            # Pine's descending 0..-1 loop for the zero-length corner case.
            offsets=range(count) if count else (0,-1)
            scr.extend(float(rows[i-k]['close']) if 0<=i-k<len(rows) else None for k in offsets)
            for k,value in enumerate(scr):
                old=rows[i-k] if i-k>=0 else None
                vol=old.get('volume') if old else None
                if vol is None: continue
                total.append(float(vol))
                if value is not None and value>float(old['open']): green.append(float(vol))
                if value is not None and value<float(old['open']): red.append(float(vol))
            def ratio(a): return floor(sum(a)/sum(total)*10000+.5)/100 if sum(total) else 0
            sign='green' if ratio(green)>55 else 'red' if ratio(red)>55 else 'yellow'
            direction='long' if side==0 else 'short'
            structure=('BOS' if hbreak else 'CHoCH') if side==0 else ('CHoCH' if hbreak else 'BOS')
            line('breakout',anchors[side],updated[side],i,updated[side],direction)
            label('structure',(i+anchors[side])//2,updated[side],text=structure,sign=sign,direction=direction)
            label('entry',i,l if side==0 else h,direction=direction)
            hbreak=side==0
            alerts.append(dict(timestamp=stamp(r),index=i,title='BUY' if side==0 else 'Sell',direction=direction))
        if any(signals):
            # Both signals: Short overwrites direction; switch(Long) still wins levels.
            long_levels=signals[0]
            distance=abs(close-(l-atr*1.5 if long_levels else h+atr*1.5)) if atr is not None else None
            tp=close+(1 if long_levels else -1)*c.rr_ratio*distance if distance is not None else None
            sl=close+(-1 if long_levels else 1)*distance if distance is not None else None
            active=dict(index=i,timestamp=stamp(r),direction='short' if signals[1] else 'long',entry=close,tp=tp,sl=sl,endIndex=i,won=False,lost=False,state='ACTIVE')
            trades.append(active)
            line('connector',i,h if long_levels else l,i,tp)
            active['_tp']=line('target',i,tp,i+2,tp)
            if c.show_sl: active['_sl']=line('stop',i,sl,i+2,sl)
            active['_label']=label('target',i,tp,text='Target',state='ACTIVE',stop=None)
        if active is not None:
            t=active
            t['endIndex']=i
            t['_tp']['x2']=i
            if '_sl' in t: t['_sl']['x2']=i
            t['_label']['x']=i+1
            won=lost=False
            if t['tp'] is not None:
                if t['direction']=='long':
                    won=h>=t['tp'];lost=(close if c.sl_type=='Close' else l)<=t['sl']
                else:
                    won=l<=t['tp'];lost=(close if c.sl_type=='Close' else h)>=t['sl']
            if won or lost:
                wins+=int(won);losses+=int(lost)
                t.update(won=won,lost=lost,state='BOTH' if won and lost else 'STOP' if lost else 'TARGET')
                t['_label'].update(state='STOP' if lost else 'TARGET',stop=t['sl'] if lost else None)
                active=None
        points.append(dict(timestamp=stamp(r),index=i,state=active['direction'] if active else 'neutral',buy=signals[0],sell=signals[1]))
    return dict(inputs=asdict(c),points=points,lines=lines,labels=labels,
                trades=[{k:v for k,v in t.items() if not k.startswith('_')} for t in trades],alerts=alerts,
                winningTrades=wins,losingTrades=losses,activeTrade=({k:v for k,v in active.items() if not k.startswith('_')} if active else None))


def strategy_card(overlay,count):
    t=overlay.get('activeTrade')
    return dict(id='suryavanshi',name='Suryavanshi',status=('BUY' if t['direction']=='long' else 'SELL') if t else ('INSUFFICIENT_HISTORY' if count<2*overlay['inputs']['length']+1 else 'WAITING'),
                bias=('bullish' if t['direction']=='long' else 'bearish') if t else 'neutral',availableCandles=count,
                minimumCandles=2*overlay['inputs']['length']+1,signalAt=t['timestamp'] if t else None,
                scenario='Confirmed swing breaks with ATR(14) risk and the supplied RR. Trade counts cover loaded history.',
                metrics=[dict(label='Winning Trades',value=overlay['winningTrades']),dict(label='Losing Trades',value=overlay['losingTrades'])],
                markers=[],levels=[],checks=[])
