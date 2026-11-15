import { StockChoicesComponent } from '../shared/stock-choices.component';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, EventEmitter, Input, Output, OnChanges, OnInit, OnDestroy, inject } from '@angular/core';
import { Subscription, timeout } from 'rxjs';
import { MarketApiService, SelectedStock } from '../market-api.service';
import { StructureAnalysis, StructureView } from './structure.types';
// Kept for the retired strategy-grid action component's type contract.
import { FocusPlan, PlanEvidence } from './focused-plans.types';
export interface SignalRow { stock:FocusPlan; evidence:PlanEvidence; symbol:string; strategy:string; signal:string; state:string; timeframe:string; signalAt:string; entry?:number|null; stopLoss?:number|null; target?:number|null; reason:string; support:number; optionHint:string; }

@Component({selector:'app-focused',standalone:true,imports:[CommonModule,StockChoicesComponent],templateUrl:'./focused.component.html',styleUrl:'./focused.component.css'})
export class FocusedComponent implements OnInit, OnChanges, OnDestroy {
  private api=inject(MarketApiService);private http=inject(HttpClient);
  private request?:Subscription;private universeRequest?:Subscription;private initialized=false;
  @Input() active=true;@Output() stockSelected=new EventEmitter<SelectedStock>();
  stocks:SelectedStock[]=[];query='';selectedKey='';data:StructureAnalysis|null=null;
  loading=false;universeLoading=false;error='';universeError='';
  activeViewIndex=0;
  get activeView():StructureView|null{return this.data?.views[this.activeViewIndex]??null;}
  get matches():SelectedStock[]{const q=this.query.trim().toLowerCase();return this.stocks.filter(s=>!q||`${s.symbol} ${s.name}`.toLowerCase().includes(q));}
  ngOnInit():void{this.initialized=true;this.loadStocks();}
  ngOnChanges():void{if(!this.active){this.request?.unsubscribe();this.loading=false;}else if(this.initialized&&this.selectedKey&&!this.data)this.refresh();}
  ngOnDestroy():void{this.request?.unsubscribe();this.universeRequest?.unsubscribe();}
  loadStocks():void{
    this.universeLoading=true;this.universeError='';this.universeRequest?.unsubscribe();
    this.universeRequest=this.api.fnoStocks().pipe(timeout(15000)).subscribe({next:r=>{this.stocks=r.stocks.sort((a,b)=>a.symbol.localeCompare(b.symbol));this.universeLoading=false;},error:()=>{this.universeLoading=false;this.universeError='Could not load the stock list. Retry to select a stock.';}});
  }
  get selectedSymbol():string{return this.stocks.find(s=>s.key===this.selectedKey)?.symbol??'';}
  chooseSymbol(symbol:string):void{this.query='';this.select(this.stocks.find(s=>s.symbol===symbol)?.key??'');}
  select(key:string):void{this.request?.unsubscribe();this.selectedKey=key;this.data=null;this.error='';this.loading=false;if(key)this.refresh();}
  refresh():void{
    if(!this.selectedKey||!this.active)return;
    this.request?.unsubscribe();this.data=null;this.loading=true;this.error='';
    this.request=this.http.get<StructureAnalysis>('/api/focused/structure',{params:{instrument_key:this.selectedKey}}).pipe(timeout(100000)).subscribe({next:data=>{this.data=data;this.loading=false;},error:e=>{this.loading=false;this.error=e.error?.detail||'Analysis could not be loaded. Retry to read the available history.';}});
  }
  selectView(index:number):void{if(this.data?.views[index])this.activeViewIndex=index;}
  tabKey(event:KeyboardEvent,index:number):void{
    const total=this.data?.views.length??0;if(!total)return;
    const next=event.key==='ArrowRight'?(index+1)%total:event.key==='ArrowLeft'?(index+total-1)%total:event.key==='Home'?0:event.key==='End'?total-1:null;
    if(next!==null){event.preventDefault();this.selectView(next);document.getElementById('timeframe-tab-'+next)?.focus();}
  }
  shortTrend(view:StructureView):string{return this.tone(view)==='up'?'Rising':this.tone(view)==='down'?'Falling':!view.count?'No history':view.trend.includes('Insufficient')?'Limited swings':'Mixed';}
  summaryLines(view:StructureView):string[]{
    const move=view.narrative.find(line=>line.startsWith('Fell from')||line.startsWith('Rose from'));
    const swings=view.narrative.find(line=>line.startsWith('Latest confirmed'));
    return [move,swings].filter((line):line is string=>!!line).length?[move,swings].filter((line):line is string=>!!line):view.narrative.slice(0,2);
  }
  tone(view:StructureView):string{return view.trend==='Higher highs / higher lows'?'up':view.trend==='Lower highs / lower lows'?'down':'neutral';}
  get overview():string{
    const views=this.data?.views.filter(v=>v.count)??[];
    if(!views.length)return 'No completed price history is available.';
    const up=views.filter(v=>this.tone(v)==='up').length;const down=views.filter(v=>this.tone(v)==='down').length;
    return `${up} of ${views.length} available views show higher highs and higher lows; ${down} show lower highs and lower lows. The review windows overlap, so these are context views, not independent confirmations.`;
  }
}
