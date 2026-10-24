# Derived from Sutradhar by © sairanir23, MPL-2.0; see docs/sutradhar.pine.
from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter
from services.sutradhar import calculate, SutradharConfig, LEVELS,stored_session_open


class SutradharStrategy(BaseStrategy):
    metadata=StrategyMetadata(id='sutradhar',name='Sutradhar',category='Reference Levels',default_timeframe='15m',min_candles=14,
        description='Intraday levels around the current daily open, using prior daily high/low averages. Reference levels only; no buy/sell or risk rules are supplied.',
        parameters=[StrategyParameter(name=key,display_name=label,type='int',default=value,min_value=1,max_value=1000)
                    for key,label,value in [('p1','Period 1 (Flow/Value)',14),('p2','Period 2 (Crest/Base)',7),('p3','Period 3 (Crown/Origin)',5)]]+
                   [StrategyParameter(name='use_ema',display_name='Use EMA instead of SMA',type='bool',default=False)])

    def candle_window(self,params): return 1000

    def run(self,df,instruments_map,params):
        from services.ghost_scanner import completed_rows,TIMEFRAMES
        timeframe=params.get('_timeframe','1d')
        if timeframe not in {'5m','15m','1h'} or df.is_empty(): return []
        config=SutradharConfig.resolve({k:params[k] for k in ('p1','p2','p3','use_ema') if k in params})
        results=[]
        for group in df.sort(['instrument_key','timestamp']).partition_by('instrument_key',maintain_order=True):
            key=group['instrument_key'][0];meta=instruments_map.get(key)
            if not meta: continue
            rows=completed_rows(group.to_dicts(),timeframe)
            overlay=calculate(rows,params.get('_daily_rows',{}).get(key,[]),TIMEFRAMES[timeframe],config,session_opens=stored_session_open(rows))
            if overlay['status']!='LEVELS_READY': continue
            last=overlay['points'][-1]
            results.append(dict(instrumentKey=key,symbol=meta.get('symbol',key),name=meta.get('name',''),exchange=meta.get('exchange','NSE'),
                strategyId='sutradhar',status='LEVELS_READY',state='LEVELS_READY',close=rows[-1]['close'],volume=rows[-1]['volume'],
                changePct=(rows[-1]['close']/rows[-2]['close']-1)*100 if len(rows)>1 else None,
                asOf=rows[-1]['timestamp'].isoformat(),**{name:last[name] for name in LEVELS}))
        return sorted(results,key=lambda r:r['symbol'])
