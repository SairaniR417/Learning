const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');

function component(api={}){
  const module={exports:{}};
  const source=fs.readFileSync(__dirname+'/../src/app/focused/focused.component.ts','utf8');
  const theme={withPart(){return this;},withParams(){return this;}};
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText,{
    module,exports:module.exports,Intl,Date,document:{hidden:false},
    require:name=>name==='@angular/core'?{Component:()=>x=>x,Input:()=>()=>{},Output:()=>()=>{},EventEmitter:class{},inject:()=>api}:
      name==='ag-grid-community'?{ModuleRegistry:{registerModules(){}},themeQuartz:theme}:name==='rxjs'?require('rxjs'):{}
  });
  return new module.exports.FocusedComponent();
}

const signal=(id,direction,extra={})=>({id,name:id,signal:direction,state:'ACTIVE',signalAt:'2026-10-26T05:00:00Z',...extra});
const stock=(symbol,evidence,extra={})=>({instrumentKey:symbol,symbol,action:'WAIT',direction:'BUY',timeframe:'15m',validUntil:'2026-10-26T05:30:00Z',waitReasons:['Confirm entry'],evidence,...extra});

test('Focused starts by requesting daily data and changing to one minute requests a new scan',()=>{
  const {of,NEVER}=require('rxjs');const requests=[];
  const c=component({startFocusedPlans:(mode,timeframe)=>{requests.push(timeframe);return of({id:'test'});},focusedPlansJob:()=>NEVER});
  assert.equal(c.timeframe,'1d');assert.equal(c.timeframeLabel,'1 day');
  c.refresh();assert.equal(requests[0],'1d');
  c.selectTimeframe('1m');assert.equal(requests[1],'1m');
  c.ngOnDestroy();
});

test('one stock combines supporting strategies and excludes completed and context-only signals',()=>{
  const c=component();c.now=Date.parse('2026-10-26T05:15:00Z');
  c.data={plans:[stock('TEST',[
    signal('ghost_rider','BUY',{entry:100,stopLoss:95,targets:[105]}),
    signal('suryavanshi','BUY',{entry:101,stopLoss:96,targets:[106]}),
    signal('rsi_divergence','SELL',{signalState:'INVALIDATED'}),
    {id:'golden_death_cross',name:'Golden / Death Cross',direction:'BUY',state:'DAILY_TREND'}
  ]),stock('FINISHED',[signal('suryavanshi','SELL',{signalState:'TARGET'})])]};
  c.updateSignals();
  assert.equal(c.signalRows.length,1);assert.equal(c.signalRows[0].support,2);
  assert.equal(c.signalRows[0].signal,'BUY');assert.equal(c.signalRows[0].state,'WATCH');
  assert.equal(c.signalRows[0].entry,100);assert.match(c.signalRows[0].strategy,/ghost_rider.*suryavanshi/);
  c.directionFilter='SELL';c.updateSignals();assert.equal(c.signalRows.length,0);
  c.directionFilter='all';c.strategyFilter='suryavanshi';c.updateSignals();assert.equal(c.signalRows.length,1);
  c.changeFilter('ready');assert.equal(c.signalRows.length,0);
  c.changeFilter('watch');assert.equal(c.signalRows.length,1);
});

test('opposing active signals produce one conflict row without trade levels',()=>{
  const c=component();c.data={plans:[stock('CONFLICT',[signal('ghost_rider','BUY',{entry:100,stopLoss:95,targets:[110]}),signal('suryavanshi','SELL',{entry:100,stopLoss:105,targets:[90]})])]};
  c.updateSignals();assert.equal(c.signalRows.length,1);const row=c.signalRows[0];
  assert.equal(row.signal,'CONFLICT');assert.equal(row.state,'CONFLICT');
  assert.equal(row.entry,undefined);assert.equal(row.stopLoss,undefined);assert.equal(row.target,undefined);
  assert.equal(row.optionHint,'Wait for direction');
});

test('BSE Ghost Rider BUY remains visible against Death Cross SELL even when its entry is no longer fresh',()=>{
  const c=component();c.timeframe='1d';
  const ghost=signal('ghost_rider','BUY',{name:'Ghost Rider',state:'NO_FRESH_SETUP',signalState:'CURRENT_SETUP',ageBars:8,entryEligible:false,entry:3330.2,stopLoss:3169.44,targets:[3490.96]});
  const cross=signal('golden_death_cross','SELL',{name:'Golden / Death Cross',signalState:'CROSS_ACTIVE'});
  c.data={plans:[stock('BSE',[ghost,cross],{timeframe:'1d'})]};
  c.updateSignals();const row=c.signalRows[0];
  assert.equal(row.signal,'CONFLICT');assert.equal(row.state,'CONFLICT');
  assert.match(row.strategy,/Ghost Rider BUY/);assert.match(row.strategy,/Golden \/ Death Cross SELL/);
  assert.equal(row.entry,undefined);assert.equal(row.optionHint,'Wait for direction');
  c.directionFilter='SELL';c.updateSignals();assert.equal(c.signalRows.length,0);
});

test('ready stocks rank first and use validated levels; expired rows remain watchlist references',()=>{
  const c=component();c.now=Date.parse('2026-10-26T05:15:00Z');
  const levels={entry:102,stopLoss:98,target1:110};
  c.data={plans:[stock('WATCH',[signal('ghost_rider','BUY',{entry:100,stopLoss:95,targets:[105]})]),stock('READY',[signal('ghost_rider','BUY',{entry:100,stopLoss:95,targets:[105]})],{action:'BUY',mode:'intraday',plan:levels})]};
  c.updateSignals();assert.equal(c.signalRows[0].symbol,'READY');assert.equal(c.signalRows[0].state,'READY');assert.equal(c.signalRows[0].entry,102);
  c.now=Date.parse('2026-10-27T05:15:00Z');c.updateSignals();
  const expired=c.signalRows.find(r=>r.symbol==='READY');assert.equal(expired.state,'WATCH');assert.equal(expired.entry,100);assert.match(expired.reason,/refresh current-session/);
});

test('an opposite combined plan never supplies levels for a source setup',()=>{
  const c=component();c.data={plans:[stock('SELL',[signal('ghost_rider','SELL',{entry:100,stopLoss:105,targets:[90]})],{direction:'BUY',plan:{entry:200,stopLoss:190,target1:220}})]};
  c.updateSignals();assert.equal(c.signalRows[0].entry,100);assert.equal(c.signalRows[0].stopLoss,105);assert.equal(c.signalRows[0].optionHint,'PE candidate · not verified');
});

test('expired source history never promotes a combined entry',()=>{
  const c=component();
  c.now=Date.parse('2026-10-26T06:00:00Z');
  assert.equal(c.action({action:'BUY',validUntil:'2026-10-26T05:00:00Z'}),'WAIT');
});

test('switching timeframe cancels requests, clears stale results and reloads; mode preserves selection',()=>{
  const c=component();let scans=0,cancelled=0;
  c.refresh=()=>{scans++;};
  c.request={unsubscribe:()=>{cancelled++;}};
  c.optionRequest={unsubscribe:()=>{cancelled++;}};
  c.data={plans:[]};c.chartStock={};c.selected={};c.signalRows=[{}];c.optionFor={};c.option={};c.loading=true;
  c.selectTimeframe('1m');
  assert.equal(c.timeframe,'1m');assert.equal(scans,1);assert.equal(cancelled,2);
  assert.equal(c.data,null);assert.equal(c.chartStock,null);assert.equal(c.selected,null);
  assert.equal(c.signalRows.length,0);assert.equal(c.option,null);assert.equal(c.loading,false);
  c.selectTimeframe('1m');assert.equal(scans,1);
  c.selectTimeframe('invalid');assert.equal(scans,1);
  c.selectMode('swing');assert.equal(c.timeframe,'1m');assert.equal(c.mode,'swing');assert.equal(scans,2);
  assert.equal(c.timeframes.map(t=>t.value).join(','),'1m,5m,15m,1h,1d');
});

function actionRenderer(){
  const module={exports:{}};
  const source=fs.readFileSync(__dirname+'/../src/app/focused/focused-actions.component.ts','utf8');
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}}).outputText,{
    module,exports:module.exports,require:name=>name==='@angular/core'?{Component:()=>x=>x}:{}
  });
  return new module.exports.FocusedActionsComponent();
}

test('each action routes to its own stock panel and chart uses the supporting strategy',()=>{
  const c=component();const row={stock:stock('TEST',[]),symbol:'TEST',signal:'BUY',evidence:{id:'suryavanshi'}};
  const revealed=[];let checked;
  c.reveal=id=>revealed.push(id);c.checkOptions=value=>checked=value;
  const actions=c.columnDefs.find(col=>col.colId==='actions').cellRendererParams;
  actions.onDetails(row);assert.equal(c.selected,row);assert.equal(c.chartStock,null);assert.equal(revealed.at(-1),'focused-details');
  actions.onChart(row);assert.equal(c.chartStock,row.stock);assert.equal(c.chartStrategy,'suryavanshi');assert.equal(revealed.at(-1),'focused-chart');
  actions.onOptions(row);assert.equal(checked,row.stock);assert.equal(revealed.at(-1),'focused-options');
  checked=null;actions.onOptions({...row,signal:'CONFLICT'});assert.equal(checked,null);
});

test('renderer labels CE/PE correctly, dispatches separate clicks, and blocks conflicts and duplicate option checks',()=>{
  const r=actionRenderer();let details=0,charts=0,options=0,stops=0,checking=false;
  const row={symbol:'TEST',signal:'BUY'};
  const params={data:row,onDetails:value=>{assert.equal(value,row);details++;},onChart:()=>charts++,onOptions:()=>options++,isChecking:()=>checking};
  r.agInit(params);assert.equal(r.optionLabel,'Check CE');
  const event={stopPropagation:()=>stops++};r.details(event);r.chart(event);r.options(event);
  assert.equal(details,1);assert.equal(charts,1);assert.equal(options,1);assert.equal(stops,3);
  checking=true;r.options(event);assert.equal(options,1);assert.equal(r.optionsDisabled,true);
  checking=false;r.refresh({...params,data:{symbol:'OTHER',signal:'SELL'}});assert.equal(r.optionLabel,'Check PE');
  r.options(event);assert.equal(options,2);
  r.refresh({...params,data:{signal:'CONFLICT'}});r.options(event);assert.equal(options,2);assert.equal(r.optionsDisabled,true);
  r.refresh({...params,data:undefined});r.details(event);r.chart(event);r.options(event);assert.equal(details,1);assert.equal(charts,1);assert.equal(options,2);
});

test('option action calls the API for the chosen stock/timeframe, shows the result, and close cancels pending work',()=>{
  const {Subject}=require('rxjs');const requests=[];
  const c=component({focusedOptionPlan:(key,mode,timeframe)=>{const stream=new Subject();requests.push({key,mode,timeframe,stream});return stream;}});
  const item=stock('TEST',[signal('ghost_rider','BUY')]);c.data={plans:[item]};c.timeframe='5m';
  c.checkOptions(item);assert.equal(c.optionLoading,true);assert.equal(requests[0].key,'TEST');assert.equal(requests[0].timeframe,'5m');
  requests[0].stream.next({action:'BUY CE',reason:'Passed',contract:{symbol:'TEST CE'}});requests[0].stream.complete();
  assert.equal(c.optionLoading,false);assert.equal(c.option.action,'BUY CE');assert.match(c.signalRows[0].optionHint,/TEST CE/);
  c.checkOptions(item);c.closeOptions();assert.equal(requests[1].stream.observed,false);assert.equal(c.optionFor,null);assert.equal(c.optionLoading,false);
  c.checkOptions(item);requests[2].stream.error({status:401});assert.equal(c.option.action,'WAIT');assert.match(c.option.reason,/Connect Upstox/);assert.equal(c.optionLoading,false);
});
