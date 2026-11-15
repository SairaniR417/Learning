const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const rx = require('rxjs');

function load(api) {
  const module = {exports:{}};
  let service;
  const core = {Component:()=>x=>x,Injectable:()=>x=>x,Input:()=>()=>{},Output:()=>()=>{},ViewChild:()=>()=>{},
    EventEmitter:class { values=[];emit(value){this.values.push(value);} },
    inject:token=>token.name==='MarketApiService'?api:service};
  const source=fs.readFileSync(__dirname+'/../src/app/shared/stock-choices.component.ts','utf8');
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText,
    {module,exports:module.exports,Map,require:name=>name==='@angular/core'?core:name==='rxjs'?rx:name.includes('market-api')?{MarketApiService:class MarketApiService{}}:{}});
  service = new module.exports.StockChoicesService();
  return ()=>new module.exports.StockChoicesComponent();
}

test('stock dropdown is available without typing and matches symbols or company names',()=>{
  const make=load({fnoStocks:()=>rx.of({stocks:[{symbol:'TCS',name:'Tata Consultancy'},{symbol:'INFY',name:'Infosys'},{symbol:'TCS',name:'Tata Consultancy'}]})});
  const c=make();c.ngOnInit();assert.equal(c.loading,false);assert.equal(c.choices.length,2);
  c.query='consultancy';assert.equal(c.choices[0].symbol,'TCS');
  assert.notEqual(c.selection,'','A partial search must leave the clear option selectable');
  c.choose('TCS');assert.equal(c.chosen.values[0],'TCS');
  c.choose('');assert.equal(c.chosen.values[1],'');
  c.query='missing';assert.equal(c.choices.length,0);
});

test('context dropdowns use their own stocks instead of fetching the universe',()=>{
  const make=load({fnoStocks:()=>{throw Error('Unexpected request');}}),c=make();
  c.stocks=[{symbol:'OWN',name:'Saved watchlist entry'}];c.ngOnChanges();c.ngOnInit();
  assert.equal(c.choices.length,1);assert.equal(c.choices[0].symbol,'OWN');
});

test('saved list loads once across controls and async options retain the selected symbol',()=>{
  const pending=new rx.Subject();let calls=0;
  const make=load({fnoStocks:()=>{calls++;return pending;}}),a=make(),b=make();
  a.query='TCS';a.ngOnInit();b.ngOnInit();assert.equal(calls,1);assert.equal(a.loading,true);
  pending.next({stocks:[{symbol:'TCS',name:'Tata Consultancy'}]});pending.complete();
  a.picker={nativeElement:{value:''}};a.ngAfterViewChecked();assert.equal(a.picker.nativeElement.value,'TCS');
  const c=make();c.ngOnInit();assert.equal(calls,1);assert.equal(c.choices.length,1);
  a.ngOnDestroy();b.ngOnDestroy();c.ngOnDestroy();
});

test('failed saved list can be retried without losing the typed query',()=>{
  let calls=0;const make=load({fnoStocks:()=>++calls===1?rx.throwError(()=>Error('offline')):rx.of({stocks:[{symbol:'TCS'}]})});
  const c=make();c.query='TCS';c.ngOnInit();assert.equal(c.error,true);assert.equal(c.loading,false);
  c.load();assert.equal(c.error,false);assert.equal(c.query,'TCS');assert.equal(c.choices.length,1);
});

test('index selection opens its chain without submitting an index to stock filters',()=>{
  const make=load({optionUnderlyings:()=>rx.of({underlyings:[{key:'NSE_INDEX|Nifty 50',symbol:'NIFTY',name:'Nifty 50',group:'Indices'},{key:'NSE_EQ|TCS',symbol:'TCS',group:'F&O stocks'}]})});
  const c=make();c.stocks=[{symbol:'OWN'}];c.query='OWN';c.changeMarket('Indices');
  assert.equal(c.choices.length,1);c.choose('NSE_INDEX|Nifty 50');
  assert.equal(c.chainKey,'NSE_INDEX|Nifty 50');assert.equal(c.chainOpen,true);assert.equal(c.chosen.values.length,0);
  c.changeMarket('Stocks');assert.equal(c.chainOpen,false);assert.equal(c.query,'OWN');assert.equal(c.choices[0].symbol,'OWN');
});

test('commodity expiry contracts remain distinct and chain uses the exact contract key',()=>{
  let flag;
  const make=load({optionUnderlyings:commodities=>{flag=commodities;return rx.of({underlyings:[{key:'MCX_FUT|A',symbol:'GOLD',name:'Gold November',group:'Commodities'},{key:'MCX_FUT|B',symbol:'GOLD',name:'Gold December',group:'Commodities'}]});}});
  const c=make();c.changeMarket('Commodities');assert.equal(flag,true);assert.equal(c.choices.length,2);
  c.choose('MCX_FUT|B');assert.equal(c.chainKey,'MCX_FUT|B');assert.equal(c.chainLabel,'Gold December');
  c.assetQuery='November';assert.equal(c.choices.length,1);assert.equal(c.choices[0].key,'MCX_FUT|A');
});

test('switching market cancels stale results and stock chain resolves symbols through saved keys',()=>{
  const pending=new rx.Subject();
  const make=load({fnoStocks:()=>rx.of({stocks:[{key:'NSE_EQ|TCS',symbol:'TCS'}]}),optionUnderlyings:commodities=>commodities?rx.of({underlyings:[]}):pending});
  const c=make();c.stocks=[{symbol:'TCS'}];c.query='TCS';c.changeMarket('Indices');assert.equal(c.loading,true);
  c.changeMarket('Commodities');pending.next({underlyings:[{symbol:'NIFTY',key:'INDEX',group:'Indices'}]});assert.equal(c.choices.length,0);
  c.changeMarket('Stocks');c.openChain();assert.equal(c.chainKey,'NSE_EQ|TCS');
  c.ngOnDestroy();
});
