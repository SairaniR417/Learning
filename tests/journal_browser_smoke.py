"""Manual end-to-end journal test with mocked API, never writes real trades.

Frontend :4200, headless Chrome debugging :9333, workspace-only profile.
"""
import asyncio
import base64
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
import websockets
from services.trade_journal import TradeInput, calculated


def record(identifier, **values):
    trade=TradeInput.model_validate({'account':'Main account','symbol':'TEST','direction':'LONG','entryAt':'2026-05-05T09:30:00+05:30','exitAt':'2026-05-05T10:30:00+05:30','entryPrice':100,'exitPrice':110,'quantity':100,'charges':30,'stopPrice':95,'targetPrice':110,'setup':'Breakout','emotionBefore':'Calm','emotionDuring':'Focused','emotionAfter':'Neutral','didWell':'Waited for confirmation','learned':'Stick to the plan',**values})
    return {'id':identifier,**trade.model_dump(mode='json'),**calculated(trade),'imported':False}


async def main():
    reference=json.loads(Path('data/journal-workbook-reference.json').read_text())
    rows=[record(1,symbol='HDFCBANK'),record(2,symbol='RELIANCE',direction='SHORT',entryPrice=200,exitPrice=212,quantity=25,charges=20,stopPrice=210,targetPrice=180,entryAt='2026-05-06T11:00:00+05:30',exitAt='2026-05-06T12:30:00+05:30',emotionBefore='Impatient',mistake='Entered too early',entryFollowed=False),record(3,symbol='GOLD',segment='Commodity',entryAt='2026-05-07T18:30:00+05:30',exitAt=None,exitPrice=None)]
    imported=False
    async with httpx.AsyncClient() as client:
        targets=(await client.get('http://localhost:9333/json')).json()
    websocket=next(t['webSocketDebuggerUrl'] for t in targets if t['type']=='page')
    pending,errors={},[]; sequence=0
    async with websockets.connect(websocket,max_size=20_000_000) as ws:
        async def call(method,params=None):
            nonlocal sequence
            sequence+=1;future=asyncio.get_running_loop().create_future();pending[sequence]=future
            await ws.send(json.dumps({'id':sequence,'method':method,'params':params or {}}))
            return await asyncio.wait_for(future,45)
        async def fulfill(event):
            nonlocal rows,imported
            request=event['request'];path=urlparse(request['url']).path;method=request['method'];body=json.loads(request.get('postData') or '{}');result={}
            if path=='/api/status':result={'connected':False,'configured':True}
            elif path=='/api/market/snapshot':result={'market':'equities','name':'NSE equities','chartKey':'','chartSymbol':'','assets':[],'receivedAt':1}
            elif path=='/api/watchlists/notifications':result={'notifications':[],'unread':0,'monitor':{'running':True,'error':'','lastCheck':''}}
            elif path=='/api/journal/trades' and method=='GET':result={'trades':rows}
            elif path=='/api/journal/provided-workbooks':result=reference
            elif path=='/api/journal/import-provided':
                result={'added':0 if imported else 1,'duplicates':1 if imported else 0,'warnings':reference['warnings']}
                if not imported:
                    row=record(10,**{**reference['trades'][0],'stopPrice':None,'targetPrice':None});row['imported']=True;rows.append(row);imported=True
            elif path.startswith('/api/journal/trades') and method in ('POST','PUT'):
                identifier=int(path.split('/')[-1]) if method=='PUT' else max(t['id'] for t in rows)+1
                result=record(identifier,**body);rows=[t for t in rows if t['id']!=identifier]+[result]
            elif path.startswith('/api/journal/trades/') and method=='DELETE':
                rows=[t for t in rows if t['id']!=int(path.split('/')[-1])];result={'deleted':True}
            await call('Fetch.fulfillRequest',{'requestId':event['requestId'],'responseCode':200,'responseHeaders':[{'name':'Content-Type','value':'application/json'}],'body':base64.b64encode(json.dumps(result).encode()).decode()})
        async def reader():
            async for raw in ws:
                message=json.loads(raw)
                if 'id' in message:
                    future=pending.pop(message['id'],None)
                    if future and not future.done():
                        if 'error' in message:future.set_exception(RuntimeError(str(message['error'])))
                        else:future.set_result(message.get('result',{}))
                elif message.get('method')=='Fetch.requestPaused':asyncio.create_task(fulfill(message['params']))
                elif message.get('method')=='Runtime.exceptionThrown':errors.append(message['params']['exceptionDetails'])
        task=asyncio.create_task(reader())
        await call('Runtime.enable');await call('Page.enable')
        await call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
        await call('Fetch.enable',{'patterns':[{'urlPattern':'*/api/*'}]})
        await call('Page.navigate',{'url':'http://localhost:4200'})
        async def evaluate(expression):
            r=await call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if r.get('exceptionDetails'):raise AssertionError(r['exceptionDetails'])
            return r.get('result',{}).get('value')
        async def until(expression):
            for _ in range(90):
                if await evaluate(expression):return
                await asyncio.sleep(.2)
            raise AssertionError('UI timeout: '+expression)
        async def section(name):
            await evaluate("Array.from(document.querySelectorAll('.journal-nav nav button')).find(b=>b.textContent.trim().endsWith("+json.dumps(name)+")).click()")
        async def field(label,value):
            await evaluate("(()=>{const l=Array.from(document.querySelectorAll('.journal-modal .field')).find(l=>l.firstChild.textContent.trim() === "+json.dumps(label)+");const i=l.querySelector('input,textarea,select');i.value="+json.dumps(str(value))+";i.dispatchEvent(new Event(i.tagName==='SELECT'?'change':'input',{bubbles:true}));})()")
        await until("!!document.querySelector('.primary-nav')")
        await evaluate("Array.from(document.querySelectorAll('.primary-nav button')).find(b=>b.textContent.trim()==='Trade Journal').click()")
        await until("document.querySelector('.metric-grid')?.textContent.includes('2 closed')")
        assert await evaluate("document.querySelector('.metric-grid').textContent.includes('650.00')")
        assert await evaluate("document.querySelector('.metric-grid').textContent.includes('50.0%')")
        assert await evaluate("document.querySelector('.metric-grid').textContent.includes('1 open')")
        screenshot=await call('Page.captureScreenshot',{'format':'png'})
        Path('data/trade-journal-review.png').write_bytes(base64.b64decode(screenshot['data']))
        await section('Trade Log')
        await until("document.querySelector('.table-panel')?.textContent.includes('HDFCBANK')")
        await evaluate("document.querySelector('.header-actions .gold-button').click()")
        await field('Symbol / instrument','TCS');await field('Entry price ₹',100);await field('Exit price ₹ (blank = open)',102);await field('Position quantity (units)',20);await field('Total charges ₹',5)
        await field('Entry date & time · IST','2026-05-07T09:30');await field('Exit date & time · IST (blank = open)','2026-05-07T10:30')
        await evaluate("Array.from(document.querySelectorAll('.form-tabs button')).find(b=>b.textContent==='Review').click()")
        await field('Lesson learned','Wait for the closing breakout')
        await evaluate("document.querySelector('.journal-modal footer .gold-button').click()")
        await until("!document.querySelector('.journal-modal')")
        await until("document.querySelector('.table-panel')?.textContent.includes('TCS')")
        await section('Reflections')
        await until("document.querySelector('.reflection-grid')?.textContent.includes('Wait for the closing breakout')")
        await section('Calendar')
        await evaluate("(()=>{const i=document.querySelector('input[type=month]');i.value='2026-05';i.dispatchEvent(new Event('change',{bubbles:true}));})()")
        await until("document.querySelector('.calendar-grid')?.textContent.includes('970.00')")
        await section('Settings')
        await evaluate("Array.from(document.querySelectorAll('.settings-panel + article button')).find(b=>b.textContent.includes('Review')).click()")
        await until("document.querySelector('.journal-modal')?.textContent.includes('4,300')")
        await evaluate("document.querySelector('.journal-modal footer .gold-button').click()")
        await until("!document.querySelector('.journal-modal')")
        await section('Trade Log')
        await until("document.querySelector('.table-panel')?.textContent.includes('Nifty 50')")
        assert len(rows)==5
        assert next(t for t in rows if t['symbol']=='TCS')['netPnl']==35
        assert not errors,errors
        await call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
        await section('Dashboard')
        assert await evaluate("document.documentElement.scrollWidth <= window.innerWidth+1")
        print('UI passed: offline journal works; metrics exclude open trades; add/save/reflection/calendar/import work; no runtime errors; mobile has no page overflow. All API writes were mocked.')
        try:await call('Browser.close')
        except Exception:pass
        task.cancel()


if __name__=='__main__':asyncio.run(main())
