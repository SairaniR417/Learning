# Derived from Sutradhar by © sairanir23, Mozilla Public License 2.0.
# https://mozilla.org/MPL/2.0/ — source preserved in docs/sutradhar.pine.
"""Daily-open intraday levels; never use the current day's high/low in a range."""
from dataclasses import dataclass, asdict
from datetime import timezone
from math import isfinite
from zoneinfo import ZoneInfo

INDIA = ZoneInfo('Asia/Kolkata')
LEVELS = ('Flow', 'Crest', 'Crown', 'Value', 'Base', 'Origin', 'Mid', 'O')


@dataclass(frozen=True)
class SutradharConfig:
    p1: int = 14
    p2: int = 7
    p3: int = 5
    use_ema: bool = False

    @classmethod
    def resolve(cls, params=None):
        if params is None: params = {}
        if not isinstance(params, dict) or set(params)-set(cls.__dataclass_fields__):
            raise ValueError('Unknown Sutradhar setting.')
        config = cls(**params)
        if any(type(getattr(config, key)) is not int or not 1 <= getattr(config, key) <= 1000 for key in ('p1','p2','p3')):
            raise ValueError('Sutradhar periods must be integers from 1 to 1000.')
        if type(config.use_ema) is not bool:
            raise ValueError('Use EMA must be boolean.')
        return config


def local_day(timestamp):
    if timestamp.tzinfo is None: timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(INDIA).date()


def stored_session_open(rows):
    """Only an actual 09:15 NSE/BSE equity bar proves the latest daily open."""
    if not rows: return {}
    day=local_day(rows[-1]['timestamp'])
    for row in rows:
        if not row.get('instrument_key','').startswith(('NSE_EQ|','BSE_EQ|')): continue
        timestamp=row['timestamp']
        if timestamp.tzinfo is None: timestamp=timestamp.replace(tzinfo=timezone.utc)
        local=timestamp.astimezone(INDIA)
        value=row.get('open')
        if local.date()==day and (local.hour,local.minute,local.second)==(9,15,0) and isinstance(value,(int,float)) and isfinite(value) and value>0:
            return {day:value}
    return {}


def calculate(intraday, daily, interval=15, settings=None, *, continuous_futures=False, session_opens=None):
    """Options/equities use their own daily instrument. Futures require root 1! data.

    Daily open is safe at session start. Prior-day highs/lows are shifted by one
    daily bar before smoothing, reproducing security(D, high[1]/low[1]).
    Missing daily opens are not estimated from a truncated intraday window.
    """
    config = settings if isinstance(settings,SutradharConfig) else SutradharConfig.resolve(settings)
    result = dict(points=[],settings=asdict(config),interval=interval,source='Same instrument daily OHLC',message='')
    if interval >= 1440:
        result.update(status='UNSUPPORTED_TIMEFRAME',message='Sutradhar: Intraday charts only')
        return result
    if continuous_futures:
        result.update(status='UNAVAILABLE',message='Sutradhar futures require the root continuous 1! daily series. That feed is unavailable; a single expiry is not substituted.')
        return result
    # One authoritative daily candle per exchange-local trading date.
    by_day = {}
    for row in sorted(daily,key=lambda r:r['timestamp']):
        values=[row.get(k) for k in ('open','high','low','close')]
        if not all(isinstance(v,(int,float)) and isfinite(v) and v>0 for v in values): continue
        o,h,l,c=values
        if not l <= min(o,c) <= max(o,c) <= h: continue
        by_day[local_day(row['timestamp'])]=row
    opens=dict(session_opens or {})
    opens.update({day:row['open'] for day,row in by_day.items()})
    days = sorted(set(by_day)|set(opens))
    histories = {period:[] for period in {config.p1,config.p2,config.p3}}
    smoothed = {}
    highs, lows = [], []
    for day in days:
        row=by_day.get(day)
        values={}
        for period,ema_history in histories.items():
            # This day's EMA uses only highs/lows appended on preceding days.
            if config.use_ema:
                width=(ema_history[-1][0]-ema_history[-1][1]) if ema_history else None
            else:
                width=(sum(highs[-period:])-sum(lows[-period:]))/period if len(highs)>=period else None
            values[period]=width
        smoothed[day]=values
        if row is None: continue  # A verified open never becomes an invented daily range.
        highs.append(row['high']);lows.append(row['low'])
        for period,ema_history in histories.items():
            alpha=2/(period+1)
            previous=ema_history[-1] if ema_history else (row['high'],row['low'])
            ema_history.append((previous[0]+alpha*(row['high']-previous[0]),previous[1]+alpha*(row['low']-previous[1])))
    for row in intraday:
        day=local_day(row['timestamp'])
        point=dict(timestamp=row['timestamp'].isoformat(),**{name:None for name in LEVELS})
        if day in opens:
            o=opens[day];point.update(O=o)
            for period,upper,lower in ((config.p1,'Flow','Value'),(config.p2,'Crest','Base'),(config.p3,'Crown','Origin')):
                width=smoothed[day][period]
                if width is not None: point.update({upper:o+width/2,lower:o-width/2})
            point['Mid']=(point['Flow']+point['Value'])/2 if point['Flow'] is not None else None
        result['points'].append(point)
    last=result['points'][-1] if result['points'] else None
    ready=bool(last and all(last[name] is not None for name in LEVELS))
    result['status']='LEVELS_READY' if ready else 'INSUFFICIENT_HISTORY'
    result['dailyCandles']=sum(day<local_day(intraday[-1]['timestamp']) for day in by_day) if intraday else 0
    if intraday and local_day(intraday[-1]['timestamp']) not in by_day and local_day(intraday[-1]['timestamp']) in opens:
        result['source']='Previous daily OHLC plus the stored 09:15 session opening bar'
    result['message']=('Daily-open reference levels. The supplied script defines no entry, exit, target, stop-loss or holding-time rules.' if ready else
        'Current daily open and enough previous daily candles are required. Missing levels are not estimated.')
    return result


def strategy_card(overlay,count):
    last=overlay['points'][-1] if overlay['points'] else {}
    minimum=1 if overlay['settings']['use_ema'] else max(overlay['settings'][p] for p in ('p1','p2','p3'))
    return dict(id='sutradhar',name='Sutradhar',status=overlay['status'],bias='neutral',minimumCandles=minimum,availableCandles=overlay.get('dailyCandles',0),
        signalAt=None,scenario=overlay['message'],checks=[],markers=[],levels=[],
        metrics=[dict(label=name,value=last[name]) for name in LEVELS if last.get(name) is not None])


def unloaded_card(interval):
    overlay=calculate([],[],interval)
    if interval<1440:
        overlay.update(status='NOT_LOADED',message='Select Sutradhar to load its daily-open levels. Intraday charts only.')
    return strategy_card(overlay,0)
