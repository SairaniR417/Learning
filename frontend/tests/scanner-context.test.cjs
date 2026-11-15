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
      : name === 'rxjs' ? rx : name.includes('golden-cross.types') ? {defaultGoldenSettings:()=>({inputs:{require_confirmation:false,sma_medium:50,sma_long:200}})}
      : name.includes('suryavanshi.types') ? {defaultSuryavanshiSettings:()=>({inputs:{}})}
      : name.includes('backend-url') ? {backendUrl:x=>x} : {}
  });
  return new module.exports.EmaScannerComponent();
}

test('opening the screener automatically loads Ghost Rider with its defaults once', () => {
  const calls=[];
  const c=component({fnoStocks:()=>rx.of({total:213}),scannerStrategies:()=>rx.of({strategies:[{id:'ghost_rider',parameters:[{name:'atr_multiplier',default:1.5}]}]}),scanStrategy:(...args)=>{calls.push(args);return rx.of({total_scanned:213,results:[]});}});
  c.ngOnChanges();assert.equal(calls.length,0);
  c.ngOnInit();assert.equal(c.selectedStrategy,'ghost_rider');assert.equal(calls.length,1);
  assert.equal(calls[0][0],'ghost_rider');assert.equal(calls[0][1],'1d');assert.equal(calls[0][2].atr_multiplier,1.5);
  assert.equal(c.gridColumns.find(c=>c.id==='dayOpen').visible,true);
  c.active=false;c.ngOnChanges();c.active=true;c.ngOnChanges();assert.equal(calls.length,1);
});

test('inactive screener waits until opening before loading Ghost Rider', () => {
  let scans=0;
  const c=component({fnoStocks:()=>rx.of({total:213}),scannerStrategies:()=>rx.of({strategies:[]}),scanStrategy:()=>{scans++;return rx.of({total_scanned:0,results:[]});}});
  c.active=false;c.ngOnInit();assert.equal(scans,0);
  c.active=true;c.ngOnChanges();assert.equal(scans,1);
});

test('strategy and timeframe changes load automatically and cancel outdated requests', () => {
  const requests=[],disposed=[];
  const c=component({scanStrategy:(id,frame,params)=>{requests.push({id,frame,params});return new rx.Observable(()=>()=>disposed.push(frame));}});
  c.loadingStrategies=false;
  c.strategies=[{id:'ghost_rider',parameters:[{name:'atr_multiplier',default:1.5}]}];
  c.selectStrategy('ghost_rider');assert.equal(requests.length,1);assert.equal(requests[0].params.atr_multiplier,1.5);
  c.selectTimeframe('1h');assert.equal(requests.length,2);assert.equal(requests[1].frame,'1h');assert.equal(disposed[0],'1d');
  c.selectTimeframe('1h');assert.equal(requests.length,2);
  c.ngOnDestroy();assert.equal(disposed[1],'1h');
});

test('saved screener loads once using its restored timeframe and settings', () => {
  const calls=[];
  const c=component({scanStrategy:(...args)=>{calls.push(args);return rx.of({total_scanned:0,results:[]});}});
  c.loadingStrategies=false;c.strategies=[{id:'ghost_rider',parameters:[{name:'atr_multiplier',type:'float',default:1.5,min_value:1,max_value:5}]}];
  c.savedScreeners=[{name:'Hourly',strategyId:'ghost_rider',timeframe:'1h',strategyParams:{atr_multiplier:2},factors:[],sector:'Banking & Finance'}];
  c.loadScreener('Hourly');assert.equal(calls.length,1);assert.equal(calls[0][1],'1h');assert.equal(calls[0][2].atr_multiplier,2);
  assert.equal(c.selectedSector,'Banking & Finance');
});

test('Ghost prioritizes day open, change, opening range and requested indicators', () => {
  const c = component(), moves=[];
  c.onGridReady({api:{setColumnsVisible(){},moveColumns:(columns,index)=>moves.push({columns,index}),refreshHeader(){}}});
  c.selectStrategy('ghost_rider');
  for (const field of ['price','dayOpen','orbState','adx','rsi14','macdMain','vwap','vwapPosition','ema20Position','ema50Position','sma200Position','volume']) {
    assert.equal(c.gridColumns.find(column=>column.id===field).visible,true,field);
  }
  for(const field of ['sessionDate','fromOpenPct','dayHighPct','dayLowPct','nearestLevel','strength','macdHistogram','entry','tp1','tp2','tp3','tp4','tp5','asOf','decision','stopLoss','nextTarget','remainingRR'])
    assert.equal(c.gridColumns.find(column=>column.id===field).visible,false,field);
  assert.equal(c.gridColumns.find(column=>column.id==='detail').visible,false);
  assert.equal(Array.from(moves.at(-1).columns).join(','),'symbolCompany,status,price,dayOpen,changePct,orbState,adx,rsi14,macdMain,vwap,vwapPosition,ema20Position,ema50Position,sma200Position,volume,actions');
  assert.equal(c.columnDefs.find(column=>column.field==='status').headerName,'Signal');
  assert.equal(c.columnDefs.find(column=>column.field==='decision').headerName,'Entry check');
  assert.equal(c.columnDefs.find(column=>column.field==='remainingRR').headerName,'Reward / risk');
  c.selectStrategy('opening_range_breakout');
  assert.equal(c.columnDefs.find(column=>column.field==='status').headerName,'Status');
  assert.equal(c.columnDefs.find(column=>column.field==='decision').headerName,'Entry assessment');
});

test('Price vs VWAP compares stored prices and uses green/red with unavailable missing data', () => {
  const c=component(),col=c.columnDefs.find(col=>col.field==='vwapPosition');
  for(const [price,vwap,label,color] of [[110,100,'Above VWAP','#55c99f'],[90,100,'Below VWAP','#ed8792'],[100,100,'At VWAP','#a4a8b2'],[100,null,'Unavailable','#a4a8b2']]) {
    const value=col.valueGetter({data:{price,vwap}});
    assert.equal(value,label);assert.equal(col.cellStyle({value}).color,color);
  }
});

test('price comparisons use EMA 20, EMA 50 and SMA 200 with values in hover text', () => {
  const c=component();
  for(const [field,key,label] of [['ema20Position','ema20','EMA 20'],['ema50Position','ema50','EMA 50'],['sma200Position','sma200','SMA 200']]) {
    const col=c.columnDefs.find(col=>col.field===field);
    for(const [average,prefix,color] of [[90,'Above','#55c99f'],[110,'Below','#ed8792'],[100,'At','#a4a8b2'],[null,null,'#a4a8b2']]) {
      const row={price:100,[key]:average},value=col.valueGetter({data:row});
      assert.equal(value,prefix?`${prefix} ${label}`:'Unavailable');
      assert.equal(col.cellStyle({value}).color,color);
      assert.match(col.tooltipValueGetter({data:row,value}),/Candle close:/);
    }
  }
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

test('Institution Transaction shows both views and never claims institutional confirmation', () => {
  const c=component();c.timeframe='15m';c.selectStrategy('institution_transaction');
  assert.equal(c.timeframe,'1d');assert.equal(c.gridColumns.find(c=>c.id==='detail').visible,true);
  const row={strategyId:'institution_transaction',pressureViews:{'1d':{state:'BUYING'},'1h':{state:'UNAVAILABLE'}},pressureExplanation:'Daily buying pressure; hourly history unavailable. Institutional disclosures: NOT CHECKED.'};
  const badges=c.strategySignalBadges(row);
  assert.equal(badges[0].label,'Daily: BUYING');assert.equal(badges[1].label,'1 Hour: UNAVAILABLE');
  assert.equal(badges[2].label,'Disclosures: Not checked');
  assert.ok(badges.every(b=>b.explanation.includes('NOT CHECKED')));
  assert.equal(c.strategySignalMetrics(row).length,0);
});

test('crossover hover explains custom SMA periods, direction, values and age', () => {
  const c=component();c.timeframe='1h';
  const row={strategyId:'golden_death_cross',crossType:'GOLDEN_CROSS',state:'CROSS_ACTIVE',smaMediumPeriod:30,smaLongPeriod:100,sma50:123,sma200:120,barsSinceCross:3,crossTime:'2026-11-13T04:45:00Z',asOf:'2026-11-13T07:45:00Z',requireConfirmation:false};
  const badges=c.strategySignalBadges(row), text=badges[0].explanation;
  assert.match(text,/SMA 30 crossed above SMA 100/);
  assert.match(text,/1h timeframe/);assert.match(text,/3 completed candles ago/);
  assert.match(text,/123/);assert.match(text,/120/);assert.match(text,/IST/);
  assert.match(text,/confirmation filters are disabled/);
  assert.match(badges.find(b=>b.label==='CROSS ACTIVE').explanation,/does not mean a fresh crossing/);
  assert.doesNotMatch(text,/EMA 50|NaN|Invalid Date/);
  assert.equal(c.describeStrategyResult(row),text);
});

test('death cross hover distinguishes a new cross from failed confirmation checks', () => {
  const c=component();
  const badges=c.strategySignalBadges({strategyId:'golden_death_cross',crossType:'DEATH_CROSS',state:'WATCH',barsSinceCross:0,requireConfirmation:true,confirmationCount:1,confirmationChecks:{'RSI < 45':false,'Price below both EMAs':true}});
  assert.match(badges[0].explanation,/SMA 50 crossed below SMA 200/);
  assert.match(badges[0].explanation,/New cross on the latest completed candle/);
  assert.match(badges[0].explanation,/SMA 50 unavailable/);
  assert.match(badges.find(b=>b.label==='1\/6 confirmations').explanation,/Fail: RSI < 45/);
  assert.match(badges.find(b=>b.label==='RSI < 45').explanation,/Fail on the latest completed 1d candle/);
});

test('Change percent hover explains the selected candle comparison and formula', () => {
  const c=component(), column=c.columnDefs.find(column=>column.field==='changePct');
  c.timeframe='1h';
  const hint=column.tooltipValueGetter({data:{price:100,changePct:-0.2}});
  assert.match(hint,/previous hourly candle close/);
  assert.match(hint,/Latest close − Previous close/);
  assert.match(hint,/-0.20%/);assert.match(hint,/separate strategy conditions/);
  c.timeframe='1d';assert.match(column.tooltipValueGetter({data:{price:100,changePct:0}}),/previous trading day close/);
  assert.match(column.tooltipValueGetter({data:{price:100,changePct:null}}),/Change: unavailable/);
  assert.match(column.headerTooltip,/selected timeframe/);
});

test('zero is displayed accurately and missing numbers are not turned into zero', () => {
  const c=component();
  const format=c.columnDefs.find(column=>column.field==='fromOpenPct').valueFormatter;
  assert.equal(format({value:0}),'0.00');assert.equal(format({value:null}),'—');
  const rr=c.columnDefs.find(column=>column.field==='remainingRR').valueFormatter;
  assert.equal(rr({value:2,data:{rrTarget:'TP2'}}),'2.00:1 (TP2)');
});

test('risk and optional session columns explain their meaning on hover', () => {
  const c=component();
  assert.match(c.columnHint('stopLoss',{stopTouched:true},'Stop-loss',100),/already touched/);
  assert.match(c.columnHint('remainingRR',{},'Reward \/ risk',2),/two units of possible reward/);
  assert.match(c.columnHint('nextTarget',{},'Next target','TP1'),/not from the original entry/);
  assert.match(c.columnDefs.find(c=>c.field==='sessionDate').headerTooltip,/not necessarily today/);
});

test('other signal explanations distinguish position, crossover, divergence and risk', () => {
  const c=component();
  c.selectedStrategy='ema_sma_alignment';c.strategyParams={ema1:12,ema2:26,sma1:40,sma2:100};
  const metrics=c.strategySignalMetrics({ema9:10,ema20:9,sma50:8,sma200:7});
  assert.deepEqual(Array.from(metrics,m=>m.label),['EMA 12','EMA 26','SMA 40','SMA 100']);
  assert.match(c.signalContext({status:'ALIGNED'}),/does not establish a new crossover/);
  assert.match(c.signalContext({classification:'EARLY_BULLISH',emaFastPeriod:12,emaSlowPeriod:26}),/EMA 12 crossed above EMA 26/);
  assert.match(c.signalContext({strategyId:'rsi_reversal',prevRsi:25,rsi:35}),/Previous RSI: 25; current RSI: 35/);
  const divergence={strategyId:'rsi_divergence',divergenceType:'REGULAR_BULLISH',direction:'BULLISH',pivot1Price:100,pivot2Price:95,pivot1Rsi:20,pivot2Rsi:30,rsi:40,pivot1At:'2026-11-01',pivot2At:'2026-11-05',detectedAt:'2026-11-10',asOf:'2026-11-13',ageBars:3};
  assert.ok(c.strategySignalBadges(divergence).every(b=>b.explanation.includes('price formed a lower pivot low')));
  assert.match(c.signalContext({strategyId:'ghost_rider',signal:'BUY',signalAt:'2026-11-13',state:'ACTIVE',decisionReason:'WAIT: old data',stopTouched:true}),/Stop has been touched/);
  assert.match(c.signalContext({strategyId:'sutradhar'}),/do not define an entry, stop or target/);
  assert.match(c.signalContext({strategyId:'opening_range_breakout',orbHigh:110,orbLow:100,orbHeldBars:2}),/Held 2 completed 5m bars/);
});

test('explicit chart opening only passes supported Golden inputs to the workspace', () => {
  const c=component();c.selectedStrategy='suryavanshi';c.strategyParams={length:20,rr_ratio:1.1};
  c.openStock({instrumentKey:'test',symbol:'TEST'});
  assert.deepEqual(Object.keys(c.goldenInputs).sort(),['require_confirmation','sma_long','sma_medium']);
  c.selectedStrategy='golden_death_cross';c.strategyParams={sma_medium:30,unknown_input:1};
  c.openStock({instrumentKey:'test',symbol:'TEST'});
  assert.equal(c.goldenInputs.sma_medium,30);assert.equal(c.goldenInputs.unknown_input,undefined);
});
