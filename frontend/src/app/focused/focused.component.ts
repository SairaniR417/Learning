import { CommonModule } from '@angular/common';
import { Component,EventEmitter,Input,OnChanges,OnDestroy,OnInit,Output,inject } from '@angular/core';
import { Subscription,exhaustMap,switchMap,takeWhile,timeout,timer,interval } from 'rxjs';
import { MarketApiService,SelectedStock } from '../market-api.service';
import { OptionAnalysisComponent } from '../option-market/option-analysis.component';
import { FocusMode,FocusPlan,FocusPlans,OptionPlan } from './focused-plans.types';

@Component({selector:'app-focused',standalone:true,imports:[CommonModule,OptionAnalysisComponent],templateUrl:'./focused.component.html',styleUrl:'./focused.component.css'})
export class FocusedComponent implements OnInit,OnChanges,OnDestroy {
  private api=inject(MarketApiService);private request?:Subscription;private optionRequest?:Subscription;private clock?:Subscription;private polling?:Subscription;private initialized=false;
  @Input() active=true;@Output() stockSelected=new EventEmitter<SelectedStock>();
  mode:FocusMode='intraday';data:FocusPlans|null=null;loading=false;error='';stage='';page=0;filter='all';now=Date.now();
  optionFor:FocusPlan|null=null;option:OptionPlan|null=null;optionLoading=false;chartStock:FocusPlan|null=null;
  ngOnInit():void{this.initialized=true;this.refresh();this.clock=interval(15000).subscribe(()=>this.now=Date.now());this.polling=interval(60000).subscribe(()=>{if(this.active&&!document.hidden&&!this.chartStock)this.refresh();});}
  ngOnChanges():void{if(!this.active){this.request?.unsubscribe();this.optionRequest?.unsubscribe();this.loading=false;this.optionLoading=false;}else if(this.initialized)this.refresh();}
  ngOnDestroy():void{this.request?.unsubscribe();this.optionRequest?.unsubscribe();this.clock?.unsubscribe();this.polling?.unsubscribe();}
  selectMode(mode:FocusMode):void{if(mode===this.mode)return;this.request?.unsubscribe();this.optionRequest?.unsubscribe();this.mode=mode;this.data=null;this.loading=false;this.optionLoading=false;this.option=null;this.optionFor=null;this.chartStock=null;this.page=0;this.refresh();}
  refresh():void{
    if(this.loading||!this.active||document.hidden)return;this.loading=true;this.error='';this.stage='Reading stored history';this.option=null;this.optionFor=null;this.optionRequest?.unsubscribe();this.optionLoading=false;
    this.request?.unsubscribe();this.request=this.api.startFocusedPlans(this.mode).pipe(timeout(15000),switchMap(job=>timer(0,1000).pipe(exhaustMap(()=>this.api.focusedPlansJob(job.id).pipe(timeout(15000))))),takeWhile(job=>job.status==='running',true)).subscribe({next:job=>{
      this.stage=job.stage;if(job.status==='complete'&&job.result){this.data=job.result;this.now=Date.now();this.loading=false;this.page=0;}if(job.status==='failed'){this.loading=false;this.error=job.error;}
    },error:e=>{this.loading=false;this.error=e.error?.detail||'Could not build complete trade plans. Retry Refresh.';}});
  }
  action(row:FocusPlan):string{
    if(row.action==='WAIT'||this.now>Date.parse(row.validUntil))return 'WAIT';
    const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(new Date(this.now));
    const part=(key:string)=>parts.find(p=>p.type===key)?.value??'';const minutes=Number(part('hour'))*60+Number(part('minute'));
    return ['Sat','Sun'].includes(part('weekday'))||minutes<555||minutes>=(row.mode==='intraday'?900:920)?'WAIT':row.action;
  }
  get rows():FocusPlan[]{return (this.data?.plans??[]).filter(r=>this.filter==='all'||(this.filter==='ready'?this.action(r)!=='WAIT':this.action(r)==='WAIT'));}
  get visible():FocusPlan[]{return this.rows.slice(this.page*5,this.page*5+5);}
  get readyCount():number{return (this.data?.plans??[]).filter(r=>this.action(r)!=='WAIT').length;}
  get headline():string{return this.readyCount?this.readyCount+' technical setups ready for entry-zone checks':'WAIT ? no fresh, aligned entry right now';}
  changeFilter(value:string):void{this.filter=value;this.page=0;}
  checkOptions(row:FocusPlan):void{
    this.optionRequest?.unsubscribe();this.optionFor=row;this.option=null;this.optionLoading=true;
    this.optionRequest=this.api.focusedOptionPlan(row.instrumentKey,this.mode).pipe(timeout(90000)).subscribe({next:r=>{this.option=r;this.optionLoading=false;},error:e=>{this.optionLoading=false;this.option={action:'WAIT',plan:null,reason:e.status===401?'Connect Upstox to verify an actual contract and live premium.':e.error?.detail||'Option data unavailable. No premium entry.'};}});
  }
  get optionAction():string{return this.option?.validUntil&&this.now>Date.parse(this.option.validUntil)?'WAIT ? quote expired':this.option?.action??'WAIT';}
}
