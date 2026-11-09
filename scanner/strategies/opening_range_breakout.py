"""Opening-range holds; uses completed 5m bars and verifies every opening slot."""
from datetime import datetime, timezone
from scanner.strategies.base import BaseStrategy, StrategyMetadata, StrategyParameter
from services.market_session import opening_range, utc, clean
from services.market_sync import INDIA


class OpeningRangeBreakoutStrategy(BaseStrategy):
    metadata = StrategyMetadata(
        id='opening_range_breakout', name='Opening Range Breakout', category='Breakout',
        default_timeframe='5m', min_candles=5,
        description='NSE 09:15 opening range: 15, 30 or 60 minutes. Bullish above its high and bearish below its low after consecutive completed 5m closes. Uses the latest stored session; old data is labelled. Missing opening bars are not estimated.',
        parameters=[
            StrategyParameter(name='range_minutes', display_name='Opening range (minutes)', type='str', default='15', options=['15', '30', '60']),
            StrategyParameter(name='hold_bars', display_name='Consecutive 5m closes to hold', type='int', default=2, min_value=1, max_value=6),
            StrategyParameter(name='include_waiting', display_name='Include waiting / incomplete stocks', type='bool', default=False)])

    def candle_window(self, params):
        return 1000

    def run(self, df, instruments_map, params):
        if params.get('_timeframe', '5m') != '5m':
            raise ValueError('Opening Range Breakout requires stored 5m candles.')
        minutes, hold = int(params.get('range_minutes', '15')), params.get('hold_bars', 2)
        now = datetime.now(timezone.utc)
        results = []
        if df.is_empty():
            return results
        for group in df.sort(['instrument_key', 'timestamp']).partition_by('instrument_key', maintain_order=True):
            key = group['instrument_key'][0]
            if key not in instruments_map:
                continue
            rows = [r for r in group.to_dicts() if utc(r['timestamp']) <= now]
            context = opening_range(rows, minutes, hold, now)
            if context['orbState'] not in {'BULLISH', 'BEARISH'} and not params.get('include_waiting', False):
                continue
            completed = [r for r in rows if utc(r['timestamp']).isoformat() == context['orbAsOf']]
            latest = completed[-1] if completed and clean(completed[-1]) else None
            metadata = instruments_map[key]
            stale = context['sessionDate'] != now.astimezone(INDIA).date().isoformat()
            if context['orbAsOf']:
                from datetime import timedelta
                stale |= now - datetime.fromisoformat(context['orbAsOf']) > timedelta(minutes=20)
            state = context['orbState']
            results.append(dict(instrumentKey=key, symbol=metadata.get('symbol', ''), name=metadata.get('name', ''),
                                exchange='NSE', strategyId='opening_range_breakout', status=state,
                                signal='BUY' if state == 'BULLISH' else 'SELL' if state == 'BEARISH' else 'WAIT',
                                close=latest['close'] if latest else None, volume=latest['volume'] if latest else None,
                                changePct=context['fromOpenPct'], asOf=context['orbAsOf'], stale=stale,
                                decision='HISTORICAL' if stale else 'BULLISH HOLD' if state == 'BULLISH' else 'BEARISH HOLD' if state == 'BEARISH' else 'WAIT',
                                decisionReason=context['orbReason'] + (' Old data; current breakout is not verified.' if stale else ''), **context))
        return sorted(results, key=lambda r: (r['stale'], r['symbol']))
