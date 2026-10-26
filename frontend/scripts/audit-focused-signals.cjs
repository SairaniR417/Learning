// Verify the actual Angular shortlist mapping against the read-only DB audit.
// Run after scripts/audit_focused_signals.py: node scripts/audit-focused-signals.cjs
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const root=path.resolve(__dirname,'../..');
const report=JSON.parse(fs.readFileSync(path.join(root,'data/focused-signal-audit.json'),'utf8'));
const compiled={exports:{}};
const theme={withPart(){return this;},withParams(){return this;}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(root,'frontend/src/app/focused/focused.component.ts'),'utf8'),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,experimentalDecorators:true}
}).outputText,{
  module:compiled,exports:compiled.exports,Intl,Date,
  require:name=>name==='@angular/core'?{Component:()=>x=>x,Input:()=>()=>{},Output:()=>()=>{},EventEmitter:class{},inject:()=>({})}:
    name==='ag-grid-community'?{ModuleRegistry:{registerModules(){}},themeQuartz:theme}:{}
});
const component=new compiled.exports.FocusedComponent();
component.now=Date.parse(report.auditedAt);
const failures=[];
const frames={};
for(const [timeframe,frame] of Object.entries(report.frames)){
  const plans=report.frontendPlans.filter(p=>p.timeframe===timeframe);
  component.timeframe=timeframe;component.data={plans};component.updateSignals();
  const snapshots=new Map(frame.snapshots.map(s=>[s.symbol,s]));
  const counts={stocks:plans.length,shortlisted:component.shortlist.length,buy:0,sell:0,conflict:0,ready:0,watch:0};
  for(const plan of plans){
    const source=snapshots.get(plan.symbol).sourceDirections;
    const directions=new Set(Object.values(source).filter(Boolean));
    const rsi=plan.evidence.find(e=>e.id==='rsi_divergence');
    if(rsi?.signal&&!['INVALIDATED','NO_FRESH_SETUP'].includes(rsi.signalState??rsi.state))directions.add(rsi.signal);
    const expected=directions.size>1?'CONFLICT':directions.values().next().value;
    const row=component.shortlist.find(r=>r.stock.instrumentKey===plan.instrumentKey);
    const fail=reason=>failures.push({symbol:plan.symbol,timeframe,reason});
    if((row?.signal)!==expected)fail(`Expected ${expected}, displayed ${row?.signal}`);
    if(!row)continue;
    counts[row.signal.toLowerCase()]++;
    counts[row.state==='READY'?'ready':'watch']++;
    if(row.signal==='CONFLICT'&&[row.entry,row.stopLoss,row.target].some(v=>v!=null))fail('Conflict exposes trade levels');
    if(row.state==='READY'&&(component.action(plan)!==row.signal||plan.waitReasons.length))fail('Blocked setup promoted to READY');
    if(row.signal!=='CONFLICT'&&row.entry!=null&&row.stopLoss!=null&&row.target!=null){
      if(!(row.signal==='BUY'?row.stopLoss<row.entry&&row.entry<row.target:row.target<row.entry&&row.entry<row.stopLoss))fail('Source entry, stop and target direction disagree');
    }
  }
  frames[timeframe]=counts;
}
const result={auditedAt:report.auditedAt,frames,failures};
fs.writeFileSync(path.join(root,'data/focused-shortlist-audit.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result,null,2));
process.exitCode=failures.length?1:0;
