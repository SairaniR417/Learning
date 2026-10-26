const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const rxjs = require('rxjs');

function setup() {
  const requests = [];
  const document = { hidden: false };
  let tick, cleared = false;
  const api = { get: (url, options) => {
    const stream = new rxjs.Subject(); requests.push({ url, options, stream }); return stream;
  }};
  const module = { exports: {} };
  const source = fs.readFileSync(__dirname + '/../src/app/option-market/underlying-chart.component.ts', 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, experimentalDecorators: true
  }}).outputText;
  vm.runInNewContext(js, { module, exports: module.exports, document,
    setInterval: callback => { tick = callback; return 1; }, clearInterval: () => { cleared = true; },
    require: name => {
      if (name === '@angular/core') return { Component: () => x => x, Input: () => () => {}, ViewChild: () => () => {}, inject: () => api };
      if (name === 'rxjs') return rxjs;
      return {};
    }
  });
  const component = new module.exports.UnderlyingChartComponent();
  component.instrumentKey = 'NSE_INDEX|Nifty 50';
  return { component, requests, document, tick: () => tick(), cleared: () => cleared };
}

test('switching timeframe cancels old request; switching underlying clears old candles', () => {
  const s = setup(); s.component.ngOnChanges();
  assert.equal(s.requests[0].url, '/api/market/chart');
  assert.equal(s.requests[0].options.params.instrument_key, 'NSE_INDEX|Nifty 50');
  s.component.changeInterval(15);
  assert.equal(s.requests[0].stream.observed, false);
  assert.equal(s.requests[1].options.params.interval, 15);
  s.component.rows = [{ close: 100 }];
  s.component.instrumentKey = 'MCX_FO|123'; s.component.ngOnChanges();
  assert.equal(s.component.rows.length, 0);
  assert.equal(s.requests[1].stream.observed, false);
  assert.equal(s.requests[2].options.params.instrument_key, 'MCX_FO|123');
  s.component.ngOnDestroy();
});

test('refresh pauses while hidden or busy; destruction cancels request and timer', () => {
  const s = setup(); s.component.ngOnChanges();
  s.tick(); assert.equal(s.requests.length, 1);
  s.requests[0].stream.next({candles:[],invalidCandles:0});
  s.document.hidden = true; s.tick(); assert.equal(s.requests.length, 1);
  s.document.hidden = false; s.tick(); assert.equal(s.requests.length, 2);
  s.component.ngOnDestroy();
  assert.equal(s.requests[1].stream.observed, false);
  assert.equal(s.cleared(), true);
});

test('provider failures show a retry message and release loading state', () => {
  const s = setup(); s.component.ngOnChanges();
  s.requests[0].stream.error({error:{detail:'Provider unavailable'}});
  assert.equal(s.component.loading, false);
  assert.equal(s.component.error, 'Provider unavailable');
  s.component.load(); assert.equal(s.requests.length, 2);
  s.component.ngOnDestroy();
});


test('old-data alert persists during retries and clears only after successful refresh', () => {
  const s = setup(); s.component.ngOnChanges();
  const candle = {timestamp:'2026-10-26T09:15:00+05:30',open:100,high:102,low:99,close:101};
  s.requests[0].stream.next({candles:[candle],invalidCandles:0});
  assert.equal(s.component.staleData, false);
  s.component.load(); s.requests[1].stream.error({status:502});
  assert.equal(s.component.staleData, true);
  assert.equal(s.component.lastDataAt, candle.timestamp);
  assert.equal(s.component.rows[0], candle);
  s.component.load(); assert.equal(s.component.staleData, true);
  s.requests[2].stream.next({candles:[{...candle,close:102}],invalidCandles:0});
  assert.equal(s.component.staleData, false);
  s.component.ngOnDestroy();
});
