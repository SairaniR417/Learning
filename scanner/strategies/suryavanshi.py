from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter
from services.suryavanshi import Config, calculate


class SuryavanshiStrategy(BaseStrategy):
    metadata=StrategyMetadata(id='suryavanshi',name='Suryavanshi',category='Breakout',default_timeframe='15m',min_candles=41,
        description='Supplied Pine swing-break indicator: CHoCH/BOS, ATR(14) stop, RR target and active trade state.',parameters=[
            StrategyParameter(name='length',display_name='Length',type='int',default=20,min_value=0,max_value=5000),
            StrategyParameter(name='candle_type',display_name='Type',type='str',default='Wicks',options=['Wicks','Body']),
            StrategyParameter(name='rr_ratio',display_name='RR Ratio',type='float',default=1.1),
            StrategyParameter(name='sl_type',display_name='SL Type',type='str',default='Close',options=['Close','High/Low']),
            StrategyParameter(name='show_sl',display_name='Show SL',type='bool',default=False)])

    def candle_window(self,params): return 1000

    def run(self,df,instruments_map,params):
        from services.ghost_scanner import completed_rows
        if df.is_empty(): return []
        config=Config.resolve({k:v for k,v in params.items() if not k.startswith('_')})
        results=[]
        for group in df.sort(['instrument_key','timestamp']).partition_by('instrument_key',maintain_order=True):
            key=group['instrument_key'][0];meta=instruments_map.get(key)
            if not meta: continue
            rows=completed_rows(group.to_dicts(),params.get('_timeframe','15m'))
            overlay=calculate(rows,config)
            latest=overlay['trades'][-1] if overlay['trades'] else None
            if not latest or (not overlay['activeTrade'] and latest['index']!=len(rows)-1): continue
            results.append(dict(instrumentKey=key,symbol=meta.get('symbol',key),name=meta.get('name',''),exchange=meta.get('exchange','NSE'),
                strategyId='suryavanshi',status='BUY' if latest['direction']=='long' else 'SELL',state=latest['state'],setupState=latest['state'],
                close=rows[-1]['close'],volume=rows[-1]['volume'],entry=latest['entry'],stopLoss=latest['sl'],tp1=latest['tp'],
                signalAt=latest['timestamp'],asOf=rows[-1]['timestamp'].isoformat(),winningTrades=overlay['winningTrades'],losingTrades=overlay['losingTrades'],
                changePct=(rows[-1]['close']/rows[-2]['close']-1)*100 if len(rows)>1 else None))
        return sorted(results,key=lambda r:r['symbol'])
