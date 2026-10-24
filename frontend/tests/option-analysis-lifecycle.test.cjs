const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { Subject, Subscription } = require('rxjs');

function setup() {
  const clock = new Subject();
  const calls = [];
  const api = { analyzeOption: (...args) => { const stream = new Subject(); calls.push({ args, stream }); return stream; },
    analyzeStockGhost: (...args) => { const stream = new Subject(); calls.push({ args, stream, stock:true }); return stream; },
    analyzeStockRsi: (...args) => { const stream = new Subject(); calls.push({ args, stream, rsi:true }); return stream; },
    analyzeStockSutradhar: (...args) => { const stream = new Subject(); calls.push({ args, stream, sutradhar:true }); return stream; } };
  const document = { hidden: false };
  const module = { exports: {} };
  const settingsModule = { exports: {} };
  const rsiModule = { exports: {} };
  const sutradharModule = { exports: {} };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(__dirname + '/../src/app/option-market/sutradhar.types.ts', 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, { module: sutradharModule, exports: sutradharModule.exports,require:()=>({}) });
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(__dirname + '/../src/app/option-market/rsi.types.ts', 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, { module: rsiModule, exports: rsiModule.exports });
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(__dirname + '/../src/app/option-market/ghost-rider.types.ts', 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, { module: settingsModule, exports: settingsModule.exports });
  class Emitter extends Subject { emit(value) { this.next(value); } }
  const source = fs.readFileSync(__dirname + '/../src/app/option-market/option-analysis.component.ts', 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, experimentalDecorators: true } }).outputText;
  vm.runInNewContext(js, { module, exports: module.exports, document,
    require: name => {
      if (name === '@angular/core') return { Component: () => x => x, Input: () => () => {}, Output: () => () => {}, ViewChild: () => () => {}, HostListener: () => () => {}, inject: () => api, EventEmitter: Emitter };
      if (name === 'rxjs') return { Subscription, interval: ms => { assert.equal(ms, 60000); return clock; } };
      if (name.includes('backend-url')) return { backendUrl: x => x };
      if (name.includes('ghost-rider.types')) return settingsModule.exports;
      if (name.includes('rsi.types')) return rsiModule.exports;
      if (name.includes('sutradhar.types')) return sutradharModule.exports;
      return {};
    }
  });
  const component = new module.exports.OptionAnalysisComponent();
  Object.assign(component, { underlyingKey: 'NSE_INDEX|Nifty 50', expiry: '2026-12-31', strike: 25000, side: 'PE' });
  const finish = () => {
    calls.at(-1).stream.next({ candles: [], strategies: [{ id: 'ghost_rider', markers: [], levels: [] }] });
    calls.at(-1).stream.complete();
  };
  return { component, calls, clock, document, finish };
}

test('requests exact option and timeframe; cancels previous request when timeframe changes', () => {
  const s = setup(); s.component.ngOnChanges();
  assert.deepEqual(Array.from(s.calls[0].args).slice(0,6), ['NSE_INDEX|Nifty 50', '2026-12-31', 25000, 'PE', 5, 1.5]);
  assert.equal(s.calls[0].args[6].calculate_divergence,true);
  s.component.changeInterval('15');
  assert.equal(s.calls[0].stream.observed, false);
  assert.equal(s.calls[1].args[4], 15);
  s.finish(); s.clock.next(); assert.equal(s.calls.length, 3);
  s.clock.next(); assert.equal(s.calls.length, 3);
  s.component.ngOnDestroy(); assert.equal(s.calls[2].stream.observed, false);
  s.clock.next(); assert.equal(s.calls.length, 3);
});

test('pauses hidden-tab requests and recovers from provider errors', () => {
  const s = setup(); s.component.ngOnChanges();
  s.document.hidden = true; s.component.visibilityChanged();
  assert.equal(s.calls[0].stream.observed, false);
  s.clock.next(); assert.equal(s.calls.length, 1);
  s.document.hidden = false; s.component.visibilityChanged();
  assert.equal(s.calls.length, 2);
  s.calls[1].stream.error({ status: 401, error: { detail: 'Connect Upstox' } });
  assert.equal(s.component.needsConnection, true);
  assert.equal(s.component.error, 'Connect Upstox');
  s.clock.next(); assert.equal(s.calls.length, 3);
  s.finish(); assert.equal(s.component.loading, false);
  s.component.ngOnDestroy();
});

test('hour day and week changes cancel old requests and retain Ghost visibility', () => {
  const s=setup(); s.component.ngOnChanges();
  for (const interval of [60,1440,10080]) {
    const previous=s.calls.at(-1);
    s.component.changeInterval(String(interval));
    assert.equal(previous.stream.observed,false);
    assert.equal(s.calls.at(-1).args[4],interval);
    assert.equal(s.component.ghostVisible,true);
  }
  s.component.ngOnDestroy();
});

test('scanner charts use stored stock history, preserve ATR input and support daily and intraday visibility', () => {
  const s=setup();
  Object.assign(s.component,{stockMode:true,underlyingKey:'NSE_EQ|INE002A01018',stockTimeframe:'1d',initialAtrMultiplier:2.5});
  s.component.ngOnChanges();
  assert.equal(s.calls[0].stock,true);
  assert.deepEqual(Array.from(s.calls[0].args),['NSE_EQ|INE002A01018','1d',2.5]);
  assert.equal(s.component.ghostVisible,true);
  s.component.changeStockTimeframe('15m');
  assert.deepEqual(Array.from(s.calls[1].args),['NSE_EQ|INE002A01018','15m',2.5]);
  assert.equal(s.calls[0].stream.observed,false);
  s.component.ngOnDestroy();
});

test('scanner RSI uses its stored endpoint and settings changes cancel stale requests',()=>{
  const s=setup();Object.assign(s.component,{stockMode:true,stockStrategy:'rsi_divergence',stockTimeframe:'5m',initialRsiPeriod:7});
  s.component.ngOnChanges();assert.equal(s.calls[0].rsi,true);assert.equal(s.calls[0].args[2].period,7);
  assert.equal(s.component.strategyId,'rsi_divergence');
  const settings=JSON.parse(JSON.stringify(s.component.rsiSettings));settings.inputs.ma_type='EMA';
  s.component.applyRsiSettings(settings);assert.equal(s.calls[0].stream.observed,false);assert.equal(s.calls[1].args[2].ma_type,'EMA');
  s.component.ngOnDestroy();assert.equal(s.calls[1].stream.observed,false);
});

test('Sutradhar daily history is requested on selection and input edits, not style edits',()=>{
  const s=setup();s.component.ngOnChanges();s.finish();
  assert.equal(s.calls[0].args[7],undefined);
  s.component.showStrategy('sutradhar');assert.equal(s.calls.length,2);assert.equal(s.calls[1].args[7].p1,14);
  s.finish();
  const style=JSON.parse(JSON.stringify(s.component.sutradharSettings));style.fills=false;
  s.component.applySutradharSettings(style);assert.equal(s.calls.length,2);
  const inputs=JSON.parse(JSON.stringify(style));inputs.inputs.use_ema=true;
  s.component.applySutradharSettings(inputs);assert.equal(s.calls.length,3);assert.equal(s.calls[2].args[7].use_ema,true);
  s.component.ngOnDestroy();assert.equal(s.calls[2].stream.observed,false);
});

test('Sutradhar stock chart retains selected periods and stops when destroyed',()=>{
  const s=setup();Object.assign(s.component,{stockMode:true,stockStrategy:'sutradhar',stockTimeframe:'15m',initialSutradharInputs:{p1:10,p2:6,p3:4,use_ema:true}});
  s.component.ngOnChanges();assert.equal(s.calls[0].sutradhar,true);assert.equal(s.calls[0].args[2].p1,10);
  assert.equal(s.component.sutradharVisible,true);s.component.ngOnDestroy();assert.equal(s.calls[0].stream.observed,false);
});
