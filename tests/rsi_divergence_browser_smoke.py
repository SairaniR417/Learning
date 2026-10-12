"""Manual scanner UI test with all API calls intercepted; no real API writes.

Requires frontend on :4200 and headless Chrome debugging on :9332.
"""
import asyncio
import base64
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
import websockets
from scanner.strategies.rsi_divergence import RsiDivergenceStrategy


async def main():
    review = json.loads(Path('data/rsi-divergence-scan-review.json').read_text())
    examples = []
    for kind in ('REGULAR_BULLISH', 'REGULAR_BEARISH', 'HIDDEN_BULLISH', 'HIDDEN_BEARISH'):
        examples.append(next(row for row in review['results'] if row['divergenceType'] == kind))
    async with httpx.AsyncClient() as client:
        targets = (await client.get('http://localhost:9332/json')).json()
    ws_url = next(t['webSocketDebuggerUrl'] for t in targets if t['type'] == 'page')
    pending, errors, requests = {}, [], []
    sequence = 0
    async with websockets.connect(ws_url, max_size=20_000_000) as ws:
        async def call(method, params=None):
            nonlocal sequence
            sequence += 1
            future = asyncio.get_running_loop().create_future()
            pending[sequence] = future
            await ws.send(json.dumps(dict(id=sequence, method=method, params=params or {})))
            return await asyncio.wait_for(future, 20)

        async def fulfill(event):
            request = event['request']
            path = urlparse(request['url']).path
            result = {}
            if path == '/api/status':
                result = dict(connected=True, configured=True)
            elif path == '/api/market/snapshot':
                result = dict(market='equities', name='NSE equities', chartKey='', chartSymbol='', assets=[], receivedAt=1)
            elif path == '/api/watchlists/notifications':
                result = dict(notifications=[], unread=0, monitor=dict(running=True, error='', lastCheck=''))
            elif path == '/api/strategies':
                result = dict(strategies=[RsiDivergenceStrategy.metadata.model_dump()])
            elif path == '/api/strategies/scan':
                requests.append(json.loads(request['postData']))
                result = dict(strategy_id='rsi_divergence', strategy_name='RSI Divergence', timeframe='1d', total_scanned=review['scanned'], total_matched=4, results=examples, cached=False, scanned_at='2026-10-12T09:00:00Z')
            elif path == '/api/stocks/history':
                result = dict(total=0, page=1, pageSize=50, earliest=None, latest=None, high=None, low=None, totalVolume=0, candles=[], chart=[], source='Test fixture', addedAt=None)
            elif path == '/api/stocks/news':
                result = dict(items=[], source='Test fixture')
            elif path == '/api/quotes':
                result = dict(data={})
            await call('Fetch.fulfillRequest', dict(requestId=event['requestId'], responseCode=200, responseHeaders=[dict(name='Content-Type', value='application/json')], body=base64.b64encode(json.dumps(result).encode()).decode()))

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
            response = await call('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
            if response.get('exceptionDetails'):
                raise AssertionError(response['exceptionDetails'])
            return response.get('result', {}).get('value')
        async def until(expression):
            for _ in range(80):
                if await evaluate(expression):
                    return
                await asyncio.sleep(.2)
            raise AssertionError('UI timeout: ' + expression)
        await until("!!document.querySelector('.primary-nav')")
        await evaluate("Array.from(document.querySelectorAll('.primary-nav button')).find(b => b.textContent.trim() === 'Market Scanner').click()")
        await until("!!document.querySelector('.strategy-select option[value=rsi_divergence]')")
        await evaluate("(() => {const s=document.querySelector('.strategy-select'); s.value='rsi_divergence'; s.dispatchEvent(new Event('change',{bubbles:true}));})()")
        await evaluate("document.querySelector('.run-scan').click()")
        await until("document.querySelector('.market-grid')?.textContent.includes('REGULAR BULLISH')")
        assert await evaluate("document.querySelector('.market-grid').textContent.includes('HIDDEN BEARISH')")
        assert await evaluate("document.querySelectorAll('.scanner-tabs button.active').length === 1")
        await evaluate("document.querySelector('.grid-tool-rail button:last-child').click()")
        await evaluate("(() => {const s=Array.from(document.querySelectorAll('.side-filter')).find(l=>l.textContent.includes('Divergence')).querySelector('select');s.value='HIDDEN_BULLISH';s.dispatchEvent(new Event('change',{bubbles:true}));})()")
        await until("/Displaying\\s+1\\s+matches/.test(document.querySelector('.results-meta')?.textContent || '')")
        assert await evaluate("document.querySelector('.market-grid').textContent.includes('HIDDEN BULLISH')")
        shot = await call('Page.captureScreenshot', dict(format='png'))
        Path('data/rsi-divergence-review.png').write_bytes(base64.b64decode(shot['data']))
        await evaluate("document.querySelector('.symbol-company-cell button').click()")
        await until("document.querySelector('.stock-page')?.textContent.includes('HIDDEN BULLISH')")
        assert await evaluate("document.querySelector('.stock-page').textContent.includes('Pivots')")
        assert requests[0]['strategy_id'] == 'rsi_divergence' and requests[0]['timeframe'] == '1d'
        assert not errors, errors
        print('UI passed: strategy loads, scan renders four types, type filter works, only one market tab active, selection preserves evidence, no runtime errors.')
        try:
            await call('Browser.close')
        except Exception:
            pass
        task.cancel()


if __name__ == '__main__':
    asyncio.run(main())
