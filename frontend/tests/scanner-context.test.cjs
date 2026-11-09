const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const rx = require('rxjs');

function component(api = {}) {
  const module = {exports:{}};
  const source = fs.readFileSync(__dirname + '/../src/app/scanner/ema-scanner.component.ts', 'utf8');
  const theme = {withPart(){return this;},withParams(){return this;}};
  vm.runInNewContext(ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText, {
    module, exports:module.exports, Intl, Date, localStorage:{getItem:()=>null},
    require:name => name === '@angular/core' ? {Component:()=>x=>x,Input:()=>()=>{},Output:()=>()=>{},EventEmitter:class{},inject:()=>api}
      : name === 'ag-grid-community' ? {ModuleRegistry:{registerModules(){}},themeQuartz:theme}
      : name === 'rxjs' ? rx : name.includes('golden-cross.types') ? {defaultGoldenSettings:()=>({inputs:{}})}
      : name.includes('suryavanshi.types') ? {defaultSuryavanshiSettings:()=>({inputs:{}})}
      : name.includes('backend-url') ? {backendUrl:x=>x} : {}
  });
  return new module.exports.EmaScannerComponent();
}

test('Ghost exposes day movement, risk and indicator columns with assessment before the old levels', () => {
  const c = component(), moves=[];
  c.onGridReady({api:{setColumnsVisible(){},moveColumns:(columns,index)=>moves.push({columns,index}),refreshHeader(){}}});
  c.selectStrategy('ghost_rider');
  for (const field of ['decision','dayOpen','fromOpenPct','dayHighPct','dayLowPct','nearestLevel','remainingRR','strength','adx','macdHistogram']) {
    assert.equal(c.gridColumns.find(column=>column.id===field).visible,true,field);
  }
  assert.equal(c.gridColumns.find(column=>column.id==='detail').visible,false);
  assert.ok(moves.at(-1).columns.includes('decision'));
  assert.equal(c.columnDefs.find(column=>column.field==='status').headerName,'Pine signal');
});

test('scan mapping preserves signed values and assessment filtering separates WAIT from BUY signals', () => {
  const rows = ['BUY CANDIDATE','WAIT'].map((decision,i)=>({
    instrumentKey:String(i),symbol:'AAA'+i,name:'Company',close:100,volume:1000,signal:'BUY',strategyId:'ghost_rider',
    decision,decisionReason:i?'Weak ADX':'Confluence confirmed',dayOpen:100,fromOpenPct:0,dayLowPct:-2,adx:18.4,
    nearestLevelPct:0.2,remainingRR:2,rrTarget:'TP2',nextTarget:'TP1',nextTargetPct:1,
    asOf:'2026-11-09T04:30:00+00:00',macdHistogram:-0.5
  }));
  const c=component({scanStrategy:()=>rx.of({total_scanned:2,results:rows})});
  c.selectStrategy('ghost_rider');c.scan();
  assert.equal(c.results[0].fromOpenPct,0);assert.equal(c.results[0].dayLowPct,-2);
  assert.equal(c.results[0].nearestLevelPct,0.2);assert.equal(c.results[0].rrTarget,'TP2');
  c.setRightFilter('decision','WAIT');assert.equal(c.filteredResults.length,1);
  assert.equal(c.filteredResults[0].decisionReason,'Weak ADX');
  c.clearRightFilters();assert.equal(c.filteredResults.length,2);
});

test('opening range forces 5m, exposes range holds and hides Ghost risk columns', () => {
  const c=component();c.timeframe='1d';c.selectStrategy('opening_range_breakout');
  assert.equal(c.timeframe,'5m');
  for(const field of ['orbHigh','orbLow','orbMinutes','orbHeldBars','decisionReason'])
    assert.equal(c.gridColumns.find(column=>column.id===field).visible,true,field);
  assert.equal(c.gridColumns.find(column=>column.id==='entry').visible,false);
});

test('zero is displayed accurately and missing numbers are not turned into zero', () => {
  const c=component();
  const format=c.columnDefs.find(column=>column.field==='fromOpenPct').valueFormatter;
  assert.equal(format({value:0}),'0.00');assert.equal(format({value:null}),'—');
  const rr=c.columnDefs.find(column=>column.field==='remainingRR').valueFormatter;
  assert.equal(rr({value:2,data:{rrTarget:'TP2'}}),'2.00 to TP2');
});
