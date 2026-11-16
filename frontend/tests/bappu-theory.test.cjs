const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
const rxjs=require('rxjs');
function load(file,env={}){
 const module={exports:{}};
 const js=ts.transpileModule(fs.readFileSync(__dirname+'/../src/app/option-market/'+file+'.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText;
 vm.runInNewContext(js,{module,exports:module.exports,document:env.document,require:name=>name==='@angular/core'?{Component:()=>x=>x,Input:()=>()=>{},ViewChild:()=>()=>{},HostListener:()=>()=>{},inject:()=>env.api}:name==='rxjs'?{...rxjs,interval:()=>env.clock}:name==='./bappu-theory'?math:name==='lightweight-charts'?env.charts??{}:name.includes('backend-url')?{backendUrl:x=>x}:{}});
 return module.exports;
}
const math=load('bappu-theory');
test('five multiples use the same ATP-low difference, including decimals and zero',()=>{
 const result=math.bappuLevels({price:120,atp:118,dayLow:83});
 assert.equal(result.direction,'BUY');
 assert.equal(result.difference,35);
 assert.deepEqual(Array.from(result.targets,t=>t.price),[153,188,223,258,293]);
 assert.equal(math.bappuLevels({price:84,atp:83,dayLow:83}).targets[4].price,83);
 assert.ok(Math.abs(math.bappuLevels({price:100,atp:97.65,dayLow:64.75}).targets[4].price-262.15)<1e-8);
 for(const q of [undefined,{}, {atp:118},{price:120,atp:0,dayLow:83},{price:120,atp:80,dayLow:83},{price:120,atp:Infinity,dayLow:83},{price:120,atp:118,dayLow:NaN},{price:118,atp:118,dayLow:83},{price:NaN,atp:118,dayLow:83},{price:0,atp:118,dayLow:83}])assert.equal(math.bappuLevels(q),null);
});
test('SELL uses high minus ATP and subtracts all five multiples from ATP',()=>{
 const levels=math.bappuLevels({price:99,atp:100,dayHigh:110,dayLow:80});
 assert.equal(levels.direction,'SELL');assert.equal(levels.difference,10);
 assert.deepEqual(Array.from(levels.targets,t=>t.price),[90,80,70,60,50]);
 for(const dayHigh of [undefined,NaN,Infinity,0,99])assert.equal(math.bappuLevels({price:95,atp:100,dayHigh}),null);
 assert.equal(math.bappuLevels({price:99,atp:100,dayHigh:100}).difference,0);
});
test('current price selects the requested ATP formulas using the same high and low',()=>{
 const quote={price:99,atp:100,dayHigh:120,dayLow:80};
 const sell=math.bappuLevels(quote);
 assert.equal(sell.direction,'SELL');
 assert.equal(sell.targets[0].price,quote.atp-(quote.dayHigh-quote.atp));
 assert.deepEqual(Array.from(sell.targets,t=>t.price),[80,60,40,20,0]);
 const buy=math.bappuLevels({...quote,price:101});
 assert.equal(buy.direction,'BUY');
 assert.equal(buy.targets[0].price,quote.atp+(quote.atp-quote.dayLow));
 assert.deepEqual(Array.from(buy.targets,t=>t.price),[120,140,160,180,200]);
 assert.equal(math.bappuLevels({...quote,price:100}),null);
});
test('crossings include exact touches and skipped levels, exclude moving levels and direction changes',()=>{
 const buy={price:105,atp:100,dayLow:90},sell={price:95,atp:100,dayHigh:110};
 assert.deepEqual(Array.from(math.crossedBapuLevels(buy,{...buy,price:130}),t=>t.multiple),[1,2,3]);
 assert.deepEqual(Array.from(math.crossedBapuLevels(sell,{...sell,price:70}),t=>t.multiple),[1,2,3]);
 assert.equal(math.crossedBapuLevels(buy,{...buy,atp:95}).length,0);
 assert.equal(math.crossedBapuLevels(buy,{...sell,price:80}).length,0);
 assert.equal(math.crossedBapuLevels(undefined,buy).length,0);
 assert.equal(math.crossedBapuLevels(sell,{...sell,price:NaN}).length,0);
});
function setup(file,type){
 const calls=[],document={hidden:false},clock=new rxjs.Subject();
 const api=Object.fromEntries(['optionExpiries','optionChain','chartQuote','analyzeOption'].map(name=>[name,(...args)=>{const stream=new rxjs.Subject();calls.push({name,args,stream});return stream;}]));
 const component=new (load(file,{api,document,clock})[type])();component.underlyingKey='NIFTY';
 return {component,calls,document,clock};
}
test('CE and PE selections stay independent and clear when expiry or underlying changes',()=>{
 const s=setup('bappu-theory.component','BappuTheoryComponent');s.component.ngOnChanges();
 s.calls[0].stream.next({expiries:['2026-11-17','2026-11-24']});
 s.calls[1].stream.next({rows:[{strike:25300},{strike:25400}]});
 s.component.selectStrike('CE','25300');s.component.selectStrike('PE','25400');
 assert.equal(s.component.ceStrike,25300);assert.equal(s.component.peStrike,25400);
 s.component.selectStrike('CE','25400');assert.equal(s.component.ceStrike,25400);
 s.component.selectStrike('PE','999');assert.equal(s.component.peStrike,0);
 s.component.selectExpiry('2026-11-24');assert.equal(s.component.ceStrike,0);assert.equal(s.component.peStrike,0);
 assert.equal(s.calls[1].stream.observed,false);
 s.component.underlyingKey='OTHER';s.component.ngOnChanges();assert.equal(s.calls[2].stream.observed,false);
 s.component.ngOnDestroy();assert.equal(s.calls.at(-1).stream.observed,false);
});
test('leg requests exact contract and cancels old requests and levels on changes',()=>{
 const s=setup('bappu-leg.component','BappuLegComponent');Object.assign(s.component,{expiry:'2026-11-17',strike:25300,side:'PE'});s.component.ngOnChanges();
 assert.deepEqual(Array.from(s.calls[0].args),['NIFTY','2026-11-17',25300,'PE']);
 assert.deepEqual(Array.from(s.calls[1].args),['NIFTY','2026-11-17',25300,'PE',5]);
 s.calls[0].stream.next({price:120,atp:118,dayLow:83,receivedAt:'2026-11-16T04:00:00Z'});assert.equal(s.component.calculation.targets[0].price,153);
 s.component.strike=25400;s.component.ngOnChanges();assert.equal(s.calls[0].stream.observed,false);assert.equal(s.calls[1].stream.observed,false);assert.equal(s.component.calculation,null);
 s.document.hidden=true;s.component.visibilityChanged();assert.equal(s.calls[2].stream.observed,false);assert.equal(s.calls[3].stream.observed,false);
 const count=s.calls.length;s.clock.next();assert.equal(s.calls.length,count);
 s.document.hidden=false;s.component.visibilityChanged();assert.equal(s.calls.length,count+2);
 s.calls.at(-2).stream.next({price:120,atp:119,dayLow:83,receivedAt:'2026-11-16T04:00:00Z'});s.component.loadQuote();s.calls.at(-1).stream.error({error:{detail:'Disconnected'}});assert.equal(s.component.quote.atp,119);assert.equal(s.component.quoteError,'Disconnected');
 s.component.ngOnDestroy();const last=s.calls.length;s.clock.next();assert.equal(s.calls.length,last);
});
test('PE alerts identify contract, deduplicate levels and reset for a new session or contract',()=>{
 const s=setup('bappu-leg.component','BappuLegComponent');
 Object.assign(s.component,{expiry:'2026-11-17',strike:25300,side:'PE'});s.component.ngOnChanges();
 const emit=(price,receivedAt='2026-11-16T04:00:00Z')=>{s.component.loadQuote();s.calls.filter(c=>c.name==='chartQuote').at(-1).stream.next({price,atp:100,dayHigh:110,dayLow:90,receivedAt});};
 emit(95);assert.equal(s.component.alerts.length,0);emit(70);assert.equal(s.component.alerts.length,3);
 assert.match(s.component.alerts[0].message,/25300 PE · SELL · 3×/);
 emit(95);emit(70);assert.equal(s.component.alerts.length,3);
 emit(105);emit(120);assert.equal(s.component.alerts.length,5);
 assert.match(s.component.alerts[0].message,/PE · BUY/);
 emit(95,'2026-11-17T04:00:00Z');assert.equal(s.component.alerts.length,0);
 emit(90,'2026-11-17T04:00:15Z');assert.equal(s.component.alerts.length,1);
 s.component.strike=25400;s.component.ngOnChanges();assert.equal(s.component.alerts.length,0);s.component.ngOnDestroy();
});
test('chart draws Ghost Rider VWAP values, colors and gaps; changing contract clears it',()=>{
 const series=[];
 const charts={ColorType:{Solid:'solid'},createChart:()=>({addSeries:()=>{const line={setData:data=>line.data=data,createPriceLine:()=>({}),removePriceLine:()=>{}};series.push(line);return line;},timeScale:()=>({fitContent:()=>{}}),remove:()=>{}})};
 const api={chartQuote:()=>rxjs.EMPTY,analyzeOption:()=>rxjs.of({candles:[],ghostRider:{points:[{timestamp:'2026-11-16T04:00:00Z',vwap:101,vwapColor:'#4caf50'},{timestamp:'2026-11-16T04:05:00Z',vwap:null}]}})};
 const component=new (load('bappu-leg.component',{api,document:{hidden:false},clock:new rxjs.Subject(),charts}).BappuLegComponent)();
 Object.assign(component,{underlyingKey:'NIFTY',expiry:'2026-11-17',strike:25300,chartHost:{nativeElement:{}}});component.ngAfterViewInit();component.loadHistory();
 assert.equal(series[1].data[0].value,101);assert.equal(series[1].data[0].color,'#4caf50');assert.equal('value' in series[1].data[1],false);
 component.ngOnChanges();assert.equal(series[1].data.length,2);
 component.underlyingKey='';component.ngOnChanges();assert.equal(series[1].data.length,0);component.ngOnDestroy();
});
