"""Focused layout/ranking verification with 33 recorded or repeated fixture matches."""
import asyncio
import base64
import json
from pathlib import Path
from urllib.parse import urlparse
import httpx
import websockets

async def main():
    async with httpx.AsyncClient(trust_env=False) as client:
        targets=(await client.get('http://localhost:9333/json')).json()
    websocket=next(t['webSocketDebuggerUrl'] for t in targets if t['type']=='page')
    pending={};sequence=0;errors=[]
    fixture=json.loads(Path('data/focused-latest.json').read_text(encoding='utf-8'))
    caps=json.loads(Path('data/nse-market-cap.json').read_text(encoding='utf-8'))
    for side in ('bullish','bearish'):
        for stock in fixture[side]:
            stock['marketCap']=caps['values'].get(stock['symbol'])
            stock['marketCapAsOf']=caps['asOf']
    fixture['marketCapAsOf']=caps['asOf']
    fixture['marketCapSource']=caps['source']
    original=fixture['bullish']
    fixture['bullish']=[dict(original[i%len(original)]) for i in range(33)]
    fixture['totalBullish']=33
    async with websockets.connect(websocket,max_size=20_000_000) as ws:
        async def call(method,params=None):
            nonlocal sequence
            sequence+=1
            future=asyncio.get_running_loop().create_future()
            pending[sequence]=future
            await ws.send(json.dumps({'id':sequence,'method':method,'params':params or {}}))
            response=await asyncio.wait_for(future,30)
            if 'error' in response:raise RuntimeError(response['error'])
            return response.get('result',{})
        async def intercept(params):
            path=urlparse(params['request']['url']).path
            mocks={
                '/api/focused/jobs':{'id':'layout-check'},
                '/api/focused/jobs/layout-check':{'id':'layout-check','status':'complete','stage':'Ready','result':fixture,'error':''},
                '/api/status':{'connected':True,'configured':True},
                '/api/market/snapshot':{'market':'equities','name':'NSE equities','chartKey':'','chartSymbol':'','assets':[],'receivedAt':1},
                '/api/watchlists/notifications':{'notifications':[],'unread':0,'monitor':{'running':False,'lastCheck':None,'error':''}},
            }
            if path in mocks:
                await call('Fetch.fulfillRequest',{'requestId':params['requestId'],'responseCode':200,'responseHeaders':[{'name':'Content-Type','value':'application/json'}],'body':base64.b64encode(json.dumps(mocks[path]).encode()).decode()})
            else:await call('Fetch.continueRequest',{'requestId':params['requestId']})
        async def receive():
            async for raw in ws:
                event=json.loads(raw)
                if 'id' in event:
                    future=pending.pop(event['id'],None)
                    if future and not future.done():future.set_result(event)
                elif event.get('method')=='Fetch.requestPaused':asyncio.create_task(intercept(event['params']))
                elif event.get('method')=='Runtime.exceptionThrown':errors.append(event['params']['exceptionDetails'].get('text','Error'))
        receiver=asyncio.create_task(receive())
        async def js(expression):
            result=await call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if 'exceptionDetails' in result:raise AssertionError(result['exceptionDetails'])
            return result['result'].get('value')
        async def until(expression):
            for _ in range(100):
                value=await js(expression)
                if value:return value
                await asyncio.sleep(.3)
            raise AssertionError('Timed out: '+expression)
        await call('Runtime.enable')
        await call('Page.enable')
        await call('Fetch.enable',{'patterns':[{'urlPattern':'*/api/*'}]})
        await call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':768,'deviceScaleFactor':1,'mobile':False})
        await call('Page.navigate',{'url':'http://localhost:4200'})
        await until("Array.from(document.querySelectorAll('.primary-nav button')).some(b=>b.textContent.trim()==='Focused')")
        await js("Array.from(document.querySelectorAll('.primary-nav button')).find(b=>b.textContent.trim()==='Focused').click()")
        await until("document.querySelectorAll('.stock-row').length===10")
        text=await js("document.querySelector('.focused-page').innerText")
        assert '2026-10-12' in text and '33 bullish' in text
        assert 'SL' in text and 'T1' in text and 'T2' in text and 'Cap' in text
        expected=sorted(fixture['bullish'],key=lambda s: (-(s['marketCap'] or -1),-s['averageTurnover'],-s['score'],s['symbol']))[0]['symbol']
        assert await js("document.querySelector('.bullish .symbol').textContent") == expected, 'Company-size sort failed'
        await js("(()=>{const s=document.querySelector('.actions .page-size');s.value='10';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelectorAll('.stock-row').length===15")
        height=await js("document.documentElement.scrollHeight")
        assert height<=768, f'Desktop page requires scrolling: {height}'
        assert await js("Array.from(document.querySelectorAll('.table-wrap')).every(t=>t.scrollWidth<=t.clientWidth)"), 'Desktop table overflow'
        await js("document.querySelector('.reason-button').click()")
        await until("document.querySelector('dialog').open && document.querySelector('dialog').innerText.toLowerCase().includes('level calculation')")
        assert await js("document.querySelector('dialog').querySelectorAll('.reason').length>=2"), 'Missing reasons'
        await call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
        await call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
        await until("!document.querySelector('dialog').open")
        await js("document.querySelector('[aria-label=\"Next bullish page\"]').click()")
        await until("document.querySelector('.bullish .pagination').innerText.includes('11-20 of 33')")
        await js("document.querySelector('[aria-label=\"Next bullish page\"]').click();document.querySelector('[aria-label=\"Next bullish page\"]').click()")
        await until("document.querySelector('.bullish .pagination').innerText.includes('31-33 of 33')")
        assert await js("document.querySelectorAll('.bullish .stock-row').length") == 3
        await js("document.querySelector('[aria-label=\"Previous bullish page\"]').click();document.querySelector('[aria-label=\"Previous bullish page\"]').click();document.querySelector('[aria-label=\"Previous bullish page\"]').click()")
        await js("(()=>{const s=document.querySelector('.sort-select');s.value='price';s.dispatchEvent(new Event('change'));})()")
        expectedPrice=max(s['close'] for s in fixture['bullish'])
        firstPrice=await js("Number(document.querySelector('.bullish .stock-row').querySelectorAll('td')[5].textContent.replaceAll(',',''))")
        assert firstPrice==expectedPrice, 'Price sorting failed'
        await js("(()=>{const s=document.querySelector('.sort-select');s.value='size';s.dispatchEvent(new Event('change'));})()")
        await js("(()=>{const s=document.querySelector('.actions input');s.value='500';s.dispatchEvent(new Event('input'));})()")
        assert await js("Array.from(document.querySelectorAll('.stock-row')).every(r=>Number(r.querySelectorAll('td')[5].textContent.replaceAll(',',''))>=500)"), 'Minimum price filter failed'
        await js("(()=>{const s=document.querySelector('.actions input');s.value='0';s.dispatchEvent(new Event('input'));})()")
        shot=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
        Path('data/focused-compact-desktop.png').write_bytes(base64.b64decode(shot['data']))
        await js("(()=>{const s=document.querySelector('.actions .page-size');s.value='3';s.dispatchEvent(new Event('change'));})()")
        await until("document.querySelectorAll('.stock-row').length===6")
        shot=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
        Path('data/focused-compact-three.png').write_bytes(base64.b64decode(shot['data']))
        await call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
        await asyncio.sleep(.5)
        assert await js("document.querySelector('.focused-page').scrollWidth <= document.querySelector('.focused-page').clientWidth"), 'Focused mobile overflow'
        shot=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
        Path('data/focused-compact-mobile.png').write_bytes(base64.b64decode(shot['data']))
        assert not errors,errors
        print(json.dumps({'desktopRows':15,'desktopPageHeight':height,'limitThreeRows':6,'reasonsDialog':True,'paginationTo33':True,'marketCapSorting':True,'priceSorting':True,'minPriceFilter':True,'mobileOverflow':False,'runtimeErrors':errors,'screenshots':['data/focused-compact-desktop.png','data/focused-compact-mobile.png']}))
        receiver.cancel()

asyncio.run(main())
