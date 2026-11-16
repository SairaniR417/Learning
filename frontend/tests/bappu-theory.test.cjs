const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
const rxjs=require('rxjs');
function load(file,env={}){
 const module={exports:{}};
 const js=ts.transpileModule(fs.readFileSync(__dirname+'/../src/app/option-market/'+file+'.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText;
 vm.runInNewContext(js,{module,exports:module.exports,document:env.document,require:name=>name==='@angular/core'?{Component:()=>x=>x,Input:()=>()=>{},ViewChild:()=>()=>{},HostListener:()=>()=>{},inject:()=>env.api}:name==='rxjs'?{...rxjs,interval:()=>env.clock}:name==='./bappu-theory'?math:name.includes('backend-url')?{backendUrl:x=>x}:{}});
 return module.exports;
}
const math=load('bappu-theory');
test('five multiples use the same ATP-low difference, including decimals and zero',()=>{
 const result=math.bappuLevels({atp:118,dayLow:83});
 assert.equal(result.difference,35);
 assert.deepEqual(Array.from(result.targets,t=>t.price),[153,188,223,258,293]);
 assert.equal(math.bappuLevels({atp:83,dayLow:83}).targets[4].price,83);
 assert.ok(Math.abs(math.bappuLevels({atp:97.65,dayLow:64.75}).targets[4].price-262.15)<1e-8);
 for(const q of [undefined,{}, {atp:118},{atp:0,dayLow:83},{atp:80,dayLow:83},{atp:Infinity,dayLow:83},{atp:118,dayLow:NaN}])assert.equal(math.bappuLevels(q),null);
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
 s.calls[0].stream.next({atp:118,dayLow:83});assert.equal(s.component.calculation.targets[0].price,153);
 s.component.strike=25400;s.component.ngOnChanges();assert.equal(s.calls[0].stream.observed,false);assert.equal(s.calls[1].stream.observed,false);assert.equal(s.component.calculation,null);
 s.document.hidden=true;s.component.visibilityChanged();assert.equal(s.calls[2].stream.observed,false);assert.equal(s.calls[3].stream.observed,false);
 const count=s.calls.length;s.clock.next();assert.equal(s.calls.length,count);
 s.document.hidden=false;s.component.visibilityChanged();assert.equal(s.calls.length,count+2);
 s.calls.at(-2).stream.next({atp:119,dayLow:83});s.component.loadQuote();s.calls.at(-1).stream.error({error:{detail:'Disconnected'}});assert.equal(s.component.quote.atp,119);assert.equal(s.component.quoteError,'Disconnected');
 s.component.ngOnDestroy();const last=s.calls.length;s.clock.next();assert.equal(s.calls.length,last);
});
