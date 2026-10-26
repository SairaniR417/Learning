import { CommonModule } from '@angular/common';
import { Component,EventEmitter,Input,OnChanges,OnDestroy,OnInit,Output,inject } from '@angular/core';
import { Subscription,exhaustMap,switchMap,takeWhile,timeout,timer,interval } from 'rxjs';
import { MarketApiService,SelectedStock } from '../market-api.service';
import { OptionAnalysisComponent } from '../option-market/option-analysis.component';
import { FocusMode,FocusTimeframe,FocusPlan,FocusPlans,OptionPlan,PlanEvidence } from './focused-plans.types';
import { AgGridAngular } from 'ag-grid-angular';
import { FocusedActionsComponent } from './focused-actions.component';
import { AllCommunityModule,ColDef,GridApi,GridReadyEvent,ModuleRegistry,RowClassParams,colorSchemeDark,themeQuartz } from 'ag-grid-community';

ModuleRegistry.registerModules([AllCommunityModule]);
export interface SignalRow { stock:FocusPlan; evidence:PlanEvidence; symbol:string; strategy:string; signal:string; state:string; timeframe:string; signalAt:string; entry?:number|null; stopLoss?:number|null; target?:number|null; reason:string; support:number; optionHint:string; }

@Component({selector:'app-focused',standalone:true,imports:[CommonModule,OptionAnalysisComponent,AgGridAngular],templateUrl:'./focused.component.html',styleUrl:'./focused.component.css'})
export class FocusedComponent implements OnInit,OnChanges,OnDestroy {
  private api=inject(MarketApiService);private request?:Subscription;private optionRequest?:Subscription;private clock?:Subscription;private polling?:Subscription;private initialized=false;
  @Input() active=true;@Output() stockSelected=new EventEmitter<SelectedStock>();
  timeframe:FocusTimeframe='1d';
  readonly timeframes:{value:FocusTimeframe;label:string}[]=[{value:'1m',label:'1 minute'},{value:'5m',label:'5 minutes'},{value:'15m',label:'15 minutes'},{value:'1h',label:'1 hour'},{value:'1d',label:'1 day'}];
  get timeframeLabel():string{return this.timeframes.find(t=>t.value===this.timeframe)?.label??this.timeframe;}
  mode:FocusMode='intraday';data:FocusPlans|null=null;loading=false;error='';stage='';filter='all';now=Date.now();
  optionFor:FocusPlan|null=null;option:OptionPlan|null=null;optionLoading=false;chartStock:FocusPlan|null=null;
  selected:SignalRow|null=null;chartStrategy='ghost_rider';strategyFilter='all';directionFilter='all';search='';shortlist:SignalRow[]=[];signalRows:SignalRow[]=[];private grid?:GridApi<SignalRow>;
  readonly gridTheme=themeQuartz.withPart(colorSchemeDark).withParams({backgroundColor:'#0d1712',foregroundColor:'#dce8e1',headerBackgroundColor:'#15251c',accentColor:'#8ee3ca',borderColor:'#2c4438',fontSize:12});
  readonly signalRowStyle=(p:RowClassParams<SignalRow>)=>({backgroundColor:p.data?.signal==='SELL'?'#28171d':'#0d1712'});
  readonly defaultColDef:ColDef<SignalRow>={sortable:true,filter:true,resizable:true,minWidth:100};
  readonly columnDefs:ColDef<SignalRow>[]=[
    {field:'symbol',headerName:'Stock',pinned:'left',width:130},
    {field:'signal',headerName:'Setup',pinned:'left',width:115,cellStyle:p=>({color:p.value==='BUY'?'#7ad5ad':p.value==='SELL'?'#ffd0d6':'#e5c578',backgroundColor:p.value==='SELL'?'#54242e':'transparent',fontWeight:'700'})},
    {field:'state',headerName:'Entry check',width:130,tooltipField:'reason',cellStyle:p=>({color:p.value==='READY'?'#7ad5ad':'#e5c578',fontWeight:'700'})},
    ...(['entry','stopLoss','target'] as const).map(field=>({field,headerName:field==='entry'?'Reference entry ₹':field==='stopLoss'?'Stop loss ₹':'Target ₹',width:145,valueFormatter:(p:{value:number|null|undefined})=>p.value==null?'—':p.value.toFixed(2)})),
    {field:'strategy',headerName:'Strategy signals',minWidth:200,flex:1,tooltipField:'strategy'},
    {field:'reason',headerName:'What to do',hide:true,minWidth:280,tooltipField:'reason',wrapText:true,autoHeight:true},
    {field:'optionHint',headerName:'Options',hide:true,width:200,tooltipField:'optionHint'},
    {headerName:'Candle (IST)',hide:true,width:170,valueGetter:p=>p.data?.stock.asOf,valueFormatter:p=>this.signalTime(p.value)},
    {headerName:'Actions',colId:'actions',width:250,minWidth:250,maxWidth:250,pinned:'right',resizable:false,sortable:false,filter:false,suppressKeyboardEvent:p=>p.event.key==='Enter'||p.event.key===' ',cellRenderer:FocusedActionsComponent,
      cellRendererParams:{onDetails:(row:SignalRow)=>this.openDetails(row),onChart:(row:SignalRow)=>this.openChart(row),onOptions:(row:SignalRow)=>this.openOptions(row),isChecking:(row:SignalRow)=>this.optionLoading&&this.optionFor?.instrumentKey===row.stock.instrumentKey}}
  ];
  gridReady(event:GridReadyEvent<SignalRow>):void{this.grid=event.api;}
  private reveal(id:string):void{setTimeout(()=>document.getElementById(id)?.scrollIntoView({behavior:'smooth',block:'start'}));}
  openDetails(row:SignalRow):void{this.selected=row;this.reveal('focused-details');}
  openChart(row:SignalRow):void{this.selected=row;this.chartStrategy=row.evidence.id;this.chartStock=row.stock;this.reveal('focused-chart');}
  openOptions(row:SignalRow):void{if(row.signal==='CONFLICT')return;this.selected=row;this.checkOptions(row.stock);this.reveal('focused-options');}
  signalTime(value:string):string{return value?new Date(value).toLocaleString('en-GB',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'—';}
  private stockRow(stock:FocusPlan):SignalRow|null{
    const usable=stock.evidence.filter(e=>e.signal&&!['INVALIDATED','NO_FRESH_SETUP','TARGET','STOP','BOTH','EXPIRED','CONFIRMED_WEAKENED'].includes(e.signalState??e.state));
    if(!usable.length)return null;
    const buys=usable.filter(e=>e.signal==='BUY'),sells=usable.filter(e=>e.signal==='SELL');
    const conflict=buys.length>0&&sells.length>0;
    const signal=conflict?'CONFLICT':buys.length?'BUY':'SELL';
    const agreeing=conflict?usable:usable.filter(e=>e.signal===signal);
    const ordered=[...agreeing].sort((a,b)=>Number(b.entry!=null&&b.stopLoss!=null)-Number(a.entry!=null&&a.stopLoss!=null)||Date.parse(b.signalAt??'')-Date.parse(a.signalAt??''));
    const source=ordered[0];
    const ready=!conflict&&this.action(stock)===signal;
    const combined=stock.direction===signal?stock.plan:null;
    // Never mix the opposite direction's combined levels with a source signal.
    const levels=ready&&combined?{entry:combined.entry,stopLoss:combined.stopLoss,target:combined.target1}:conflict?{}:{entry:source.entry,stopLoss:source.stopLoss,target:source.targets?.[0]};
    const needsRefresh=this.now>Date.parse(stock.validUntil);
    const reason=conflict?usable.map(e=>e.name+': '+e.signal).join('; ')+'. Conflicting strategies — no directional entry.':ready?'Entry checks passed. Consider only within the entry zone; exit at stop or target.':needsRefresh?'Watchlist only: refresh current-session candles before entering.':stock.waitReasons?.[0]??'Watchlist only: confirm the setup and current entry levels first.';
    let optionHint=signal==='BUY'?'CE candidate · not verified':signal==='SELL'?'PE candidate · not verified':'Wait for direction';
    if(this.optionFor?.instrumentKey===stock.instrumentKey){optionHint=this.optionLoading?'Checking contract…':this.option?`${this.optionAction}${this.option.contract?' · '+this.option.contract.symbol:''}`:optionHint;}
    return {stock,evidence:source,symbol:stock.symbol,strategy:agreeing.map(e=>e.name+' '+e.signal).join(' · '),signal,state:conflict?'CONFLICT':ready?'READY':'WATCH',timeframe:stock.timeframe,signalAt:source.signalAt??'',...levels,reason,support:agreeing.length,optionHint};
  }
  updateSignals():void{
    this.shortlist=(this.data?.plans??[]).map(stock=>this.stockRow(stock)).filter((r):r is SignalRow=>r!==null)
      .sort((a,b)=>Number(b.state==='READY')-Number(a.state==='READY')||Number(a.state==='CONFLICT')-Number(b.state==='CONFLICT')||b.support-a.support||Date.parse(b.signalAt)-Date.parse(a.signalAt)||a.symbol.localeCompare(b.symbol));
    if(this.selected)this.selected=this.shortlist.find(r=>r.stock.instrumentKey===this.selected?.stock.instrumentKey)??null;
    this.signalRows=this.shortlist.filter(r=>(this.strategyFilter==='all'||r.stock.evidence.some(e=>e.id===this.strategyFilter&&e.signal&&!['INVALIDATED','NO_FRESH_SETUP','TARGET','STOP','BOTH','EXPIRED','CONFIRMED_WEAKENED'].includes(e.signalState??e.state)))&&(this.directionFilter==='all'||r.signal===this.directionFilter)&&(this.filter==='all'||(this.filter==='ready'?r.state==='READY':r.state!=='READY')));
  }
  count(direction:string):number{return this.shortlist.filter(r=>r.signal===direction).length;}
  ngOnInit():void{this.initialized=true;this.refresh();this.clock=interval(15000).subscribe(()=>{this.now=Date.now();this.updateSignals();this.grid?.refreshCells({force:true});});this.polling=interval(60000).subscribe(()=>{if(this.active&&!document.hidden&&!this.chartStock)this.refresh();});}
  ngOnChanges():void{if(!this.active){this.request?.unsubscribe();this.optionRequest?.unsubscribe();this.loading=false;this.optionLoading=false;}else if(this.initialized)this.refresh();}
  ngOnDestroy():void{this.request?.unsubscribe();this.optionRequest?.unsubscribe();this.clock?.unsubscribe();this.polling?.unsubscribe();}
  selectTimeframe(value:FocusTimeframe):void{if(value===this.timeframe||!this.timeframes.some(t=>t.value===value))return;this.timeframe=value;this.resetScan();}
  selectMode(mode:FocusMode):void{if(mode===this.mode)return;this.mode=mode;this.resetScan();}
  private resetScan():void{this.request?.unsubscribe();this.optionRequest?.unsubscribe();this.data=null;this.loading=false;this.optionLoading=false;this.option=null;this.optionFor=null;this.chartStock=null;this.selected=null;this.shortlist=[];this.signalRows=[];this.refresh();}
  refresh():void{
    if(this.loading||!this.active||document.hidden)return;this.loading=true;this.error='';this.stage='Reading stored history';this.option=null;this.optionFor=null;this.optionRequest?.unsubscribe();this.optionLoading=false;this.updateSignals();
    this.request?.unsubscribe();this.request=this.api.startFocusedPlans(this.mode,this.timeframe).pipe(timeout(15000),switchMap(job=>timer(0,1000).pipe(exhaustMap(()=>this.api.focusedPlansJob(job.id).pipe(timeout(15000))))),takeWhile(job=>job.status==='running',true)).subscribe({next:job=>{
      this.stage=job.stage;if(job.status==='complete'&&job.result){this.data=job.result;this.now=Date.now();this.loading=false;this.selected=null;this.updateSignals();}if(job.status==='failed'){this.loading=false;this.error=job.error;}
    },error:e=>{this.loading=false;this.error=e.error?.detail||'Could not build complete trade plans. Retry Refresh.';}});
  }
  action(row:FocusPlan):string{
    if(row.action==='WAIT'||this.now>Date.parse(row.validUntil))return 'WAIT';
    const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(new Date(this.now));
    const part=(key:string)=>parts.find(p=>p.type===key)?.value??'';const minutes=Number(part('hour'))*60+Number(part('minute'));
    return ['Sat','Sun'].includes(part('weekday'))||minutes<555||minutes>=(row.mode==='intraday'?900:920)?'WAIT':row.action;
  }
  get readyCount():number{return this.shortlist.filter(r=>r.state==='READY').length;}
  get headline():string{return this.readyCount?this.readyCount+' stocks pass entry checks':'Watchlist for the next entry check — no stock ready now';}
  changeFilter(value:string):void{this.filter=value;this.updateSignals();}
  closeOptions():void{this.optionRequest?.unsubscribe();this.optionFor=null;this.option=null;this.optionLoading=false;this.updateSignals();}
  checkOptions(row:FocusPlan):void{
    this.optionRequest?.unsubscribe();this.optionFor=row;this.option=null;this.optionLoading=true;this.updateSignals();
    this.optionRequest=this.api.focusedOptionPlan(row.instrumentKey,this.mode,this.timeframe).pipe(timeout(90000)).subscribe({next:r=>{this.option=r;this.optionLoading=false;this.updateSignals();},error:e=>{this.optionLoading=false;this.option={action:'WAIT',plan:null,reason:e.status===401?'Connect Upstox to verify an actual contract and live premium.':e.error?.detail||'Option data unavailable. No premium entry.'};this.updateSignals();}});
  }
  get optionAction():string{return this.option?.validUntil&&this.now>Date.parse(this.option.validUntil)?'WAIT · quote expired':this.option?.action??'WAIT';}
}
