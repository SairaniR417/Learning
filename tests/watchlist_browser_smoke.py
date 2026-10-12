"""Manual UI smoke test against localhost:4200 with all API calls mocked via CDP.

Start a headless Chrome instance on debugging port 9331 before running this file.
No watchlist or alert records are written to the real API.
"""
import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import websockets


async def main():
    async with httpx.AsyncClient() as client:
        targets = (await client.get('http://localhost:9331/json')).json()
    ws_url = next(t['webSocketDebuggerUrl'] for t in targets if t['type'] == 'page')
    now = datetime.now(timezone.utc).isoformat()
    entries = [dict(key='NSE_EQ|INE040A01034', symbol='HDFCBANK', name='HDFC Bank Ltd.', exchange='NSE', section='Stocks', flag='red'),
               dict(key='NSE_EQ|INE002A01018', symbol='RELIANCE', name='Reliance Industries Ltd.', exchange='NSE', section='Stocks', flag=''),
               dict(key='NSE_INDEX|Nifty 50', symbol='NIFTY 50', name='Nifty 50', exchange='NSE', section='Indices', flag='blue')]
    watchlist = dict(id=999, name='My market', sections=['Stocks', 'Indices'], entries=entries)
    alerts = []
    notices = []
    errors = []
    pending = {}
    sequence = 0

    async with websockets.connect(ws_url, max_size=20_000_000) as ws:
        async def call(method, params=None):
            nonlocal sequence
            sequence += 1
            future = asyncio.get_running_loop().create_future()
            pending[sequence] = future
            await ws.send(json.dumps(dict(id=sequence, method=method, params=params or {})))
            return await asyncio.wait_for(future, 15)

        async def fulfill(event):
            request = event['request']
            path = urlparse(request['url']).path
            method = request['method']
            body = json.loads(request.get('postData') or '{}')
            result = {}
            if path == '/api/status':
                result = dict(connected=True, configured=True)
            elif path == '/api/market/snapshot':
                result = dict(market='equities', name='NSE equities', chartKey='', chartSymbol='NIFTY 50', assets=[], receivedAt=1)
            elif path == '/api/watchlists' and method == 'GET':
                result = dict(lists=[watchlist])
            elif path == '/api/watchlists/999' and method == 'PUT':
                watchlist.update(body)
                result = watchlist
            elif path == '/api/watchlists/quotes':
                result = dict(quotes={e['key']: dict(price=1000+i*300, previousClose=990+i*310, change=10-i*10, changePct=1-i, volume=123400+i*1000) for i, e in enumerate(watchlist['entries'])}, receivedAt=now)
            elif path == '/api/instruments':
                result = dict(instruments=[dict(key='NSE_EQ|INE467B01029', symbol='TCS', name='Tata Consultancy Services Ltd.', exchange='NSE')])
            elif path == '/api/stocks/news':
                result = dict(items=[dict(title='Example company update (test fixture)', url='https://news.google.com', source='Test publisher', publishedAt=now)], fetchedAt=now, source='Test fixture')
            elif path == '/api/watchlists/alerts' and method == 'POST':
                alert = {**body, 'id': 123, 'active': False, 'lastPrice': 1010, 'triggeredAt': now}
                alerts.append(alert)
                notices.append(dict(id=456, key=body['key'], symbol=body['symbol'], name=body['name'], exchange=body['exchange'], message='Test price alert triggered at 1,010.00.', price=1010, createdAt=now, read=False))
                result = alert
            elif path == '/api/watchlists/alerts':
                result = dict(alerts=alerts)
            elif path == '/api/watchlists/notifications':
                result = dict(notifications=notices, unread=sum(not n['read'] for n in notices), monitor=dict(running=True, lastCheck=now, error=''))
            elif path.endswith('/read'):
                for notice in notices:
                    notice['read'] = True
                result = dict(read=True)
            await call('Fetch.fulfillRequest', dict(requestId=event['requestId'], responseCode=200,
                responseHeaders=[dict(name='Content-Type', value='application/json')], body=base64.b64encode(json.dumps(result).encode()).decode()))

        async def reader():
            async for raw in ws:
                message = json.loads(raw)
                if 'id' in message:
                    future = pending.pop(message['id'], None)
                    if future and not future.done():
                        if 'error' in message:
                            future.set_exception(RuntimeError(str(message['error'])))
                        else:
                            future.set_result(message.get('result', {}))
                elif message.get('method') == 'Fetch.requestPaused':
                    asyncio.create_task(fulfill(message['params']))
                elif message.get('method') == 'Runtime.exceptionThrown':
                    errors.append(message['params']['exceptionDetails'])

        task = asyncio.create_task(reader())
        await call('Runtime.enable')
        await call('Page.enable')
        await call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=900, deviceScaleFactor=1, mobile=False))
        await call('Fetch.enable', dict(patterns=[dict(urlPattern='*/api/*')]))
        await call('Page.navigate', dict(url='http://localhost:4200'))

        async def evaluate(expression):
            value = await call('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
            if value.get('exceptionDetails'):
                raise AssertionError(value['exceptionDetails'])
            return value.get('result', {}).get('value')

        async def until(expression):
            for _ in range(60):
                if await evaluate(expression):
                    return
                await asyncio.sleep(.2)
            raise AssertionError(f'UI timeout: {expression}')

        await until("!!document.querySelector('.primary-nav')")
        await evaluate("Array.from(document.querySelectorAll('.primary-nav button')).find(b => b.textContent.trim() === 'Watchlist').click()")
        await until("document.querySelector('.watch-table-panel')?.textContent.includes('HDFCBANK')")
        await evaluate("document.querySelector('.plus-button').click()")
        await until("!!document.querySelector('.search-input')")
        await evaluate("(() => { const input = document.querySelector('.search-input'); input.value = 'TCS'; input.dispatchEvent(new Event('input', {bubbles:true})); })()")
        await until("document.querySelector('.search-results')?.textContent.includes('TCS')")
        await evaluate("document.querySelector('.search-results button').click()")
        await until("document.querySelector('.watch-table-panel')?.textContent.includes('TCS')")
        await evaluate("document.querySelector('.modal header button').click()")
        await evaluate("Array.from(document.querySelectorAll('.symbol-cell button')).find(b => b.textContent.includes('TCS')).click()")
        await evaluate("document.querySelector('.preview-buttons button:last-child').click()")
        await until("!!document.querySelector('input[type=number]')")
        await evaluate("(() => { const input = document.querySelector('input[type=number]'); input.value = '1000'; input.dispatchEvent(new Event('input', {bubbles:true})); document.querySelector('.modal form').dispatchEvent(new Event('submit', {bubbles:true,cancelable:true})); })()")
        await until("!!document.querySelector('.alert-toast')")
        assert await evaluate("document.querySelector('.alert-toast').textContent.includes('TCS')")
        assert not errors, errors
        screenshot = await call('Page.captureScreenshot', dict(format='png'))
        artifact = Path('data/watchlist-review.png')
        artifact.write_bytes(base64.b64decode(screenshot['data']))
        print('UI passed: list loads; plus searches and adds; alert form saves; triggered notification toast appears; no runtime exceptions.')
        print('Screenshot:', artifact.resolve())
        try:
            await call('Browser.close')
        except Exception:
            pass
        task.cancel()


if __name__ == '__main__':
    asyncio.run(main())
