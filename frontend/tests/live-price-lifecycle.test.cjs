const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
const rxjs=require('rxjs');
function setup(){
  const calls=[];let tick,stopped=false;
  const document={hidden:false};
  const api={chartQuote:(...args)=>{const stream=new rxjs.Subject();calls.push({args,stream});return stream;}};
  const module={exports:{}};
  const js=ts.transpileModule(fs.readFileSync(__dirname+'/../src/app/live-price.component.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText;
  vm.runInNewContext(js,{module,exports:module.exports,document,
    setInterval:(callback,ms)=>{assert.equal(ms,15000);tick=callback;return 1;},clearInterval:()=>{stopped=true;},
    require:name=>name==='@angular/core'?{Component:()=>x=>x,Input:()=>()=>{},HostListener:()=>()=>{},inject:()=>api}:name==='rxjs'?rxjs:{}});
  const component=new module.exports.LivePriceComponent();component.instrumentKey='NSE_INDEX|Nifty 50';
  return {component,calls,document,tick:()=>tick(),stopped:()=>stopped};
}
test('quote refresh is independent of chart data and uses exact option selection',()=>{
  const s=setup();Object.assign(s.component,{expiry:'2026-10-27',strike:22600,side:'CE'});s.component.ngOnChanges();
  assert.deepEqual(Array.from(s.calls[0].args),['NSE_INDEX|Nifty 50','2026-10-27',22600,'CE']);
  s.tick();assert.equal(s.calls.length,1);
  s.calls[0].stream.next({price:138.4,receivedAt:'2026-10-26T05:50:00Z'});
  s.component.fallbackPrice=100;s.component.ngOnChanges();assert.equal(s.calls.length,1);
  s.tick();assert.equal(s.calls.length,2);
  s.calls[1].stream.error({status:502});assert.equal(s.component.failed,true);assert.equal(s.component.quote.price,138.4);
  s.component.load();assert.equal(s.component.failed,true);
  s.calls[2].stream.next({price:140,receivedAt:'2026-10-26T05:50:15Z'});assert.equal(s.component.failed,false);
  s.component.ngOnDestroy();assert.equal(s.stopped(),true);
});
test('switching instrument cancels the old quote; hidden charts do not poll',()=>{
  const s=setup();s.component.ngOnChanges();s.component.instrumentKey='MCX_FO|123';s.component.ngOnChanges();
  assert.equal(s.calls[0].stream.observed,false);assert.equal(s.component.quote,undefined);
  s.document.hidden=true;s.component.visibilityChanged();assert.equal(s.calls[1].stream.observed,false);
  s.tick();assert.equal(s.calls.length,2);
  s.document.hidden=false;s.component.visibilityChanged();assert.equal(s.calls.length,3);
  s.component.ngOnDestroy();assert.equal(s.calls[2].stream.observed,false);
});
