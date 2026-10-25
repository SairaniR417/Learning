"""Shared Golden/Death Cross calculation for scans and chart workspaces."""
from math import isfinite


def resolve(settings=None):
    from scanner.strategies.golden_death_cross import GoldenDeathCrossStrategy
    params=GoldenDeathCrossStrategy.metadata.parameters
    if settings is not None and (not isinstance(settings,dict) or set(settings)-{p.name for p in params}):
        raise ValueError('Unknown Golden / Death Cross input.')
    values={p.name:p.default for p in params};values.update(settings or {})
    for p in params:
        v=values[p.name]
        if p.type=='bool':
            if type(v) is not bool: raise ValueError(f'{p.display_name} must be boolean.')
        elif isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) or (p.type=='int' and type(v) is not int) or (p.min_value is not None and v<p.min_value) or (p.max_value is not None and v>p.max_value):
            raise ValueError(f'Invalid {p.display_name}.')
    if values['ema_fast']>=values['ema_slow'] or values['sma_medium']>=values['sma_long']:
        raise ValueError('Fast EMA must be shorter than slow EMA; medium SMA must be shorter than long SMA.')
    return values


def calculate(rows,settings=None):
    from scanner.strategies.golden_death_cross import GoldenDeathCrossStrategy as Math
    p=resolve(settings)
    close=[float(r['close']) for r in rows];high=[float(r['high']) for r in rows];low=[float(r['low']) for r in rows];volume=[float(r.get('volume') or 0) for r in rows]
    fast=Math._ema(close,p['ema_fast']);slow=Math._ema(close,p['ema_slow']);medium=Math._sma(close,p['sma_medium']);long=Math._sma(close,p['sma_long']);rsi=Math._rsi(close,p['rsi_period'])
    points=[];events=[];latest=None;confirmation=None;checks={};state='INSUFFICIENT_HISTORY';signal=None
    def stamp(r): return r['timestamp'].isoformat() if hasattr(r['timestamp'],'isoformat') else str(r['timestamp'])
    for i,r in enumerate(rows):
        values=dict(timestamp=stamp(r),ema9=fast[i],ema20=slow[i],sma50=medium[i],sma200=long[i],rsi=rsi[i])
        points.append(values)
        if i<p['sma_long']: continue
        golden=medium[i-1]<=long[i-1] and medium[i]>long[i]
        death=medium[i-1]>=long[i-1] and medium[i]<long[i]
        if golden or death:
            latest=dict(index=i,timestamp=stamp(r),price=close[i],direction='BUY' if golden else 'SELL',kind='GOLDEN_CROSS' if golden else 'DEATH_CROSS')
            events.append(dict(latest));confirmation=None
        if latest is None: state='NO_CROSS';continue
        up=latest['direction']=='BUY'
        slope=p['slope_lookback'];vl=p['volume_lookback'];bl=p['breakout_lookback']
        ef,es,m,l,rv=fast[i],slow[i],medium[i],long[i],rsi[i]
        prior_m=medium[i-slope] if i>=slope else None;prior_l=long[i-slope] if i>=slope else None
        average=sum(volume[i-vl:i])/vl if i>=vl else 0
        level=(max(high[i-bl:i]) if up else min(low[i-bl:i])) if i>=bl else None
        checks={
            f'MA alignment: EMA {p["ema_fast"]} {">" if up else "<"} EMA {p["ema_slow"]} {">" if up else "<"} SMA {p["sma_medium"]} {">" if up else "<"} SMA {p["sma_long"]}': ef is not None and es is not None and (ef>es>m>l if up else ef<es<m<l),
            'Price above both EMAs' if up else 'Price below both EMAs':ef is not None and es is not None and (close[i]>ef and close[i]>es if up else close[i]<ef and close[i]<es),
            'Both SMAs rising' if up else 'Both SMAs falling':prior_m is not None and prior_l is not None and (m>prior_m and l>prior_l if up else m<prior_m and l<prior_l),
            f'RSI {">" if up else "<"} {p["bullish_rsi"] if up else p["bearish_rsi"]:g}':rv is not None and (rv>p['bullish_rsi'] if up else rv<p['bearish_rsi']),
            f'Volume >= {p["volume_multiplier"]:g}x prior {vl}-bar average':average>0 and volume[i]>=p['volume_multiplier']*average,
            f'Close {"above prior high" if up else "below prior low"} ({bl} bars)':level is not None and (close[i]>level if up else close[i]<level),
        }
        age=i-latest['index'];passed=all(checks.values())
        if not p['require_confirmation']:
            state='CROSS' if age==0 else 'CROSS_ACTIVE';signal=latest['direction']
        elif confirmation is not None:
            state='CONFIRMED_ACTIVE' if passed else 'CONFIRMED_WEAKENED';signal=latest['direction']
        elif age>p['max_confirmation_bars']:
            state='EXPIRED';signal=None
        elif passed:
            confirmation=stamp(r);state='CONFIRMED';signal=latest['direction']
            events.append(dict(index=i,timestamp=stamp(r),price=close[i],direction=signal,kind='CONFIRMATION'))
        else: state='WATCH';signal=None
    age=len(rows)-1-latest['index'] if latest else None
    return dict(inputs=p,points=points,events=events,latestCross=latest,state=state,signal=signal,confirmationTime=confirmation,
                confirmationChecks=checks,barsSinceCross=age,minimumCandles=p['sma_long']+1,
                scanMatch=bool(latest and (p['require_confirmation'] and state in {'WATCH','CONFIRMED','CONFIRMED_ACTIVE','CONFIRMED_WEAKENED'} or not p['require_confirmation'] and age<=p['max_confirmation_bars'])))


def scan_row(overlay,rows,key,meta):
    if not overlay['scanMatch']: return None
    last=rows[-1];point=overlay['points'][-1];cross=overlay['latestCross'];p=overlay['inputs']
    prev=rows[-2]['close'] if len(rows)>1 else None
    return dict(instrumentKey=key,symbol=meta.get('symbol',key),name=meta.get('name',key),exchange=meta.get('exchange','NSE'),strategyId='golden_death_cross',
                close=last['close'],previousClose=prev,changePct=(last['close']/prev-1)*100 if prev else None,volume=last.get('volume',0),
                **{k:point[k] for k in ('ema9','ema20','sma50','sma200','rsi')},status=overlay['signal'] or 'WATCH',signal=overlay['signal'],state=overlay['state'],
                requireConfirmation=p['require_confirmation'],crossType=cross['kind'],crossTime=cross['timestamp'],confirmationTime=overlay['confirmationTime'],barsSinceCross=overlay['barsSinceCross'],
                confirmationCount=sum(overlay['confirmationChecks'].values()),confirmationChecks=overlay['confirmationChecks'] if p['require_confirmation'] else {},
                emaFastPeriod=p['ema_fast'],emaSlowPeriod=p['ema_slow'],smaMediumPeriod=p['sma_medium'],smaLongPeriod=p['sma_long'],candlesAnalyzed=len(rows),asOf=point['timestamp'])


def strategy_card(overlay,count):
    cross=overlay['latestCross'];p=overlay['inputs'];point=overlay['points'][-1] if overlay['points'] else {}
    return dict(id='golden_death_cross',name='Golden Cross / Death Cross',status=overlay['state'],
                bias=('bullish' if cross['direction']=='BUY' else 'bearish') if cross else 'neutral',availableCandles=count,minimumCandles=overlay['minimumCandles'],
                signalAt=overlay['confirmationTime'] or (cross['timestamp'] if cross else None),
                scenario=(f"{'Six-filter confirmation' if p['require_confirmation'] else 'Classic crossover'} · SMA {p['sma_medium']} / {p['sma_long']}. "
                          +(f"Latest {cross['kind'].replace('_',' ').lower()}: {overlay['barsSinceCross']} bars ago." if cross else 'No cross in loaded history.')
                          +' Periods count chart candles; daily charts give the classic daily signal.'),
                metrics=[dict(label=label,value=point[key]) for key,label in [('sma50',f"SMA {p['sma_medium']}"),('sma200',f"SMA {p['sma_long']}"),('rsi','RSI')] if point.get(key) is not None and (key!='rsi' or p['require_confirmation'])],
                checks=[dict(label=k,passed=v) for k,v in overlay['confirmationChecks'].items()] if p['require_confirmation'] else [],markers=[],levels=[])
