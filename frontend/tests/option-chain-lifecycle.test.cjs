const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { Subject, Subscription } = require('rxjs');

function setup() {
  const clock = new Subject();
  const expiry = new Subject();
  const requests = [];
  let expiryCalls = 0;
  const api = {
    optionExpiries: () => { expiryCalls++; return expiry; },
    optionChain: (key, expiry) => { const stream = new Subject(); requests.push({ key, expiry, stream }); return stream; }
  };
  const document = { hidden: false };
  const module = { exports: {} };
  const source = fs.readFileSync(__dirname + '/../src/app/stock-details/option-chain.component.ts', 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, experimentalDecorators: true
  }}).outputText;
  vm.runInNewContext(js, { module, exports: module.exports, document,
    require: name => {
      if (name === '@angular/core') return { Component: () => x => x, Input: () => () => {}, ViewChild: () => () => {}, HostListener: () => () => {}, inject: () => api };
      if (name === '@angular/common') return {};
      if (name === 'rxjs') return { Subscription, interval: ms => { assert.equal(ms, 60000); return clock; } };
      if (name.includes('backend-url')) return { backendUrl: x => x };
      return {};
    }
  });
  const component = new module.exports.OptionChainComponent();
  component.stockKey = 'NSE_INDEX|Nifty 50';
  const finish = () => { const req = requests.at(-1); req.stream.next({ rows: [], receivedAt: 'now' }); req.stream.complete(); };
  return { component, clock, expiry, requests, document, finish, expiryCalls: () => expiryCalls };
}

test('loads on opening, refreshes chain each minute, avoids overlaps and stops on destruction', () => {
  const s = setup(); s.component.ngOnChanges();
  s.expiry.next({ expiries: ['2026-12-31'] });
  assert.equal(s.requests.length, 1);
  s.clock.next(); assert.equal(s.requests.length, 1);
  s.finish(); s.clock.next(); assert.equal(s.requests.length, 2);
  assert.equal(s.expiryCalls(), 1);
  s.component.ngOnDestroy();
  assert.equal(s.requests.at(-1).stream.observed, false);
  s.clock.next(); assert.equal(s.requests.length, 2);
});

test('pauses in hidden browser tabs, resumes on return and cancels old expiry requests', () => {
  const s = setup(); s.component.ngOnChanges(); s.expiry.next({ expiries: ['2026-12-31'] });
  s.document.hidden = true; s.component.visibilityChanged();
  assert.equal(s.requests[0].stream.observed, false);
  s.clock.next(); assert.equal(s.requests.length, 1);
  s.document.hidden = false; s.component.visibilityChanged();
  assert.equal(s.requests.length, 2);
  s.component.selectExpiry('2027-01-28');
  assert.equal(s.requests[1].stream.observed, false);
  assert.equal(s.requests[2].expiry, '2027-01-28');
  s.component.ngOnDestroy();
});

test('opens CE/PE analysis, pauses chain polling and reloads chain on return', () => {
  const s = setup(); s.component.ngOnChanges(); s.expiry.next({ expiries: ['2026-12-31'] });
  const snapshot = price => ({ expiry: '2026-12-31', rows: [{ strike: 25000, call: { ltp: price }, put: { ltp: 80 } }], receivedAt: 'now' });
  s.requests[0].stream.next(snapshot(100)); s.requests[0].stream.complete();
  s.component.selectContract(25000, 'CE');
  assert.equal(s.component.selectedLeg.ltp, 100);
  s.clock.next(); assert.equal(s.requests.length, 1);
  s.component.selectContract(25000, 'PE');
  assert.equal(s.component.selectedLeg.ltp, 80);
  s.component.closeAnalysis();
  assert.equal(s.component.selectedContract, undefined);
  assert.equal(s.component.selectedLeg, undefined);
  assert.equal(s.requests.length, 2);
  s.component.ngOnDestroy();
});
