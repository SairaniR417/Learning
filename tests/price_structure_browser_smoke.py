"""Headless desktop/mobile check against a local build and synthetic price history."""
import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlparse

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.price_structure import build
from services.research_dashboard import build as build_research


async def run(base, debug_port):
    now = datetime.now(timezone.utc)
    daily = [dict(timestamp=now-timedelta(days=420-i), open=100+i*.2,
                  high=105+i*.2+math.sin(i/5)*3, low=95+i*.2+math.sin(i/5)*3,
                  close=100+i*.2, volume=100000+i*20) for i in range(420)]
    hourly = [dict(daily[-50+i], timestamp=now.replace(hour=3, minute=45, second=0, microsecond=0)-timedelta(days=10-i//7)+timedelta(hours=i%7)) for i in range(50)]
    views = build(daily, hourly, now)
    research = build_research([dict(key=f'research-{i}',symbol=f'RESEARCH{i}',name='Synthetic research company',exchange='NSE') for i in range(14)],
                             {f'research-{i}':daily for i in range(14)}, {f'research-{i}':hourly for i in range(14)}, now)
    for view in views:
        view.update(source='Synthetic QA history', staleData=False, oldHistory=False, developingExcluded=0)
    fixture = dict(stock=dict(key='test-a', symbol='TEST A', name='Synthetic QA company'), views=views,
                   warnings=['Synthetic QA data, not actual stock prices.'], receivedAt=now.isoformat(),
                   historyContext=dict(count=420, firstDate=daily[0]['timestamp'].isoformat(), asOf=daily[-1]['timestamp'].isoformat(), narrative=['Synthetic longer-term context.']),
                   methodology='Synthetic test fixture.')
    async with httpx.AsyncClient(trust_env=False) as client:
        for _ in range(80):
            try:
                targets = (await client.get(f'http://127.0.0.1:{debug_port}/json')).json()
                break
            except httpx.HTTPError:
                await asyncio.sleep(.1)
        else:
            raise AssertionError('Headless browser did not start')
    websocket = next(t['webSocketDebuggerUrl'] for t in targets if t['type'] == 'page')
    pending = {}; sequence = 0; errors = []; requests = []; signal_frames = []; index_frames = []; chain_keys = []
    async with websockets.connect(websocket, max_size=8_000_000) as ws:
        async def call(method, params=None):
            nonlocal sequence
            sequence += 1
            future = asyncio.get_running_loop().create_future()
            pending[sequence] = future
            await ws.send(json.dumps(dict(id=sequence, method=method, params=params or {})))
            response = await asyncio.wait_for(future, 20)
            if 'error' in response:
                raise RuntimeError(response['error'])
            return response.get('result', {})

        async def intercept(params):
            import base64
            path = urlparse(params['request']['url']).path
            requests.append(path)
            payload = dict(stocks=[], assets=[], receivedAt=0, indices=[], connected=False, configured=False)
            status = 200
            if path == '/api/market/fno-stocks':
                payload = dict(stocks=[dict(key='test-a', symbol='TEST A', name='Synthetic QA company'), dict(key='test-b', symbol='TEST B', name='Missing history company')], total=2)
            elif path == '/api/research/dashboard':
                payload = research
            elif path == '/api/options/underlyings':
                commodities = parse_qs(urlparse(params['request']['url']).query).get('commodities',['false'])[0]=='true'
                payload = dict(underlyings=[dict(key='MCX_FUT|GOLD-A',symbol='GOLD',name='Gold November futures',group='Commodities'),dict(key='MCX_FUT|GOLD-B',symbol='GOLD',name='Gold December futures',group='Commodities')] if commodities else [dict(key='NSE_INDEX|Nifty 50',symbol='NIFTY',name='Nifty 50',group='Indices')])
            elif path == '/api/stocks/option-expiries':
                payload = dict(expiries=['2026-12-31'])
            elif path == '/api/stocks/option-chain':
                chain_keys.append(parse_qs(urlparse(params['request']['url']).query).get('instrument_key',[''])[0])
                leg=dict(oi=1000,volume=100,iv=15,bid_price=10,ask_price=11,ltp=10.5)
                payload = dict(rows=[dict(strike=100,call=leg,put=leg)],spot=100,atmStrike=100,expiry='2026-12-31',receivedAt=now.isoformat())
            elif path == '/api/strategies':
                payload = dict(strategies=[dict(id='ghost_rider', name='Ghost Rider', description='Synthetic strategy fixture', min_candles=20, parameters=[]),dict(id='ema_sma_alignment', name='EMA alignment', description='Synthetic MA fixture', min_candles=20, parameters=[])])
                payload['strategies'].append(dict(id='golden_death_cross', name='Golden Cross', description='Synthetic cross fixture', min_candles=201, parameters=[]))
                payload['strategies'].append(dict(id='institution_transaction', name='Institution Transaction', description='Possible price/volume pressure; disclosures not checked.', min_candles=21, parameters=[]))
            elif path == '/api/market/ema-indicators':
                payload = dict(scanned=20, indicators=[dict(instrumentKey=f'test-{i}', symbol=f'TEST{i}', name=f'Synthetic company {i}', close=100+i, previousClose=99+i, changePct=1, volume=100000, ema9=99+i, ema20=98+i, sma50=97+i, sma200=96+i, historySufficient=True) for i in range(20)])
            elif path == '/api/strategies/scan':
                selected_strategy=json.loads(params['request'].get('postData','{}')).get('strategy_id','ghost_rider')
                payload = dict(total_scanned=20, results=[dict(instrumentKey=f'test-{i}',symbol=f'TEST{i}',name=f'Synthetic company {i}',strategyId=selected_strategy,close=100+i,volume=100000,changePct=1,signal='BUY',status='ALIGNED',state='CURRENT_SETUP',decision='WAIT',sessionDate='2026-11-13',signalAt=now.isoformat(),asOf=now.isoformat(),ema9=99+i,ema20=98+i,sma50=97+i,sma200=96+i) for i in range(20)], coverage=[], errors=[])
                if selected_strategy == 'golden_death_cross':
                    for row in payload['results']:
                        row.update(crossType='GOLDEN_CROSS', state='CROSS_ACTIVE', smaMediumPeriod=50, smaLongPeriod=200, sma50=105, sma200=100, barsSinceCross=3, crossTime=now.isoformat(), requireConfirmation=False)
                if selected_strategy == 'ghost_rider':
                    for row in payload['results']:
                        row.update(ema20=row['close']-1,ema50=row['close']+1,sma200=row['close'],stopLoss=row['close']-5,tp1=row['close']+5,nextTarget='TP1',nextTargetPct=5,remainingRR=2,rrTarget='TP2')
                if selected_strategy == 'institution_transaction':
                    for row in payload['results']:
                        row.update(status='BUYING WATCH',state='BUYING WATCH',signal='WATCH',pressureViews={'1d':dict(state='BUYING'),'1h':dict(state='UNAVAILABLE')},pressureExplanation='Daily: BUYING; relative volume 2.1x. 1 Hour: UNAVAILABLE. Institutional disclosures: NOT CHECKED.',disclosureStatus='Not checked',institutionalConfirmed=False)
            elif path == '/api/market/snapshot':
                payload = dict(market='equities', assets=[], receivedAt=now.timestamp()*1000)
            elif path == '/api/market/overview-signals':
                frame = parse_qs(urlparse(params['request']['url']).query)['timeframe'][0]
                signal_frames.append(frame)
                payload = dict(stocks=[dict(key='test-a',symbol='TEST A',name='Synthetic QA company',price=110,vwap=108,sma20=105,sma50=100,vwapPosition='above',sma20Position='above',sma50Position='above',maTrend='above',crossover='bullish',bars=60,asOf=now.isoformat())], timeframe=frame, source='Synthetic history', vwapLabel='Session VWAP', fetchedAt=now.isoformat())
            elif path in ('/api/stocks/analysis','/api/market/analysis'):
                if path == '/api/market/analysis':
                    index_frames.append(parse_qs(urlparse(params['request']['url']).query)['timeframe'][0])
                payload = dict(contract=dict(key='test-a',name='TEST A · Synthetic QA company',underlyingKey='test-a',expiry='',strike=0,side='CE'),interval=1440,
                               candles=[dict(row,timestamp=row['timestamp'].isoformat()) for row in daily[-100:]],
                               strategies=[dict(id='golden_death_cross',name='Golden Cross / Death Cross',status='CROSS_ACTIVE',bias='bullish',minimumCandles=201,availableCandles=420,scenario='Synthetic QA crossover. The chart and this explanation use the selected timeframe and the stored history.',signalAt=now.isoformat(),metrics=[dict(label='SMA 50',value=180),dict(label='SMA 200',value=160)],checks=[],markers=[],levels=[])],
                               underlying=dict(trend='UP',supportsPremium=None,asOf=now.isoformat(),description='Synthetic stock close relative to EMA 20; strategy signals refer to the underlying price.'),
                               warnings=['Synthetic QA history.'],historyMessage='Stored history for layout verification.',asOf=now.isoformat(),receivedAt=now.isoformat())
                if path == '/api/market/analysis':
                    payload['strategies'][0].update(id='ghost_rider',name='Ghost Rider')
            elif path == '/api/market/chart-quote':
                payload = dict(price=1903.3,receivedAt=now.isoformat())
            elif path in ('/api/stocks/chart', '/api/stocks/history', '/api/stocks/news'):
                status = 503
                payload = dict(detail='Synthetic QA: stock data unavailable')
            elif path == '/api/quotes':
                payload = dict(data={})
            elif path == '/api/focused/structure':
                payload = fixture if 'test-a' in params['request']['url'] else dict(detail='Synthetic history failure')
                status = 200 if payload is fixture else 503
            elif path == '/api/watchlists/notifications':
                payload = dict(notifications=[], unread=0, monitor=dict(running=False, lastCheck=None, error=''))
            await call('Fetch.fulfillRequest', dict(requestId=params['requestId'], responseCode=status,
                       responseHeaders=[dict(name='Content-Type', value='application/json')],
                       body=base64.b64encode(json.dumps(payload).encode()).decode()))

        async def receive():
            async for raw in ws:
                event = json.loads(raw)
                if 'id' in event:
                    future = pending.pop(event['id'], None)
                    if future and not future.done():
                        future.set_result(event)
                elif event.get('method') == 'Fetch.requestPaused':
                    asyncio.create_task(intercept(event['params']))
                elif event.get('method') == 'Runtime.exceptionThrown':
                    errors.append(event['params']['exceptionDetails'])

        receiver = asyncio.create_task(receive())
        async def js(expression):
            result = await call('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
            assert 'exceptionDetails' not in result, result
            return result['result'].get('value')

        async def until(expression):
            for _ in range(80):
                assert not errors, errors
                value = await js(expression)
                if value:
                    return value
                await asyncio.sleep(.1)
            raise AssertionError('Timed out: ' + expression + '\n' + str(await js("document.querySelector('.research')?.innerText || document.body.innerText"))[:3000])

        await call('Runtime.enable')
        await call('Page.addScriptToEvaluateOnNewDocument', dict(source="localStorage.setItem('traders-gita-navigation-order', JSON.stringify(['Overview','F&O Stocks','Market Scanner','Focused','Stock Details','Option Chains','Watchlist','Trade Journal','Learning']));"))
        await call('Fetch.enable', dict(patterns=[dict(urlPattern='*/api/*')]))
        await call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=900, deviceScaleFactor=1, mobile=False))
        await call('Page.navigate', dict(url=base))
        await until("Array.from(document.querySelectorAll('.primary-nav button')).some(b=>b.textContent.trim()==='Focused')")
        await until("document.querySelectorAll('.scanner-page .ag-row').length>0")
        assert await js("document.querySelector('select[aria-label=Strategy]').value==='ghost_rider'"), 'Ghost Rider must be selected when the screener opens'
        assert await js("!!document.querySelector('.scanner-page .ag-cell[col-id=dayOpen]')"), 'Default Ghost Rider results did not load'
        assert await js("!!document.querySelector('.scanner-page .ag-cell[col-id=price]')"), 'Ghost Rider must retain the latest price column'
        scan_count = requests.count('/api/strategies/scan')
        await js("(()=>{const s=document.querySelector('select[aria-label=Sector]');s.value='Banking & Finance';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelector('.scanner-page').innerText.includes('No instruments match these filters')")
        await js("(()=>{const s=document.querySelector('select[aria-label=Sector]');s.value='All sectors';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelectorAll('.scanner-page .ag-row').length>0")
        assert requests.count('/api/strategies/scan') == scan_count, 'Sector changes should filter immediately without fetching again'
        for field in ('sessionDate','dayHighPct','dayLowPct','nearestLevel','decision','tp1','tp2','stopLoss'):
            assert await js(f"!document.querySelector('.scanner-page .ag-header-cell[col-id={field}]')"), f'{field} should be hidden by default'
        assert await js("['symbolCompany','status','dayOpen','changePct','orbState','adx','rsi14','macdMain','vwap','actions'].every(id=>{const r=document.querySelector('.scanner-page .ag-header-cell[col-id='+id+']')?.getBoundingClientRect();return r && r.width>0 && r.left>=0 && r.right<=window.innerWidth;})"), 'Priority Ghost columns must fit on desktop without horizontal scrolling'
        screenshot=await call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False))
        import base64
        (ROOT/'frontend/dist'/'ghost-priority-ui.png').write_bytes(base64.b64decode(screenshot['data']))
        await js("(()=>{const s=document.querySelector('.scanner-page .ag-body-horizontal-scroll-viewport');s.scrollLeft=s.scrollWidth;})()")
        await until("document.querySelector('.scanner-page .ag-cell[col-id=ema20Position]')?.textContent.includes('Above EMA 20')")
        await until("document.querySelector('.scanner-page .ag-cell[col-id=ema50Position]')?.textContent.includes('Below EMA 50')")
        await until("document.querySelector('.scanner-page .ag-cell[col-id=sma200Position]')?.textContent.includes('At SMA 200')")
        assert await js("document.querySelector('.scanner-page .ag-cell[col-id=ema50Position]').title.includes('EMA50')"), 'MA tooltip must include its actual value'
        await js("document.querySelector('.scanner-page .ag-body-horizontal-scroll-viewport').scrollLeft=0")
        await js("document.querySelector('.grid-tool-rail button[aria-label=Columns]').click()")
        await js("Array.from(document.querySelectorAll('.column-option')).find(l=>l.textContent.includes('Session (IST)')).querySelector('input').click()")
        await js("(()=>{const s=document.querySelector('.scanner-page .ag-body-horizontal-scroll-viewport');s.scrollLeft=s.scrollWidth;})()")
        await until("!!document.querySelector('.scanner-page .ag-header-cell[col-id=sessionDate]')")
        await js("Array.from(document.querySelectorAll('.column-option')).find(l=>l.textContent.includes('Session (IST)')).querySelector('input').click()")
        await js("document.querySelector('.grid-tool-panel button[aria-label=\"Close panel\"]').click()")
        nav_text = await js("document.querySelector('.primary-nav').innerText")
        assert 'Overview' not in nav_text and 'F&O Stocks' not in nav_text, 'Removed tabs returned from saved navigation'
        assert await js("document.querySelectorAll('.factor-sidebar').length===0"), 'Screener sidebar remains'
        assert await js("document.querySelector('.scanner-page .market-grid').getBoundingClientRect().width>window.innerWidth*.9"), 'Table does not fill the page'
        assert await js("document.querySelector('.scan-controls').getBoundingClientRect().bottom<document.querySelector('.scanner-page .market-grid').getBoundingClientRect().top"), 'Strategy/timeframe controls must be above table'
        await js("(()=>{const s=document.querySelector('select[aria-label=Strategy]');s.value='ghost_rider';s.dispatchEvent(new Event('change'));})()")
        assert await js("!document.querySelector('select[aria-label=Timeframe]').disabled")
        await js("(()=>{const s=document.querySelector('select[aria-label=Timeframe]');s.value='1h';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelectorAll('.scanner-page .ag-row').length>0")
        assert await js("Array.from(document.querySelectorAll('.scanner-page .ag-row')).every(r=>r.getBoundingClientRect().height<=40)"), 'Strategy rows should remain compact'
        assert await js("Array.from(document.querySelectorAll('.scanner-page .ag-cell[col-id=actions] button')).every(b=>b.getBoundingClientRect().height<=28)"), 'Action buttons inherit excessive cell line height'
        await js("(()=>{const s=document.querySelector('select[aria-label=Strategy]');s.value='ema_sma_alignment';s.dispatchEvent(new Event('change'));})()")
        await until("!!document.querySelector('.scanner-page .ag-cell[col-id=detail]')")
        assert await js("Array.from(document.querySelectorAll('.scanner-page .ag-row')).every(r=>r.getBoundingClientRect().height<=40)"), 'Signal details must not expand rows'
        await js("(()=>{const s=document.querySelector('select[aria-label=Strategy]');s.value='golden_death_cross';s.dispatchEvent(new Event('change'));})()")
        await until("Array.from(document.querySelectorAll('.ag-cell[col-id=detail] span')).some(s=>s.textContent.includes('Golden Cross'))")
        cross_hover = await js("Array.from(document.querySelectorAll('.ag-cell[col-id=detail] span')).find(s=>s.textContent.includes('Golden Cross')).title")
        assert 'SMA 50 crossed above SMA 200' in cross_hover and '3 completed candles ago' in cross_hover, cross_hover
        assert await js("Array.from(document.querySelectorAll('.ag-cell[col-id=detail] span')).find(s=>s.textContent==='CROSS ACTIVE').title.includes('does not mean a fresh crossing')"), 'Active cross explanation missing'
        await js("document.querySelector('.scanner-page .ag-cell[col-id=price]').click()")
        await js("Array.from(document.querySelectorAll('.ag-cell[col-id=detail] span')).find(s=>s.textContent.includes('Golden Cross')).click()")
        await js("document.querySelector('.scanner-page .ag-cell[col-id=symbolCompany] span').click()")
        assert await js("!document.querySelector('app-ema-scanner app-option-analysis') && !document.querySelector('.scanner-page').hidden"), 'Row, stock name or badge click unexpectedly opened analysis'
        assert await js("document.querySelector('.scanner-page .ag-cell[col-id=price]').outerHTML.includes('SMA 50 crossed above SMA 200')"), await js("document.querySelector('.scanner-page .ag-cell[col-id=price]').outerHTML")
        await js("Array.from(document.querySelectorAll('.scanner-page .ag-cell[col-id=actions] button')).find(b=>b.textContent==='Chart').click()")
        await until("!!document.querySelector('app-ema-scanner app-option-analysis')")
        await until("!!document.querySelector('app-ema-scanner app-option-analysis .strategies article')")
        for width in (1440,1920,390):
            await call('Emulation.setDeviceMetricsOverride', dict(width=width, height=1000, deviceScaleFactor=1, mobile=width<500))
            await asyncio.sleep(.2)
            assert await js("document.querySelector('.analysis').scrollWidth<=document.querySelector('.analysis').clientWidth"), f'Analysis overflow at {width}'
            if width>=1000:
                assert await js("document.querySelector('.chart-column').getBoundingClientRect().width>document.querySelector('.strategy-column').getBoundingClientRect().width*1.7"), 'Chart must have the larger share of the workspace'
                assert await js("Math.abs(document.querySelector('.chart-panel').getBoundingClientRect().top-document.querySelector('.strategy-column').getBoundingClientRect().top)<2"), 'Analysis panels must align at the top'
            screenshot=await call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False))
            import base64
            (ROOT/'frontend/dist'/f'analysis-ui-{width}.png').write_bytes(base64.b64decode(screenshot['data']))
        await call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=900, deviceScaleFactor=1, mobile=False))
        await js("Array.from(document.querySelectorAll('app-ema-scanner app-option-analysis button')).find(b=>b.textContent.includes('Back')).click()")
        await until("!document.querySelector('app-ema-scanner app-option-analysis')")
        await js("(()=>{const s=document.querySelector('select[aria-label=Strategy]');s.value='institution_transaction';s.dispatchEvent(new Event('change'));})()")
        assert await js("Array.from(document.querySelector('select[aria-label=Timeframe]').options).map(o=>o.value).sort().join(',')==='1d,1h'"), 'Institution strategy must only offer supported timeframes'
        await until("Array.from(document.querySelectorAll('.ag-cell[col-id=detail] span')).some(s=>s.textContent==='Daily: BUYING')")
        assert await js("Array.from(document.querySelectorAll('.ag-cell[col-id=detail] span')).find(s=>s.textContent==='Daily: BUYING').title.includes('NOT CHECKED')"), 'Pressure must never imply confirmed institutional activity'
        assert await js("Array.from(document.querySelectorAll('.ag-cell[col-id=detail] span')).some(s=>s.textContent==='Disclosures: Not checked')"), 'Disclosure availability must remain visible'
        assert await js("Array.from(document.querySelectorAll('.scanner-page .ag-row')).every(r=>r.getBoundingClientRect().height<=40)"), 'Hover details must preserve compact rows'
        await js("(()=>{const s=document.querySelector('select[aria-label=Strategy]');s.value='market_screener';s.dispatchEvent(new Event('change'));})()")
        assert await js("document.querySelector('select[aria-label=Timeframe]').value==='1d' && document.querySelector('select[aria-label=Timeframe]').disabled"), 'Daily-only screener has an invalid timeframe'
        await until("document.querySelectorAll('.scanner-page .ag-row').length>0")
        # Research dashboards live under Strategies and never call the scan API.
        scan_count = requests.count('/api/strategies/scan')
        await js("(()=>{const s=document.querySelector('select[aria-label=Strategy]');s.value='research_radar';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelector('.research .stats')?.textContent.includes('ALIGNED BULLISH')")
        assert await js("!document.querySelector('select[aria-label=Timeframe]')"), 'Research must use its own timeframe controls'
        for view, label in [('research_cpr','CPR & Sutradhar'),('research_camarilla','Camarilla levels'),('research_wall','Chart wall'),('research_stock','Stock intelligence'),('research_trends','Trendline scanner'),('research_scenarios','Trade scenarios')]:
            await js(f"Array.from(document.querySelectorAll('.research .view-nav button')).find(b=>b.textContent.trim()==={json.dumps(label)}).click()")
            await until(f"document.querySelector('select[aria-label=Strategy]').value==={json.dumps(view)}")
            assert await js("!document.querySelector('.research .error')"), f'Research view failed: {view}'
            if view == 'research_wall':
                assert await js("document.querySelectorAll('.research app-research-chart').length===12"), 'Chart wall needs bounded pagination'
                await js("Array.from(document.querySelectorAll('.research .pagination button')).find(b=>b.textContent==='Next').click()")
                await until("document.querySelectorAll('.research app-research-chart').length===2")
            if view == 'research_cpr':
                await until("document.querySelector('.research select[aria-label=\"Choose research stock\"]')?.options.length===15")
                await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Choose research stock\"]');s.value='RESEARCH13';s.dispatchEvent(new Event('change'));})()")
                await until("document.querySelectorAll('.research .wide-table tbody tr').length===1 && Array.from(document.querySelectorAll('.research .panel h3')).some(h=>h.textContent.includes('RESEARCH13'))")
                await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Choose research stock\"]');s.value='';s.dispatchEvent(new Event('change'));})()")
                await until("document.querySelectorAll('.research .wide-table tbody tr').length===14")
                await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Choose research stock\"]');s.value='RESEARCH2';s.dispatchEvent(new Event('change'));})()")
                await until("document.querySelectorAll('.research .wide-table tbody tr').length===1")
                await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Choose research stock\"]');s.value='';s.dispatchEvent(new Event('change'));})()")
            if view == 'research_scenarios':
                await js("(()=>{const inputs=document.querySelectorAll('.research .leg input');[100,3,1,110,1,1].forEach((v,i)=>{inputs[i].value=v;inputs[i].dispatchEvent(new Event('input'));});})()")
                await until("!!document.querySelector('.research .payoff polyline')")
                for width in (1440,390):
                    await call('Emulation.setDeviceMetricsOverride', dict(width=width,height=900,deviceScaleFactor=1,mobile=width<500))
                    await asyncio.sleep(.3)
                    assert await js("document.querySelector('.research').scrollWidth<=document.querySelector('.research').clientWidth"), f'Research overflow at {width}'
                    screenshot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))
                    (ROOT/'frontend/dist'/f'research-ui-{width}.png').write_bytes(base64.b64decode(screenshot['data']))
                await call('Emulation.setDeviceMetricsOverride', dict(width=1440,height=900,deviceScaleFactor=1,mobile=False))
        await js("Array.from(document.querySelectorAll('.research .view-nav button')).find(b=>b.textContent.trim()==='Index intelligence').click()")
        await until("!!document.querySelector('.research app-option-analysis .strategies article')")
        assert index_frames == ['1h'], index_frames
        assert await js("document.querySelector('.research .analysis .controls select').value==='1h'"), 'Index timeframe label and API request must agree'
        await js("(()=>{const s=document.querySelector('.research .analysis .controls select');s.value='1w';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelector('.research .analysis .controls select').value==='1w' && !document.querySelector('.research .analysis .controls button').disabled")
        assert index_frames[-1] == '1w', index_frames
        await js("Array.from(document.querySelectorAll('.research .segmented button')).find(b=>b.textContent.trim()==='Live option chain').click()")
        await until("!!document.querySelector('.research app-option-chain')")
        assert requests.count('/api/strategies/scan') == scan_count, 'Research selection must not submit an unregistered strategy'
        assert requests.count('/api/research/dashboard') == 1, 'Switching research views should reuse its snapshot'
        await js("Array.from(document.querySelectorAll('.research .view-nav button')).find(b=>b.textContent.trim()==='CPR & Sutradhar').click()")
        await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Market for Choose research stock\"]');s.value='Indices';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelector('.research select[aria-label=\"Choose research stock\"]')?.options.length===2")
        await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Choose research stock\"]');s.value='NSE_INDEX|Nifty 50';s.dispatchEvent(new Event('change'));})()")
        await until("!!document.querySelector('.research dialog[open] .chain-scroll tbody tr')")
        assert await js("document.querySelector('.research dialog[open]').textContent.includes('Nifty 50')"), 'Index chain must identify its underlying'
        await js("document.querySelector('.research dialog[open] button[aria-label=\"Close option chain\"]').click()")
        await until("!document.querySelector('.research dialog[open]')")
        await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Market for Choose research stock\"]');s.value='Commodities';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelector('.research select[aria-label=\"Choose research stock\"]')?.options.length===3")
        await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Choose research stock\"]');s.value='MCX_FUT|GOLD-B';s.dispatchEvent(new Event('change'));})()")
        await until("!!document.querySelector('.research dialog[open] .chain-scroll tbody tr')")
        assert await js("document.querySelector('.research dialog[open]').textContent.includes('Gold December')"), 'Commodity chain must use the selected expiry contract'
        for width in (1440,390):
            await call('Emulation.setDeviceMetricsOverride',dict(width=width,height=900,deviceScaleFactor=1,mobile=width<500))
            assert await js("document.querySelector('.research dialog[open]').getBoundingClientRect().width<=window.innerWidth"), 'Option dialog must fit viewport'
        await js("document.querySelector('.research dialog[open] button[aria-label=\"Close option chain\"]').click()")
        await call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=900,deviceScaleFactor=1,mobile=False))
        await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Market for Choose research stock\"]');s.value='Stocks';s.dispatchEvent(new Event('change'));})()")
        await js("(()=>{const s=document.querySelector('.research select[aria-label=\"Choose research stock\"]');s.value='RESEARCH13';s.dispatchEvent(new Event('change'));})()")
        await js("document.querySelector('.research app-stock-choices button.options').click()")
        await until("!!document.querySelector('.research dialog[open] .chain-scroll tbody tr')")
        await js("document.querySelector('.research dialog[open] button[aria-label=\"Close option chain\"]').click()")
        assert 'NSE_INDEX|Nifty 50' in chain_keys and 'MCX_FUT|GOLD-B' in chain_keys and 'research-13' in chain_keys, chain_keys
        await js("(()=>{const s=document.querySelector('select[aria-label=Strategy]');s.value='market_screener';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelectorAll('.scanner-page .ag-row').length>0")
        await js("Array.from(document.querySelectorAll('.market-workspace-tabs button')).find(b=>b.textContent.includes('Heat map')).click()")
        await until("!!document.querySelector('.heat-panel')")
        await js("Array.from(document.querySelectorAll('.market-workspace-tabs button')).find(b=>b.textContent.includes('VWAP')).click()")
        await until("!!document.querySelector('app-overview-signals')")
        await until("document.querySelector('.signals-heading select')?.value==='1h'")
        await until("document.querySelector('.signals-heading button')?.disabled===false")
        assert signal_frames == ['1h'], f'Initial signal request must use 1h: {signal_frames}'
        await until("document.querySelector('select[aria-label=\"Choose VWAP and MA stock\"]')?.options.length===2")
        await js("(()=>{const s=document.querySelector('select[aria-label=\"Choose VWAP and MA stock\"]');s.value='TEST A';s.dispatchEvent(new Event('change'));})()")
        assert await js("document.querySelector('app-overview-signals input[type=search]').value==='TEST A'"), 'Choosing a stock must update its search'
        await js("(()=>{const s=document.querySelector('select[aria-label=\"Choose VWAP and MA stock\"]');s.value='';s.dispatchEvent(new Event('change'));})()")
        assert await js("document.querySelector('app-overview-signals td:nth-child(7)').title.includes('SMA 20 crossed above SMA 50')"), 'VWAP/MA crossover explanation missing'
        assert await js("document.querySelector('app-overview-signals td:nth-child(3)').title.includes('Session VWAP 108')"), 'VWAP position explanation missing'
        await js("(()=>{const s=document.querySelector('.signals-heading select');s.value='15m';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelector('.signals-heading select')?.value==='15m' && document.querySelector('.signals-heading button')?.disabled===false")
        assert signal_frames[-1] == '15m', 'Dropdown and requested signal timeframe differ'
        await js("Array.from(document.querySelectorAll('.market-workspace-tabs button')).find(b=>b.textContent.trim()==='Screener').click()")
        await js("Array.from(document.querySelectorAll('.market-workspace-tabs button')).find(b=>b.textContent.includes('VWAP')).click()")
        await until("document.querySelector('.signals-heading select')?.value==='1h'")
        await until("document.querySelector('.signals-heading button')?.disabled===false")
        assert signal_frames[-1] == '1h', 'Reopening signals should default to 1h'
        await js("Array.from(document.querySelectorAll('.market-workspace-tabs button')).find(b=>b.textContent.trim()==='Screener').click()")
        assert await js("document.querySelectorAll('.scanner-page .ag-row').length>0"), 'Scan state lost between merged views'
        for width in (1440, 390):
            await call('Emulation.setDeviceMetricsOverride', dict(width=width, height=900, deviceScaleFactor=1, mobile=width<500))
            await asyncio.sleep(.2)
            assert await js("document.querySelector('.scanner-page').scrollWidth<=document.querySelector('.scanner-page').clientWidth"), f'Screener overflow at {width}'
            screenshot=await call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False))
            import base64
            (ROOT/'frontend/dist'/f'screener-ui-{width}.png').write_bytes(base64.b64decode(screenshot['data']))
            if width==390:
                assert await js("['symbolCompany','price'].every(id=>{const r=document.querySelector('.scanner-page .ag-cell[col-id='+id+']')?.getBoundingClientRect();return r&&r.width>0&&r.left>=0&&r.right<=window.innerWidth;})"), 'Mobile table must show both stock name and price without horizontal scrolling'
        await call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=900, deviceScaleFactor=1, mobile=False))
        await js("Array.from(document.querySelectorAll('.primary-nav button')).find(b=>b.textContent.trim()==='Stock Details').click()")
        await until("document.querySelector('.stock-dropdown select[aria-label^=Select]')?.options.length===3")
        await js("(()=>{const s=document.querySelector('#stock-details-search');s.value='missing';s.dispatchEvent(new Event('input'));})()")
        assert await js("document.querySelector('.stock-dropdown select[aria-label^=Select]').options.length===3"), 'Stock dropdown search did not filter locally'
        await js("(()=>{const s=document.querySelector('.stock-dropdown select[aria-label^=Select]');s.value='TEST B';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelector('.stock-identity h1')?.textContent.includes('TEST B')")
        await js("(()=>{const s=document.querySelector('.stock-dropdown select[aria-label^=Select]');s.value='TEST A';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelector('.stock-identity h1')?.textContent.includes('TEST A')")
        assert '/api/instruments' not in requests, 'Dropdown search should not need broker search'
        await js("Array.from(document.querySelectorAll('.primary-nav button')).find(b=>b.textContent.trim()==='Focused').click()")
        await until("document.querySelector('.stock-picker select[aria-label^=Select]')?.options.length===3")
        assert await js("!!document.querySelector('.empty-state')")
        await js("(()=>{const s=document.querySelector('.stock-picker select[aria-label^=Select]');s.value='TEST A';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelectorAll('.view-card').length===1")
        text = await js("document.querySelector('.focused-page').innerText")
        for label in ('12 Months', '3 Months', '1 Month', '1 Week', '1 Day', '1 Hour', 'What to watch next', 'Volume confirmation'):
            assert label.lower() in text.lower(), label
        assert await js("document.querySelectorAll('.view-nav [role=tab]').length===6"), 'All timeframes must remain available'
        assert await js("document.querySelector('.view-card').getBoundingClientRect().top<320"), 'Too much space above analysis'
        assert await js("document.querySelectorAll('.methodology[open],.more-detail[open]').length===0"), 'Long explanations must start collapsed'
        for index in range(6):
            await js(f"document.getElementById('timeframe-tab-{index}').click()")
            await until(f"document.querySelector('[role=tab][aria-selected=true]').id==='timeframe-tab-{index}'")
            assert await js("document.querySelectorAll('.view-card').length===1"), 'Timeframes must replace each other'
            assert await js("document.querySelectorAll('.candle-patterns').length") == (1 if index>=4 else 0)
        assert await js("document.querySelector('.candle-patterns').textContent.includes('Doji')"), 'Detected shapes missing from analysis'
        await js("document.querySelector('.pattern-observation summary').click()")
        assert await js("!!document.querySelector('.pattern-observation[open] .pattern-confirmation')"), 'Pattern confirmation must remain accessible'
        await js("document.getElementById('timeframe-tab-4').click()")
        assert await js("document.querySelectorAll('.pattern-observation[open]').length===0"), 'Details should reset on timeframe switch'
        await js("document.getElementById('timeframe-tab-4').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))")
        assert await js("document.activeElement.id==='timeframe-tab-5'"), 'Keyboard timeframe navigation failed'
        assert await js("document.querySelector('.focused-page').querySelectorAll('canvas').length===0")
        for width in (1440, 390):
            await call('Emulation.setDeviceMetricsOverride', dict(width=width, height=900, deviceScaleFactor=1, mobile=width<500))
            await asyncio.sleep(.2)
            assert await js("document.querySelector('.focused-page').scrollWidth<=document.querySelector('.focused-page').clientWidth"), f'Overflow at {width}px'
            if width==1440:
                assert await js("document.documentElement.scrollHeight<=1000"), 'Collapsed desktop analysis needs excessive scrolling'
            screenshot=await call('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False))
            import base64
            (ROOT/'frontend/dist'/f'focused-ui-{width}.png').write_bytes(base64.b64decode(screenshot['data']))
        await js("(()=>{const s=document.querySelector('.stock-picker select[aria-label^=Select]');s.value='TEST B';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelector('.notice[role=alert]')?.textContent.includes('Synthetic history failure')")
        assert await js("document.querySelectorAll('.view-card').length===0"), 'Old stock analysis remained after error'
        assert not any('/jobs' in r for r in requests), 'Unexpected market-wide scan'
        assert not errors, errors
        print('PASS: eight research views under Strategies; chart pagination; filters; payoff inputs; index hourly/weekly requests; desktop/mobile layout; existing screener, Stock Details and Focused behavior; no browser exceptions.')
        receiver.cancel()


if __name__ == '__main__':
    browser = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    build_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT/'frontend/dist/market-desk/browser'
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(build_dir)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='focused-structure-qa-') as profile:
        process = subprocess.Popen([str(browser), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                                    '--remote-debugging-port=9348', f'--user-data-dir={profile}', 'about:blank'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            asyncio.run(run(f'http://127.0.0.1:{server.server_port}', 9348))
        finally:
            process.terminate()
            process.wait(timeout=15)
            server.shutdown()
