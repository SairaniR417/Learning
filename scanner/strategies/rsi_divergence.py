"""Scanner adapter for the user's supplied RSI Pine script."""
from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter
from services.rsi_overlay import RsiConfig, calculate


class RsiDivergenceStrategy(BaseStrategy):
    metadata=StrategyMetadata(id='rsi_divergence',name='RSI Divergence',category='Momentum',min_candles=31,
        description='Supplied Pine RSI: regular bullish/bearish RSI pivots, five bars on each side, separation 6–61 bars. No hidden patterns or breakout filters.',
        parameters=[StrategyParameter(name='period',display_name='RSI Length',type='int',default=14,min_value=1,max_value=1000),
                    StrategyParameter(name='freshness',display_name='Show signals confirmed within bars',type='int',default=5,min_value=1,max_value=1000)])

    def candle_window(self,params): return max(1000,int(params.get('period',14))+80)

    def run(self,df,instruments_map,params):
        from services.ghost_scanner import completed_rows
        if df.is_empty(): return []
        results=[]; timeframe=params.get('_timeframe','1d')
        for group in df.sort(['instrument_key','timestamp']).partition_by('instrument_key',maintain_order=True):
            key=group['instrument_key'][0]; meta=instruments_map.get(key)
            if not meta: continue
            rows=completed_rows(group.to_dicts(),timeframe) if timeframe in {'1d','1h','15m','5m'} else group.to_dicts()
            if not rows: continue
            overlay=calculate(rows,RsiConfig(period=params.get('period',14)))
            events=[e for e in overlay['events'] if len(rows)-1-e['detectedIndex']<params.get('freshness',5)]
            if not events: continue
            event=events[-1]
            results.append({**event,'instrumentKey':key,'symbol':meta.get('symbol',key),'name':meta.get('name',''),'exchange':meta.get('exchange','NSE'),
                'close':rows[-1]['close'],'volume':rows[-1].get('volume',0),'changePct':(rows[-1]['close']/rows[-2]['close']-1)*100 if len(rows)>1 else None,
                'rsi':overlay['points'][-1]['rsi'],'state':'DETECTED','status':event['divergenceType'],'signal':event['direction'],
                'strategyId':'rsi_divergence','ageBars':len(rows)-1-event['detectedIndex'],'asOf':rows[-1]['timestamp'].isoformat()})
        return sorted(results,key=lambda r:(r['ageBars'],r['symbol']))
