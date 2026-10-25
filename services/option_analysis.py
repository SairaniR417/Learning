from services import golden_cross
from services import suryavanshi
"""Analyze a verified option contract against completed provider candles."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from math import isfinite
from urllib.parse import quote

from fastapi import HTTPException
import polars as pl

from scanner.strategies import strategy_registry
from services.rsi_overlay import calculate as rsi_overlay, strategy_card as rsi_card, RsiConfig
from services import option_chain, option_market
from services.ghost_rider_overlay import calculate as ghost_overlay, strategy_card
from services.market_sync import nse_daily_closed
from services import sutradhar

OPTION_TIMEFRAMES = {5:('minutes',5,28,'5m'),15:('minutes',15,28,'15m'),
                     60:('hours',1,89,'1h'),1440:('days',1,1095,'1d'),10080:('days',1,1095,'1w')}


def bar_closed(timestamp,key,interval,now):
    if interval==1440:
        return (timestamp.astimezone(option_chain.INDIA).date()<now.astimezone(option_chain.INDIA).date()
                if key.startswith('MCX_') else nse_daily_closed(timestamp,now))
    return timestamp+timedelta(minutes=interval,seconds=5)<=now


def weekly_candles(daily):
    """ISO Monday weeks in exchange-local time; preserve actual OHLCV."""
    days={row['timestamp'].astimezone(option_chain.INDIA).date():row for row in daily}
    weeks={}
    for day,row in sorted(days.items()):
        monday=day-timedelta(days=day.weekday())
        timestamp=datetime.combine(monday,datetime.min.time(),option_chain.INDIA).astimezone(timezone.utc)
        if monday not in weeks:
            weeks[monday]=dict(row,timestamp=timestamp)
        else:
            target=weeks[monday]
            target.update(high=max(target['high'],row['high']),low=min(target['low'],row['low']),close=row['close'],volume=target['volume']+row['volume'])
    return list(weeks.values())


async def resolve_contract(request, token, underlying, expiry, strike, side):
    await option_market.require_key(underlying)
    if expiry < datetime.now(option_chain.INDIA).date():
        raise HTTPException(400, 'Select a current or upcoming expiry.')
    async def load():
        if underlying.startswith('MCX_FO|'):
            rows = await option_market.mcx_contracts()
        else:
            rows = await option_chain.provider_rows(
                lambda *a, **k: option_market.limited_request(request, *a, **k), token,
                'contract', {'instrument_key': underlying, 'expiry_date': expiry.isoformat()})
        try:
            matches = [r for r in rows if r.get('underlying_key') == underlying
                       and option_market.contract_date(r) == expiry and r.get('strike_price') == strike
                       and r.get('instrument_type') == side]
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(502, 'Provider returned malformed option contracts.') from exc
        if len(matches) != 1 or matches[0].get('instrument_key', '').split('|')[0] not in {'NSE_FO', 'BSE_FO', 'MCX_FO'}:
            raise HTTPException(400, 'This option contract is unavailable. Return to the chain and select a listed contract.')
        return matches[0]
    return await option_market.cache.get(('option-contract', hashlib.sha256(token.encode()).hexdigest(),
                                          underlying, expiry.isoformat(), strike, side), 900, load)


def completed_candles(raw, key, interval, now):
    """Deduplicate timestamps; never bridge a candle with invalid OHLCV."""
    indexed = {}
    for row in raw:
        try:
            timestamp = datetime.fromisoformat(row[0].replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError('Missing timezone')
            timestamp = timestamp.astimezone(timezone.utc)
            if not bar_closed(timestamp,key,interval,now):
                continue
            indexed[timestamp] = row
        except (TypeError, ValueError, IndexError) as exc:
            raise HTTPException(502, 'Provider returned malformed candle timestamps.') from exc
    candles, invalid = [], 0
    for timestamp, row in sorted(indexed.items()):
        try:
            o, h, l, c = [float(v) for v in row[1:5]]
            volume = int(row[5])
            if not all(isfinite(v) and v > 0 for v in (o, h, l, c)) or not l <= min(o, c) <= max(o, c) <= h or volume < 0:
                raise ValueError('Invalid OHLCV')
            candles.append(dict(instrument_key=key, timestamp=timestamp, open=o, high=h, low=l, close=c, volume=volume))
        except (ValueError, TypeError, IndexError, OverflowError):
            invalid += 1
            candles = []
    return candles[-1000:], invalid


async def history(request, token, key, interval):
    async def load():
        now = datetime.now(timezone.utc)
        today = now.astimezone(option_chain.INDIA).date()
        unit,provider_interval,lookback,_=OPTION_TIMEFRAMES[interval]
        start, end = today - timedelta(days=lookback), today - timedelta(days=1)
        base = 'https://api.upstox.com/v3/historical-candle'
        encoded = quote(key, safe='')
        urls = [f'{base}/{encoded}/{unit}/{provider_interval}/{end}/{start}',
                f'{base}/intraday/{encoded}/{unit}/{provider_interval}']
        raw = []
        for url in urls:
            payload = await option_market.limited_request(request, url, headers={'Authorization': f'Bearer {token}'})
            rows = payload.get('data', {}).get('candles') if isinstance(payload, dict) else None
            if not isinstance(payload, dict) or payload.get('status') != 'success' or not isinstance(rows, list):
                raise HTTPException(502, 'Candle history is unavailable for this instrument.')
            raw.extend(rows)
        if unit=='days':
            by_day={}
            for row in raw:
                try:
                    day=datetime.fromisoformat(row[0].replace('Z','+00:00')).astimezone(option_chain.INDIA).date()
                    by_day[day]=row
                except (ValueError,IndexError,TypeError) as exc:
                    raise HTTPException(502,'Provider returned malformed daily candles.') from exc
            raw=list(by_day.values())
        if interval==10080:
            daily,invalid=completed_candles(raw,key,1440,now+timedelta(days=1))
            weekly=weekly_candles([r for r in daily if r['timestamp']<=now])
            # A completed week is confirmed when the next ISO week starts.
            candles=[r for r in weekly if r['timestamp']+timedelta(days=7)<=now]
            forming=[r for r in weekly if r['timestamp']+timedelta(days=7)>now]
            return {'candles':candles,'formingCandles':forming,'invalidCandles':invalid,'lookbackDays':lookback}
        candles, invalid = completed_candles(raw, key, interval, now)
        # Preserve the provider's developing bar separately for Ghost Rider.
        # Other strategies still receive completed candles only.
        visible, _ = completed_candles(raw, key, interval, now+timedelta(minutes=interval, seconds=5))
        forming = [r for r in visible if r['timestamp'] <= now and not bar_closed(r['timestamp'],key,interval,now)]
        return {'candles': candles, 'formingCandles': forming, 'invalidCandles': invalid,'lookbackDays':lookback}
    return await option_market.cache.get(('option-history', hashlib.sha256(token.encode()).hexdigest(), key, interval), 55, load)


METRICS = {
    'ema9': 'EMA 9', 'ema20': 'EMA 20', 'ema21': 'EMA 21', 'sma50': 'SMA 50', 'sma200': 'SMA 200',
    'rsi': 'RSI', 'entry': 'Signal entry', 'stopLoss': 'Stop level', 'tp1': 'Target 1', 'tp2': 'Target 2',
    'tp3': 'Target 3', 'tp4': 'Target 4', 'tp5': 'Target 5', 'atr': 'ATR',
    'triggerPrice': 'Confirmation level', 'invalidationPrice': 'Invalidation level',
    'support': 'Support', 'resistance': 'Resistance', 'ageBars': 'Signal age (bars)',
    'pivot1Rsi': 'First pivot RSI', 'pivot2Rsi': 'Second pivot RSI', 'volumeRatio': 'Relative volume',
}


def evaluate(candles, contract, interval, *, stock=False, defer_overlays=False):
    results = []
    key = contract['instrument_key']
    frame = pl.DataFrame(candles) if candles else pl.DataFrame()
    meta = {key: {'symbol': contract.get('trading_symbol', key), 'name': contract.get('name', ''),
                  'exchange': contract.get('exchange', key.split('_')[0])}}
    for descriptor in strategy_registry.list_strategies():
        if defer_overlays and descriptor['id'] in {'ghost_rider','rsi_divergence','suryavanshi','golden_death_cross'}:
            results.append({'id':descriptor['id']})
            continue
        if descriptor['id']=='golden_death_cross':
            results.append(golden_cross.strategy_card(golden_cross.calculate(candles),len(candles)))
            continue
        if descriptor['id']=='suryavanshi':
            results.append(suryavanshi.strategy_card(suryavanshi.calculate(candles),len(candles)))
            continue
        if descriptor['id']=='sutradhar':
            results.append(sutradhar.unloaded_card(interval))
            continue
        if descriptor['id']=='ghost_rider':
            results.append(strategy_card(ghost_overlay(candles,candles if interval==5 else [],interval),len(candles)))
            continue
        if descriptor['id']=='rsi_divergence':
            results.append(rsi_card(rsi_overlay(candles),len(candles)))
            continue
        strategy = strategy_registry.get(descriptor['id'])
        params = {p['name']: p['default'] for p in descriptor['parameters']}
        params['_timeframe'] = f'{interval}m'
        if stock:
            params['_timeframe'] = {1440:'1d',60:'1h'}.get(interval,f'{interval}m')
        minimum = descriptor['min_candles'] + (1 if descriptor['id'] == 'golden_death_cross' else 0)
        available = len(candles)
        result = dict(id=descriptor['id'], name=descriptor['name'], minimumCandles=minimum,
                      availableCandles=available, status='INSUFFICIENT_HISTORY', bias='neutral',
                      metrics=[], checks=[], markers=[], levels=[], scenario='', signalAt=None)
        if available < minimum:
            result['scenario'] = f'Needs at least {minimum} usable completed candles; {available} available.'
            results.append(result)
            continue
        try:
            matches = (strategy.run(frame, meta, params, include_unmatched=True)
                       if descriptor['id'] == 'ema_alignment' else strategy.run(frame, meta, params))
            match = matches[0] if matches else None
            if not match:
                result.update(status='NO_SETUP', scenario='No qualifying setup on the latest completed candle.')
            else:
                status = match.get('status', 'NEUTRAL')
                bullish = status in {'BUY', 'ALIGNED', 'NEWLY_ALIGNED', 'OVERSOLD_REVERSAL'} or 'BULLISH' in status
                bearish = status == 'SELL' or 'BEARISH' in status
                result.update(status=status, bias='bullish' if bullish else 'bearish' if bearish else 'neutral',
                              signalAt=match.get('signalAt') or match.get('confirmedAt') or match.get('detectedAt') or match.get('confirmationTime') or match.get('matchedSince'),
                              metrics=[{'label': label, 'value': match[name]} for name, label in METRICS.items()
                                       if isinstance(match.get(name), (int, float)) and isfinite(match[name])],
                              checks=[{'label': name, 'passed': bool(value)} for name, value in match.get('confirmationChecks', {}).items()])
                result['scenario'] = f"Current {'stock' if stock else 'premium'} setup: {status.replace('_', ' ').lower()}. Confirm with the displayed conditions; no price target is implied."
                if result['signalAt']:
                    result['markers'].append({'timestamp': result['signalAt'], 'label': descriptor['name'], 'bias': result['bias']})
        except Exception:
            logging.getLogger(__name__).exception('Option strategy failed: %s', descriptor['id'])
            result.update(status='UNAVAILABLE', scenario='This strategy could not be evaluated for the supplied candles.')
        results.append(result)
    return results


def underlying_context(candles, side):
    if len(candles) < 20:
        return {'trend': 'UNAVAILABLE', 'supportsPremium': None, 'asOf': None,
                'description': 'Underlying trend needs at least 20 completed candles.'}
    average = candles[0]['close']
    for row in candles[1:]:
        average += 2 / 21 * (row['close'] - average)
    close = candles[-1]['close']
    trend = 'UP' if close > average else 'DOWN' if close < average else 'FLAT'
    supports = None if trend == 'FLAT' else (trend == 'UP' if side == 'CE' else trend == 'DOWN')
    return {'trend': trend, 'supportsPremium': supports, 'close': close, 'ema20': average,
            'asOf': candles[-1]['timestamp'].isoformat(),
            'description': f'Underlying close is {"above" if trend == "UP" else "below" if trend == "DOWN" else "at"} EMA 20. '
                           + ('Direction supports' if supports else 'Direction opposes' if supports is False else 'Direction is neutral for')
                           + f' a rising {side} premium, before volatility and time-decay effects.'}


async def analyze(request, token, underlying, expiry, strike, side, interval, atr_multiplier=1.5, rsi_settings=None, sutradhar_settings=None, suryavanshi_settings=None, golden_settings=None):
    if interval not in OPTION_TIMEFRAMES or side not in {'CE', 'PE'} or not isfinite(strike) or strike <= 0:
        raise HTTPException(400, 'Select CE/PE, a valid strike, and a 5m, 15m, 1h, 1d or 1w timeframe.')
    try: golden_config=golden_cross.resolve(golden_settings)
    except (ValueError,TypeError) as exc: raise HTTPException(400,str(exc)) from exc
    try: sury_config=suryavanshi.Config.resolve(suryavanshi_settings)
    except (ValueError,TypeError) as exc: raise HTTPException(400,str(exc)) from exc
    contract = await resolve_contract(request, token, underlying, expiry, strike, side)
    try: rsi_config=RsiConfig.resolve(rsi_settings)
    except (ValueError,TypeError) as exc: raise HTTPException(400,str(exc)) from exc
    try: sutradhar_config=sutradhar.SutradharConfig.resolve(sutradhar_settings) if sutradhar_settings is not None else None
    except (ValueError,TypeError) as exc: raise HTTPException(400,str(exc)) from exc
    if not isfinite(atr_multiplier) or atr_multiplier < .1:
        raise HTTPException(400, 'SL ATR multiplier must be at least 0.1.')
    async def load():
        option_history = await history(request, token, contract['instrument_key'], interval)
        candles = option_history['candles']
        warnings = ['Signals describe the option premium, including PE; bullish means a rising premium, not a rising underlying.',
                    'Intraday option adaptations are not backtested. Time decay, volatility and liquidity can change outcomes.']
        if interval==10080:
            warnings.append('Weekly candles are aggregated from daily OHLCV, Monday to Sunday IST. The current week stays provisional until the next Monday. Contract listing history limits weekly signals.')
        if option_history['invalidCandles']:
            warnings.append('Invalid OHLCV found: analysis uses only the valid trailing segment and does not bridge invalid candles.')
        try:
            context_history = await history(request, token, underlying, interval)
            context = underlying_context(context_history['candles'], side)
            if context_history['invalidCandles']:
                warnings.append('Underlying history was shortened after invalid OHLCV.')
        except HTTPException:
            context = {'trend': 'UNAVAILABLE', 'supportsPremium': None, 'asOf': None, 'description': 'Underlying candle history is currently unavailable.'}
        results = await asyncio.to_thread(evaluate, candles, contract, interval)
        rsi_history=option_history if not rsi_config.timeframe or rsi_config.timeframe==interval else await history(request,token,contract['instrument_key'],rsi_config.timeframe)
        rsi_rows=rsi_history['candles']+([] if rsi_config.wait_close else rsi_history.get('formingCandles',[]))
        rsi=await asyncio.to_thread(rsi_overlay,rsi_rows,rsi_config)
        rsi['interval']=rsi_config.timeframe or interval
        results=[rsi_card(rsi,len(rsi_rows)) if r['id']=='rsi_divergence' else r for r in results]
        ghost_candles = (candles + option_history.get('formingCandles', []))[-1000:]
        five_candles = ghost_candles if interval == 5 else []
        if interval != 5:
            try:
                five_history = await history(request, token, contract['instrument_key'], 5)
                five_candles = five_history['candles'] + five_history.get('formingCandles', [])
            except HTTPException:
                warnings.append('5-minute history unavailable: Ghost Rider 5m RSI is n/a; its vote is not fabricated.')
        ghost = await asyncio.to_thread(ghost_overlay, ghost_candles, five_candles, interval, atr_multiplier)
        ghost['candles'] = [{**{k:v for k,v in row.items() if k != 'instrument_key'},'timestamp':row['timestamp'].isoformat()} for row in ghost_candles]
        ghost['developingBar'] = bool(option_history.get('formingCandles'))
        results = [strategy_card(ghost,len(ghost_candles)) if r['id']=='ghost_rider' else r for r in results]
        sury_data=await asyncio.to_thread(suryavanshi.calculate,ghost_candles,sury_config)
        sury_data['candles']=ghost['candles']
        results=[suryavanshi.strategy_card(sury_data,len(ghost_candles)) if r['id']=='suryavanshi' else r for r in results]
        golden_data=await asyncio.to_thread(golden_cross.calculate,candles,golden_config)
        golden_data['candles']=[dict(r,timestamp=r['timestamp'].isoformat()) for r in candles]
        results=[golden_cross.strategy_card(golden_data,len(candles)) if r['id']=='golden_death_cross' else r for r in results]
        sutradhar_data=None
        if sutradhar_config is not None:
            daily_rows=[]
            if interval<1440:
                try:
                    daily_history=await history(request,token,contract['instrument_key'],1440)
                    daily_rows=daily_history['candles']+daily_history.get('formingCandles',[])
                except HTTPException:
                    warnings.append('Sutradhar daily source is unavailable. Levels are not estimated.')
            sutradhar_data=await asyncio.to_thread(sutradhar.calculate,ghost_candles,daily_rows,interval,sutradhar_config)
            sutradhar_data['candles']=ghost['candles']
            results=[sutradhar.strategy_card(sutradhar_data,len(ghost_candles)) if r['id']=='sutradhar' else r for r in results]
        return {'contract': {'key': contract['instrument_key'], 'name': contract.get('trading_symbol', f'{strike} {side}'),
                             'underlyingKey': underlying, 'expiry': expiry.isoformat(), 'strike': strike, 'side': side},
                'interval': interval, 'candles': [{**{k: v for k, v in r.items() if k != 'instrument_key'},
                              'timestamp': r['timestamp'].isoformat()} for r in candles],
                'strategies': results, 'underlying': context, 'warnings': warnings, 'ghostRider': ghost, 'rsiDivergence':rsi, 'sutradhar':sutradhar_data, 'suryavanshi':sury_data, 'goldenCross':golden_data,
                'asOf': candles[-1]['timestamp'].isoformat() if candles else None,
                'receivedAt': datetime.now(timezone.utc).isoformat(),
                'historyMessage': f"{len(candles)} completed {OPTION_TIMEFRAMES[interval][3]} candles available within up to {option_history.get('lookbackDays',OPTION_TIMEFRAMES[interval][2])} calendar days of contract history. No gaps are filled."}
    return await option_market.cache.get(('option-analysis-golden-v2',json.dumps(golden_config,sort_keys=True),json.dumps(sury_config.__dict__,sort_keys=True), hashlib.sha256(token.encode()).hexdigest(),
                                          contract['instrument_key'], interval, atr_multiplier, json.dumps(rsi_config.__dict__,sort_keys=True),
                                          json.dumps(sutradhar_config.__dict__,sort_keys=True) if sutradhar_config is not None else None), 55, load)
