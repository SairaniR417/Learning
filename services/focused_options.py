"""On-demand, actual-contract premium plans for a Focused stock setup."""
from datetime import datetime,timedelta,timezone,date
from math import isfinite
from fastapi import HTTPException
from scanner.universe import require_fno_key,get_fno_stocks
from services import focused_plans as plans,option_analysis,option_market,stock_chart
from services.ghost_scanner import completed_rows


def wait(reason,**kw): return dict(action='WAIT',reason=reason,plan=None,**kw)


def quote_time(value):
    try:
        return datetime.fromtimestamp(float(value)/1000,timezone.utc)
    except (ValueError,TypeError,OverflowError):
        try: return plans.utc(value)
        except (ValueError,TypeError,AttributeError): return None


def liquid_quote(quote,lot,now):
    feed,trade=quote_time(quote.get('timestamp')),quote_time(quote.get('last_trade_time'))
    if feed is None or trade is None or not 0<=(now-feed).total_seconds()<=60 or not 0<=(now-trade).total_seconds()<=120:
        return None,'Option quote or last trade is stale; no premium entry.'
    try:
        bid=(quote['depth']['buy'][0]);ask=(quote['depth']['sell'][0])
        b,a=float(bid['price']),float(ask['price'])
        if not all(isfinite(v) for v in (a,b)) or not 0<b<=a or (a-b)/((a+b)/2)>.05 or min(bid['quantity'],ask['quantity'])<lot or quote['volume']<100 or quote['oi']<100:
            return None,'Option spread, depth, volume or open interest fails the liquidity check.'
        return dict(bid=b,ask=a,spreadPct=round((a-b)/((a+b)/2)*100,2),asOf=feed.isoformat(),lotSize=lot),None
    except (KeyError,IndexError,TypeError,ValueError): return None,'Option depth or liquidity data is missing.'


async def option_plan(key,mode,request,token,now=None,timeframe=None):
    require_fno_key(key)
    if mode not in plans.MODES: raise HTTPException(400,'Select Intraday or Swing.')
    real_clock=now is None
    now=now or datetime.now(timezone.utc)
    frame,interval=plans.execution_frame(mode,timeframe)
    local=now.astimezone(plans.INDIA)
    if local.weekday()>4 or not 9*60+15<=local.hour*60+local.minute<15*60:
        return wait('Market closed or outside entry hours. Check a live contract during the next session.')
    async def stock_rows(tf):
        response=await stock_chart.stock_chart(key,tf)
        return completed_rows([dict(r,timestamp=plans.utc(r['timestamp']),instrument_key=key) for r in response['candles']],tf,now)
    # Request broker history only for the one explicitly selected stock.
    daily=await stock_rows('1d');execution=await stock_rows(frame);five=await stock_rows('5m')
    if len(daily)<200 or len(execution)<60: return wait('Underlying history is incomplete. No option recommendation.')
    meta=next(s for s in get_fno_stocks() if s['key']==key)
    parent=plans.build_plan(execution,daily,five,meta,mode,now,timeframe=frame)
    if not parent['qualified']: return wait('Underlying setup is not qualified: '+parent['blockers'][0])
    # Swing bearish stocks legitimately have a WAIT cash-short restriction; a PUT
    # can be evaluated, but every other freshness/session restriction still applies.
    blocked=[r for r in parent['waitReasons'] if not r.startswith('Bearish swing:')]
    if blocked: return wait(blocked[0])
    side=parent['optionSide']
    minimum_days=2 if mode=='intraday' else 10
    expiries=await option_market.expiries(request,token,key)
    expiry=next((date.fromisoformat(d) for d in expiries['expiries'] if date.fromisoformat(d)>=local.date()+timedelta(days=minimum_days)),None)
    if expiry is None: return wait('No listed expiry leaves enough time for this holding policy.')
    chain=await option_market.chain(request,token,key,expiry)
    if not chain.get('spot'): return wait('Underlying spot quote unavailable; cannot choose an ATM contract.')
    leg_name='call' if side=='CE' else 'put'
    strikes=[]
    for row in sorted(chain['rows'],key=lambda r:abs(r['strike']-chain['spot']))[:3]:
        leg=row[leg_name];b=leg.get('bid_price');a=leg.get('ask_price')
        if b and a and 0<b<=a and (a-b)/((a+b)/2)<=.05 and (leg.get('volume') or 0)>=100 and (leg.get('oi') or 0)>=100:
            strikes.append(row)
    if not strikes: return wait('The three nearest strikes have no sufficiently liquid premium quote.')
    # Verify one listed contract rather than inventing a symbol or expiry.
    strike=strikes[0]['strike']
    contract=await option_analysis.resolve_contract(request,token,key,expiry,strike,side)
    lot=contract.get('lot_size')
    if not isinstance(lot,(int,float)) or isinstance(lot,bool) or not isfinite(lot) or lot<=0 or int(lot)!=lot:
        return wait('Contract lot size unavailable; no option entry.')
    history=await option_analysis.history(request,token,contract['instrument_key'],interval)
    daily_history=await option_analysis.history(request,token,contract['instrument_key'],1440)
    five_history=history if interval==5 else await option_analysis.history(request,token,contract['instrument_key'],5)
    rows=history['candles'];days=daily_history['candles']+daily_history.get('formingCandles',[]);small=five_history['candles']
    if len(rows)<60 or len(days)<15: return wait('This contract has insufficient premium history for the five-indicator plan.')
    checks,drivers,levels=plans.evidence(rows,days,small,interval,now)
    checks=[dict(c,direction='BUY',state='UNDERLYING_TREND',reason=f"Underlying daily trend supports buying {side}; this is not a cross on the premium chart.") if c['id']=='golden_death_cross' else c for c in checks]
    result=plans.build_plan(rows,days,small,dict(key=contract['instrument_key'],symbol=contract.get('trading_symbol',f'{meta["symbol"]} {strike} {side}'),name=meta['name']),mode,now,(checks,drivers,levels),'OPTION',timeframe=frame)
    if result['direction']!='BUY' or not result['qualified'] or result['action']=='WAIT':
        return wait('Premium setup is not ready: '+(result['waitReasons'][0] if result['waitReasons'] else 'premium indicators do not support buying.'),evidence=result['evidence'])
    payload=await option_market.limited_request(request,'https://api.upstox.com/v2/market-quote/quotes',headers={'Authorization':f'Bearer {token}'},params={'instrument_key':contract['instrument_key']})
    quotes=payload.get('data',{}) if isinstance(payload,dict) and payload.get('status')=='success' else {}
    quote=next((q for q in quotes.values() if q.get('instrument_token')==contract['instrument_key']),{})
    q,error=liquid_quote(quote,int(lot),datetime.now(timezone.utc) if real_clock else now)
    if error: return wait(error)
    p=result['plan'];ask=q['ask']
    if not p['entryMin']<=ask<=p['entryMax']: return wait('Ask premium has moved outside the entry zone. Wait for a fresh plan.',quote=q)
    risk=ask-p['stopLoss'];rr=(p['target1']-ask)/risk if risk>0 else 0
    if rr<1.5: return wait('Current ask leaves less than 1.5R to T1; wait.',quote=q)
    result['plan']=dict(p,entry=ask,riskPerUnit=round(risk,2),riskPct=round(risk/ask*100,2),rewardRisk=round(rr,2))
    return dict(action='BUY '+side,reason='Underlying and actual premium signals agree; quote and liquidity checks passed.',contract=dict(key=contract['instrument_key'],symbol=result['symbol'],expiry=expiry.isoformat(),strike=strike,side=side,lotSize=int(lot)),
                plan=result['plan'],quote=q,evidence=result['evidence'],holding=result['holding']+' Exit before expiry; SELL means closing a purchased option.',exitRule=result['exitRule'],asOf=result['asOf'],validUntil=min(plans.utc(result['validUntil']),now+timedelta(seconds=60)).isoformat(),
                estimatedPremiumPerLot=round(ask*lot,2),plannedRiskPerLot=round(risk*lot,2),maximumPremiumLossPerLot=round(ask*lot,2),note='Stop execution can slip; planned risk is not maximum loss. Premium targets use this contract, not the stock price. No order is placed.')
