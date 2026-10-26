const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { Subject, Subscription } = require('rxjs');

function setup() {
  const clock = new Subject();
  const calls = [];
  const api = { analyzeUnderlyingWorkspace: (...args) => { const stream = new Subject(); calls.push({args, stream, underlying:true}); return stream; }, analyzeStockWorkspace: (...args) => { const stream = new Subject(); calls.push({ args, stream, workspace:true }); return stream; }, analyzeOption: (...args) => { const stream = new Subject(); calls.push({ args, stream }); return stream; },
    analyzeStockGhost: (...args) => { const stream = new Subject(); calls.push({ args, stream, stock:true }); return stream; },
    analyzeStockRsi: (...args) => { const stream = new Subject(); calls.push({ args, stream, rsi:true }); return stream; },
    analyzeStockGolden: (...args) => { const stream = new Subject(); calls.push({ args, stream, golden:true }); return stream; },
    analyzeStockSuryavanshi: (...args) => { const stream = new Subject(); calls.push({ args, stream, suryavanshi:true }); return stream; },
    analyzeStockSutradhar: (...args) => { const stream = new Subject(); calls.push({ args, stream, sutradhar:true }); return stream; } };
  const document = { hidden: false };
  const module = { exports: {} };
  const settingsModule = { exports: {} };
  const rsiModule = { exports: {} };
  const suryavanshiModule = { exports: {} };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(__dirname + '/../src/app/option-market/suryavanshi.types.ts', 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, { module: suryavanshiModule, exports: suryavanshiModule.exports,require:()=>({}) });
  const goldenModule={exports:{}};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(__dirname + '/../src/app/option-market/golden-cross.types.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{module:goldenModule,exports:goldenModule.exports,require:()=>suryavanshiModule.exports});
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
      if (name === 'rxjs') return { ...require('rxjs'), Subscription, interval: ms => { assert.equal(ms, 60000); return clock; } };
      if (name.includes('backend-url')) return { backendUrl: x => x };
      if (name.includes('ghost-rider.types')) return settingsModule.exports;
      if (name.includes('rsi.types')) return rsiModule.exports;
      if (name.includes('suryavanshi.types')) return suryavanshiModule.exports;
      if (name.includes('golden-cross.types')) return goldenModule.exports;
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

test('combined workspace uses the selected stock endpoint and cancels frame requests', () => {
  const s = setup();
  Object.assign(s.component, {stockMode:true, stockWorkspace:true, underlyingKey:'NSE_EQ|INE002A01018', stockTimeframe:'1m'});
  s.component.ngOnChanges();
  assert.equal(s.calls[0].workspace,true);
  assert.equal(s.component.interval,1);
  s.component.changeStockTimeframe('30m');
  assert.equal(s.calls[0].stream.observed,false);
  assert.equal(s.calls[1].args[1],'30m');
  assert.equal(s.component.interval,30);
  s.component.ngOnDestroy();
  assert.equal(s.calls[1].stream.observed,false);
});

test('combined workspace requests Sutradhar settings on selection and pauses hidden requests', () => {
  const s = setup();
  Object.assign(s.component,{stockMode:true,stockWorkspace:true,underlyingKey:'NSE_EQ|INE002A01018'});
  s.component.ngOnChanges();
  assert.equal(s.calls[0].args[4],undefined);
  s.component.showStrategy('sutradhar');
  assert.equal(s.calls[1].args[4].p1,14);
  s.document.hidden=true; s.component.visibilityChanged();
  assert.equal(s.calls[1].stream.observed,false);
  s.clock.next(); assert.equal(s.calls.length,2);
  s.component.ngOnDestroy();
});


test('Suryavanshi scanner chart retains inputs; style edits do not request data', () => {
  const s=setup();s.component.stockMode=true;s.component.stockStrategy='suryavanshi';
  s.component.initialSuryavanshiInputs={length:12,candle_type:'Body',rr_ratio:2,sl_type:'High/Low',show_sl:true};
  s.component.ngOnChanges();
  assert.equal(s.calls[0].suryavanshi,true);
  assert.equal(s.calls[0].args[2].length,12);
  assert.equal(s.calls[0].args[2].candle_type,'Body');
  s.finish();
  let settings=JSON.parse(JSON.stringify(s.component.suryavanshiSettings));settings.tables=false;
  s.component.applySuryavanshiSettings(settings);assert.equal(s.calls.length,1);
  settings=JSON.parse(JSON.stringify(settings));settings.inputs.rr_ratio=3;
  s.component.applySuryavanshiSettings(settings);assert.equal(s.calls.length,2);
  assert.equal(s.calls[1].args[2].rr_ratio,3);
  s.component.ngOnDestroy();assert.equal(s.calls[1].stream.observed,false);
});


test('Golden Cross scanner and workspace retain periods and separate styles from inputs',()=>{
  const s=setup();s.component.stockMode=true;s.component.stockStrategy='golden_death_cross';
  s.component.initialGoldenInputs={...s.component.goldenSettings.inputs,sma_medium:20,sma_long:100};
  s.component.ngOnChanges();assert.equal(s.calls[0].golden,true);assert.equal(s.calls[0].args[2].sma_medium,20);
  s.finish();let settings=JSON.parse(JSON.stringify(s.component.goldenSettings));settings.labels=false;
  s.component.applyGoldenSettings(settings);assert.equal(s.calls.length,1);
  settings=JSON.parse(JSON.stringify(settings));settings.inputs.require_confirmation=true;
  s.component.applyGoldenSettings(settings);assert.equal(s.calls.length,2);assert.equal(s.calls[1].args[2].require_confirmation,true);
  s.component.ngOnDestroy();assert.equal(s.calls[1].stream.observed,false);
});


test('switching stock during the first load starts the new request immediately',()=>{
  const s=setup();Object.assign(s.component,{stockMode:true,stockWorkspace:true,underlyingKey:'NSE_EQ|FIRST'});
  s.component.ngOnChanges();assert.equal(s.component.loading,true);
  s.component.underlyingKey='NSE_EQ|SECOND';s.component.ngOnChanges();
  assert.equal(s.calls[0].stream.observed,false);assert.equal(s.calls.length,2);
  assert.equal(s.calls[1].args[0],'NSE_EQ|SECOND');assert.equal(s.calls[1].stream.observed,true);
  s.component.ngOnDestroy();
});

test('stored preview renders before live history; failure preserves preview and next selection works',()=>{
  const s=setup();Object.assign(s.component,{stockMode:true,stockWorkspace:true});s.component.ngOnChanges();
  assert.equal(s.calls[0].args[7],true);
  const preview={storedPreview:true,candles:[{timestamp:'2026-10-23',close:100}],strategies:[{id:'ghost_rider',markers:[],levels:[]}]};
  s.calls[0].stream.next(preview);assert.equal(s.component.data,preview);assert.equal(s.component.loading,true);
  assert.equal(s.calls.length,1);s.calls[0].stream.complete();assert.equal(s.calls.length,2);assert.equal(s.calls[1].args[7],false);
  s.calls[1].stream.error({status:502});assert.equal(s.component.data,preview);assert.equal(s.component.loading,false);assert.match(s.component.error,/Stored history/);
  s.component.underlyingKey='NSE_EQ|NEXT';s.component.ngOnChanges();assert.equal(s.calls.length,3);assert.equal(s.calls[2].args[0],'NSE_EQ|NEXT');
  s.component.ngOnDestroy();
});

test('preview failure falls through to live and changing stocks cancels that refresh',()=>{
  const s=setup();Object.assign(s.component,{stockMode:true,stockWorkspace:true});s.component.ngOnChanges();
  s.calls[0].stream.error({status:503});assert.equal(s.calls.length,2);assert.equal(s.calls[1].stream.observed,true);
  s.component.underlyingKey='NSE_EQ|NEXT';s.component.ngOnChanges();assert.equal(s.calls[1].stream.observed,false);assert.equal(s.calls[2].stream.observed,true);
  s.component.ngOnDestroy();
});


test('stored fallback stays visibly old through retry, then clears on live success',()=>{
  const s=setup();Object.assign(s.component,{stockMode:true,stockWorkspace:true});s.component.ngOnChanges();
  const candle={timestamp:'2026-10-23T00:00:00+05:30',close:100};
  const data={candles:[candle],strategies:[],storedPreview:true};
  s.calls[0].stream.next(data);assert.equal(s.component.staleData,true);
  assert.equal(s.component.lastDataAt,candle.timestamp);
  s.calls[0].stream.complete();
  s.calls[1].stream.next({...data,storedPreview:false,staleData:true});s.calls[1].stream.complete();
  assert.equal(s.component.staleData,true);
  s.component.load();assert.equal(s.component.staleData,true);
  s.calls[2].stream.next({...data,storedPreview:false,staleData:false});s.calls[2].stream.complete();
  assert.equal(s.component.staleData,false);
  s.component.load();s.calls[3].stream.error({status:502});
  assert.equal(s.component.staleData,true);
  s.component.load();assert.equal(s.component.staleData,true);
  s.calls[4].stream.next({...data,storedPreview:false,staleData:false});
  assert.equal(s.component.staleData,false);
  s.component.ngOnDestroy();
});


test('index and commodity workspace uses underlying analysis with matching settings and no stock preview',()=>{
  const s=setup();Object.assign(s.component,{stockMode:true,stockWorkspace:true,underlyingWorkspace:true,stockTimeframe:'5m',underlyingKey:'NSE_INDEX|Nifty 50'});
  s.component.ngOnChanges();
  assert.equal(s.calls.length,1);assert.equal(s.calls[0].underlying,true);
  assert.equal(s.calls[0].args[0],'NSE_INDEX|Nifty 50');assert.equal(s.calls[0].args[1],'5m');
  assert.equal(s.calls[0].args.length,7);s.finish();
  s.component.showStrategy('sutradhar');assert.equal(s.calls[1].args[4].p1,14);
  s.component.changeStockTimeframe('1h');assert.equal(s.calls[1].stream.observed,false);
  assert.equal(s.calls[2].args[1],'1h');
  s.component.underlyingKey='MCX_FO|123';s.component.ngOnChanges();
  assert.equal(s.calls[2].stream.observed,false);assert.equal(s.calls[3].args[0],'MCX_FO|123');
  s.finish();s.component.load();s.calls[4].stream.error({status:502});assert.equal(s.component.staleData,true);
  s.component.load();assert.equal(s.component.staleData,true);s.finish();assert.equal(s.component.staleData,false);
  s.component.ngOnDestroy();
});


test('every strategy displays historical and current candles without changing confirmed signal candles',()=>{
  const s=setup();
  const history={timestamp:'2026-10-23T09:15:00+05:30',close:100};
  const today={timestamp:'2026-10-26T09:15:00+05:30',close:110,developing:true};
  s.component.data={candles:[history],chartCandles:[history,today],goldenCross:{candles:[history]},strategies:[]};
  for(const strategy of ['ghost_rider','golden_death_cross','rsi_divergence','sutradhar','suryavanshi','ema_alignment']){
    s.component.strategyId=strategy;
    assert.equal(s.component.activeCandles.length,2);
    assert.equal(s.component.activeCandles.at(-1),today);
  }
  assert.equal(s.component.data.candles.length,1);
  s.component.ngOnDestroy();
});

test('screener workspace keeps selected strategy while loading stored preview then today',()=>{
  const s=setup();Object.assign(s.component,{stockMode:true,stockWorkspace:true,showBack:true,stockStrategy:'rsi_divergence'});
  s.component.ngOnChanges();assert.equal(s.calls[0].workspace,true);assert.equal(s.calls[0].args[7],true);
  s.calls[0].stream.next({storedPreview:true,candles:[],strategies:[]});s.calls[0].stream.complete();
  assert.equal(s.calls[1].args[7],false);assert.equal(s.component.strategyId,'rsi_divergence');
  s.component.ngOnDestroy();
});
