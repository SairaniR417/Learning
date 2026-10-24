"""Mocked UI check: serve frontend/dist/market-desk/browser on 4309 and Chrome CDP on 9347."""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlparse
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.ghost_rider_overlay import calculate as calculate_ghost
from services.ghost_rider_overlay import strategy_card
from services.ghost_scanner import scan_row
from services.rsi_overlay import calculate as calculate_rsi, strategy_card as rsi_card
from scanner.strategies.rsi_divergence import RsiDivergenceStrategy
from scanner.strategies import strategy_registry
from services import sutradhar
from scanner.strategies.sutradhar import SutradharStrategy

import httpx
import websockets


async def main():
    now = datetime.now(timezone.utc)
    expiry = (now.date() + timedelta(days=20)).isoformat()
    candles = []
    for n in range(300):
        close = 100 + math.sin(n / 9) * 5
        candles.append(dict(timestamp=(now - timedelta(minutes=5 * (301 - n))).isoformat(), open=close-.1, high=close+1, low=close-1, close=close, volume=1000))
    midnight=now.astimezone(sutradhar.INDIA).replace(hour=0,minute=0,second=0,microsecond=0)
    daily=[dict(timestamp=midnight-timedelta(days=34-n),open=100+math.sin(n/4),high=105+n*.15,low=95-n*.1,close=100.,volume=1000) for n in range(35)]
    strategies = [dict(id=name, name=label, status='BUY', bias='bullish', minimumCandles=250, availableCandles=300,
                      metrics=[dict(label='EMA 9', value=100)], checks=[dict(label='Stop level untouched', passed=True)],
                      markers=[dict(timestamp=candles[-10]['timestamp'], label=label, bias='bullish')],
                      levels=[dict(label='Stop', price=95)], scenario='Example strategy evidence.', signalAt=candles[-10]['timestamp'])
                  for name, label in [('ghost_rider', 'Ghost Rider'), ('rsi_divergence', 'RSI Divergence'), ('ema_alignment', 'EMA Alignment'), ('golden_death_cross', 'Golden Cross'), ('multi_ma_bullish', 'Multi MA'), ('rsi_reversal', 'RSI Reversal')]]
    strategies.append(sutradhar.unloaded_card(5))
    key = 'NSE_INDEX|Nifty 50'
    leg = dict(ltp=100, oi=1000, volume=500, bid_price=99, ask_price=101, iv=20, delta=.5, gamma=.01, theta=-1, vega=2)
    errors, pending, requests = [], {}, []
    async with httpx.AsyncClient(trust_env=False) as client:
        targets = (await client.get('http://127.0.0.1:9347/json')).json()
    async with websockets.connect(next(t['webSocketDebuggerUrl'] for t in targets if t['type'] == 'page'), max_size=20_000_000, ping_interval=None) as ws:
        sequence = 0
        async def call(method, params=None):
            nonlocal sequence
            sequence += 1
            future = asyncio.get_running_loop().create_future()
            pending[sequence] = future
            await ws.send(json.dumps(dict(id=sequence, method=method, params=params or {})))
            return await asyncio.wait_for(future, 15)

        async def fulfill(event):
            path = urlparse(event['request']['url']).path
            requests.append(event['request']['url'])
            result = {}
            if path == '/api/status':
                result = dict(connected=True, configured=True)
            elif path == '/api/watchlists/notifications':
                result = dict(notifications=[], unread=0, monitor=dict(running=True, error=''))
            elif path == '/api/market/snapshot':
                result = dict(market='equities', name='F&O stocks', assets=[], chartKey='', chartSymbol='', receivedAt=1)
            elif path == '/api/options/underlyings':
                result = dict(underlyings=[dict(key=key, name='Nifty 50', symbol='NIFTY', group='Indices')])
            elif path == '/api/stocks/option-expiries':
                result = dict(expiries=[expiry])
            elif path == '/api/stocks/option-chain':
                result = dict(rows=[dict(strike=25000, call=leg, put=leg)], spot=25000, atmStrike=25000, expiry=expiry, receivedAt=now.isoformat())
            elif path == '/api/strategies':
                result = dict(strategies=strategy_registry.list_strategies())
            elif path == '/api/market/fno-stocks':
                result = dict(stocks=[],total=213)
            elif path == '/api/strategies/scan':
                stock_rows=[dict(c,instrument_key='NSE_EQ|INE002A01018',timestamp=datetime.fromisoformat(c['timestamp'])) for c in candles]
                body=json.loads(event['request'].get('postData','{}'))
                rsi_scan=body.get('strategy_id')=='rsi_divergence'
                row=(RsiDivergenceStrategy().run(__import__('polars').DataFrame(stock_rows),{'NSE_EQ|INE002A01018':dict(symbol='RELIANCE',name='Reliance Industries',exchange='NSE')},{'_timeframe':'5m','freshness':1000})[0] if rsi_scan else scan_row(stock_rows,stock_rows,dict(symbol='RELIANCE',name='Reliance Industries',exchange='NSE'),'5m',1.5))
                result=dict(strategy_id='rsi_divergence' if rsi_scan else 'ghost_rider',strategy_name='RSI Divergence' if rsi_scan else 'Ghost rider v.2',timeframe='5m',total_scanned=1,total_matched=1,scanned_at=now.isoformat(),cached=False,results=[row])
                if body.get('strategy_id')=='sutradhar':
                    result.update(strategy_id='sutradhar',strategy_name='Sutradhar',timeframe=body['timeframe'],results=SutradharStrategy().run(__import__('polars').DataFrame(stock_rows),{'NSE_EQ|INE002A01018':dict(symbol='RELIANCE',name='Reliance Industries',exchange='NSE')},{**body.get('params',{}),'_timeframe':body['timeframe'],'_daily_rows':{'NSE_EQ|INE002A01018':daily}}))
            elif path in {'/api/options/analysis','/api/stocks/ghost-rider','/api/stocks/rsi-divergence','/api/stocks/sutradhar'}:
                query = parse_qs(urlparse(event['request']['url']).query)
                ghost = calculate_ghost([dict(c,timestamp=datetime.fromisoformat(c['timestamp'])) for c in candles],
                    [dict(c,timestamp=datetime.fromisoformat(c['timestamp'])) for c in candles],
                    multiplier=float(query.get('atr_multiplier',['1.5'])[0]))
                result = dict(contract=dict(key='NSE_FO|123', name='NIFTY 25000 CE', underlyingKey=key, strike=25000, expiry=expiry, side='CE'),
                              interval=15 if 'interval=15' in event['request']['url'] else 5,
                              candles=candles, strategies=strategies, underlying=dict(trend='UP', supportsPremium=True, description='Underlying supports CE.', asOf=now.isoformat()),
                              warnings=[], ghostRider=ghost, historyMessage='300 completed candles.', asOf=now.isoformat(), receivedAt=now.isoformat())
                rsi=calculate_rsi([dict(c,timestamp=datetime.fromisoformat(c['timestamp'])) for c in candles],json.loads(query.get('rsi_settings',['{}'])[0]))
                rsi['interval']=int(query.get('interval',['5'])[0])
                result['rsiDivergence']=rsi
                result['strategies']=[rsi_card(rsi,len(candles)) if x['id']=='rsi_divergence' else x for x in result['strategies']]
                if 'sutradhar_settings' in query:
                    overlay=sutradhar.calculate([dict(c,timestamp=datetime.fromisoformat(c['timestamp'])) for c in candles],daily,settings=json.loads(query['sutradhar_settings'][0]))
                    result['sutradhar']=overlay
                    result['strategies']=[sutradhar.strategy_card(overlay,len(candles)) if x['id']=='sutradhar' else x for x in result['strategies']]
                if path=='/api/stocks/sutradhar':
                    result['contract']['name']='Reliance Industries'
                    result['strategies']=[sutradhar.strategy_card(result['sutradhar'],len(candles))]
                if path == '/api/stocks/rsi-divergence':
                    result['contract']['name']='Reliance Industries'
                    result['strategies']=[rsi_card(rsi,len(candles))]
                if path == '/api/stocks/ghost-rider':
                    result['contract']['name']='Reliance Industries'
                    result['strategies']=[strategy_card(ghost,len(candles))]
            await call('Fetch.fulfillRequest', dict(requestId=event['requestId'], responseCode=200,
                       responseHeaders=[dict(name='Content-Type', value='application/json'), dict(name='Access-Control-Allow-Origin', value='*'),
                                        dict(name='Access-Control-Allow-Methods',value='GET, POST, OPTIONS'),
                                        dict(name='Access-Control-Allow-Headers',value='Content-Type, Authorization')],
                       body=base64.b64encode(json.dumps(result).encode()).decode()))

        async def reader():
            async for raw in ws:
                message = json.loads(raw)
                if 'id' in message:
                    future = pending.pop(message['id'], None)
                    if future and not future.done():
                        future.set_result(message.get('result', {}))
                elif message.get('method') == 'Fetch.requestPaused':
                    asyncio.create_task(fulfill(message['params']))
                elif message.get('method') == 'Runtime.exceptionThrown':
                    errors.append(message['params']['exceptionDetails'])
        task = asyncio.create_task(reader())
        async def evaluate(expression):
            response = await call('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
            if response.get('exceptionDetails'):
                raise AssertionError(response['exceptionDetails'])
            return response.get('result', {}).get('value')
        async def until(expression):
            for _ in range(60):
                if await evaluate(expression):
                    return
                await asyncio.sleep(.2)
            body=await evaluate('document.body.innerText.slice(-7000)')
            raise AssertionError(f'{expression}\nUI: {body}\nErrors: {errors}\nRequests: {requests[-10:]}')
        await call('Runtime.enable')
        await call('Page.enable')
        await call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=900, deviceScaleFactor=1, mobile=False))
        await call('Fetch.enable', dict(patterns=[dict(urlPattern='*/api/*')]))
        await call('Page.navigate', dict(url='http://127.0.0.1:4309'))
        await until("!!document.querySelector('.primary-nav')")
        await evaluate("Array.from(document.querySelectorAll('.primary-nav button')).find(b=>b.textContent.trim()==='Option Chains').click()")
        await until("!!document.querySelector('.picker-trigger')")
        await evaluate("document.querySelector('.picker-trigger').click()")
        await until("!!document.querySelector('.picker-option')")
        await evaluate("document.querySelector('.picker-option').click()")
        await until("!!document.querySelector('.leg-select')")
        await evaluate("document.querySelector('.leg-select').click()")
        await until("document.querySelectorAll('.strategy-picker option').length === 7 && document.querySelectorAll('.strategies article').length === 1")
        assert await evaluate("!!document.querySelector('.chart canvas')")
        assert not await evaluate("!!document.querySelector('.chain-scroll')")
        assert await evaluate("document.querySelectorAll('.ghost-dashboard tr').length === 16")
        assert await evaluate("getComputedStyle(document.querySelectorAll('.ghost-dashboard tr')[3].children[0]).color === 'rgb(54, 58, 69)'")
        assert await evaluate("getComputedStyle(document.querySelectorAll('.ghost-dashboard tr')[3].children[0]).backgroundColor.startsWith('rgba(191, 192, 253,')")
        await evaluate("document.querySelector('[aria-label=\"Ghost Rider settings\"]').click()")
        await until("!!document.querySelector('.settings-dialog')")
        await evaluate("(()=>{const input=Array.from(document.querySelectorAll('.settings-content label')).find(l=>l.textContent.includes('SL ATR Multiplier')).querySelector('input');input.value='2';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.settings-dialog .ok').click();})()")
        await until("!document.querySelector('.settings-dialog') && !document.querySelector('[role=status]')")
        assert any('atr_multiplier=2' in r for r in requests), requests
        await evaluate("document.querySelector('[aria-label=\"Ghost Rider settings\"]').click()")
        await evaluate("document.querySelector('.settings-dialog footer button').click();document.querySelector('.settings-dialog .ok').click()")
        await until("!document.querySelector('[role=status]') && !!document.querySelector('.ghost-dashboard')")
        ratio = await evaluate("document.querySelector('.chart-column').getBoundingClientRect().width / document.querySelector('.strategy-column').getBoundingClientRect().width")
        assert abs(ratio - 2 / 3) < .02, ratio
        assert not any('sutradhar_settings' in r for r in requests)
        await evaluate("(()=>{const select=document.querySelector('.strategy-picker select');select.value='sutradhar';select.dispatchEvent(new Event('change',{bubbles:true}));})()")
        await until("!document.querySelector('[role=status]') && document.querySelectorAll('.sutradhar-values span').length===8")
        assert any('sutradhar_settings' in r for r in requests)
        assert await evaluate("document.querySelector('.strategies article').textContent.includes('LEVELS READY')")
        assert await evaluate("getComputedStyle(document.querySelector('.chart-panel')).backgroundColor==='rgb(0, 0, 0)'")
        await evaluate("document.querySelector('[aria-label=\"Sutradhar settings\"]').click()")
        await until("!!document.querySelector('[role=dialog][aria-label=\"Sutradhar settings\"]')")
        await evaluate("(()=>{const dialog=document.querySelector('[role=dialog]');const label=Array.from(dialog.querySelectorAll('label')).find(x=>x.textContent.includes('Use EMA'));label.querySelector('input').click();dialog.querySelector('.ok').click();})()")
        await until("!document.querySelector('[role=dialog]') && !document.querySelector('[role=status]')")
        assert await evaluate("document.querySelector('.sutradhar-status').textContent.includes('EMA')")
        await evaluate("document.querySelector('.chart-heading button:last-child').click()")
        await asyncio.sleep(.2)
        shot=await call('Page.captureScreenshot',dict(format='png'))
        Path('data/backups/sutradhar-review.png').write_bytes(base64.b64decode(shot['data']))
        await evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        before_style=len([r for r in requests if '/api/options/analysis' in r])
        await evaluate("document.querySelector('[aria-label=\"Sutradhar settings\"]').click();Array.from(document.querySelectorAll('[role=dialog] nav button')).find(b=>b.textContent==='Style').click()")
        await evaluate("(()=>{const dialog=document.querySelector('[role=dialog]');const label=Array.from(dialog.querySelectorAll('label')).find(x=>x.textContent.trim().startsWith('Flow'));label.querySelector('input[type=checkbox]').click();dialog.querySelector('.ok').click();})()")
        assert await evaluate("document.querySelectorAll('.sutradhar-values span').length===7")
        assert before_style==len([r for r in requests if '/api/options/analysis' in r])
        await evaluate("document.querySelector('[aria-label=\"Sutradhar settings\"]').click();Array.from(document.querySelectorAll('[role=dialog] nav button')).find(b=>b.textContent==='Visibility').click()")
        await evaluate("(()=>{const dialog=document.querySelector('[role=dialog]');const label=Array.from(dialog.querySelectorAll('label')).find(x=>x.textContent.trim().startsWith('Minutes'));label.querySelector('input[type=checkbox]').click();dialog.querySelector('.ok').click();})()")
        assert await evaluate("!document.querySelector('.sutradhar-values')")
        assert before_style==len([r for r in requests if '/api/options/analysis' in r])
        await evaluate("(()=>{const select=document.querySelector('.strategy-picker select');select.value='rsi_divergence';select.dispatchEvent(new Event('change',{bubbles:true}));})()")
        assert await evaluate("document.querySelector('.chart-heading').textContent.includes('RSI Divergence')")
        assert await evaluate("document.querySelector('.strategies article h3').textContent.includes('RSI Divergence')")
        await until("!!document.querySelector('app-rsi-pane.shared-rsi') && Array.from(document.querySelectorAll('.chart-stage .chart canvas')).filter(c=>c.getBoundingClientRect().width>200 && c.getBoundingClientRect().height>100).length>=4")
        assert await evaluate("document.querySelectorAll('.chart-stage .tv-lightweight-charts').length===1 && !document.querySelector('.chart-stage .chart').hidden")
        assert await evaluate("new Set(Array.from(document.querySelectorAll('.chart-stage .chart canvas')).filter(c=>c.getBoundingClientRect().width>200 && c.getBoundingClientRect().height>100).map(c=>Math.round(c.getBoundingClientRect().top))).size===2")
        assert await evaluate("getComputedStyle(document.querySelector('.chart-panel')).backgroundColor==='rgb(0, 0, 0)'")
        await evaluate("document.querySelector('[aria-label=\"RSI settings\"]').click()")
        await until("!!document.querySelector('[aria-label=\"RSI settings\"][role=dialog]')")
        await evaluate("(()=>{const dialog=document.querySelector('[role=dialog]');const label=Array.from(dialog.querySelectorAll('label')).find(x=>x.textContent.trim().startsWith('Type'));const select=label.querySelector('select');select.value='EMA';select.dispatchEvent(new Event('change',{bubbles:true}));dialog.querySelector('.ok').click();})()")
        await until("!document.querySelector('[role=dialog]') && !document.querySelector('[role=status]')")
        assert any('EMA' in url and 'rsi_settings' in url for url in requests)

        await evaluate("document.querySelector('.chart-heading button:last-child').click()")
        assert await evaluate("!!document.querySelector('.chart-panel.expanded') && document.body.style.overflow === 'hidden'")
        await asyncio.sleep(.2)
        shot=await call('Page.captureScreenshot',dict(format='png'))
        Path('data/backups/rsi-pane-review.png').write_bytes(base64.b64decode(shot['data']))
        await evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        assert await evaluate("!document.querySelector('.chart-panel.expanded') && document.body.style.overflow !== 'hidden'")
        await evaluate("(()=>{const select=document.querySelector('.strategy-picker select');select.value='ghost_rider';select.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('.chart-heading button:last-child').click();})()")
        await until("!!document.querySelector('.ghost-dashboard')")
        await asyncio.sleep(.3)
        screenshot = await call('Page.captureScreenshot',dict(format='png'))
        artifact = Path('data/backups/ghost-rider-review.png')
        artifact.parent.mkdir(parents=True,exist_ok=True)
        artifact.write_bytes(base64.b64decode(screenshot['data']))
        await evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));const select=document.querySelector('.strategy-picker select');select.value='rsi_divergence';select.dispatchEvent(new Event('change',{bubbles:true}));")
        await evaluate("(()=>{const select=document.querySelector('.controls select');select.value='15';select.dispatchEvent(new Event('change',{bubbles:true}));})()")
        await until("!document.querySelector('[role=status]') && document.querySelectorAll('.strategies article').length === 1")
        assert await evaluate("document.querySelector('.strategy-picker select').value === 'rsi_divergence'")
        assert any('/api/options/analysis' in r and 'interval=15' in r for r in requests)
        await evaluate("document.querySelector('.analysis-header button').click()")
        await until("!!document.querySelector('.chain-scroll')")
        await evaluate("Array.from(document.querySelectorAll('.primary-nav button')).find(b=>b.textContent.trim()==='Market Scanner').click()")
        await until("!!document.querySelector('.strategy-select option[value=ghost_rider]')")
        await evaluate("(()=>{const select=document.querySelector('.strategy-select');select.value='ghost_rider';select.dispatchEvent(new Event('change',{bubbles:true}));const frame=document.querySelector('.timeframe-label + select');frame.value='5m';frame.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('.run-scan').click();})()")
        await until("!!document.querySelector('.symbol-company-cell button')")
        await evaluate("document.querySelector('.symbol-company-cell button').click()")
        await until("document.querySelector('.analysis-header')?.textContent.includes('Reliance Industries')")
        assert any('/api/stocks/ghost-rider' in r and 'timeframe=5m' in r for r in requests)
        assert await evaluate("document.querySelectorAll('.ghost-dashboard tr').length===16 && document.querySelector('.chart-panel').classList.contains('ghost-dark-panel')")
        await evaluate("document.querySelector('.analysis-header button').click()")
        await until("!!document.querySelector('.symbol-company-cell button') && !document.querySelector('app-option-analysis')")
        await evaluate("(()=>{const select=document.querySelector('.strategy-select');select.value='rsi_divergence';select.dispatchEvent(new Event('change',{bubbles:true}));const freshness=Array.from(document.querySelectorAll('.strategy-params label')).find(x=>x.textContent.includes('within'));const input=freshness.querySelector('input');input.value='1000';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.run-scan').click();})()")
        await until("!!document.querySelector('.symbol-company-cell button')")
        await evaluate("document.querySelector('.symbol-company-cell button').click()")
        await until("!!document.querySelector('app-rsi-pane canvas')")
        assert any('/api/stocks/rsi-divergence' in r for r in requests)
        assert not await evaluate("document.querySelector('app-option-analysis').textContent.includes('Await close')")
        await evaluate("document.querySelector('.analysis-header button').click()")
        await until("!!document.querySelector('.strategy-select')")
        await evaluate("(()=>{const select=document.querySelector('.strategy-select');select.value='sutradhar';select.dispatchEvent(new Event('change',{bubbles:true}));})()")
        assert await evaluate("document.querySelector('.timeframe-label+select').value==='5m'")
        await evaluate("document.querySelector('.strategy-params input[type=checkbox]').click();document.querySelector('.run-scan').click()")
        await until("!!document.querySelector('.symbol-company-cell button')")
        await evaluate("document.querySelector('.symbol-company-cell button').click()")
        await until("document.querySelectorAll('.sutradhar-values span').length===8")
        assert any('/api/stocks/sutradhar' in r for r in requests)
        assert await evaluate("document.querySelector('.sutradhar-status').textContent.includes('EMA')")
        await evaluate("Array.from(document.querySelectorAll('.primary-nav button')).find(b=>b.textContent.trim()==='Overview').click()")
        await until("!document.querySelector('app-option-analysis')")
        assert not errors, errors
        print('Browser smoke passed: CE analysis; 40/60 layout; Ghost Rider and RSI; Sutradhar eight levels, dark overlay, EMA input, Style and Visibility without refetch, scanner chart, fullscreen and navigation; no runtime errors.')
        try:
            await call('Browser.close')
        except Exception:
            pass
        task.cancel()


if __name__ == '__main__':
    asyncio.run(main())
