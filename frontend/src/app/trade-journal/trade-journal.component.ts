import { MarketApiService } from '../market-api.service';
import { CommonModule } from '@angular/common';
import { Component, HostListener, OnDestroy, OnInit, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { JournalApiService, JournalTrade, WorkbookReference } from './journal-api.service';

interface Breakdown { label: string; count: number; net: number; wins: number; width: number; }
interface Field { key: keyof JournalTrade; label: string; type: 'text' | 'number' | 'textarea' | 'select' | 'boolean'; options?: string[]; min?: number; max?: number; }

@Component({ selector: 'app-trade-journal', standalone: true, imports: [CommonModule], templateUrl: './trade-journal.component.html', styleUrl: './trade-journal.component.css' })
export class TradeJournalComponent implements OnInit, OnDestroy {
  readonly Math = Math;
  private readonly marketApi = inject(MarketApiService);
  private readonly api = inject(JournalApiService);
  private readonly subscriptions = new Subscription();
  private readonly cache = new Map<string, {dependencies: unknown[]; value: any}>();
  private memo<T>(key:string, dependencies:unknown[], calculate:()=>T):T {
    const cached=this.cache.get(key);
    if(cached&&dependencies.length===cached.dependencies.length&&dependencies.every((v,i)=>Object.is(v,cached.dependencies[i])))return cached.value;
    const value=calculate();this.cache.set(key,{dependencies,value});return value;
  }

  readonly sections = ['Dashboard', 'Calendar', 'Trade Log', 'Reflections', 'Reports', 'Scaling Simulator', 'Settings'];
  view = 'Dashboard'; trades: JournalTrade[] = []; reference?: WorkbookReference;
  loading = false; saving = false; error = ''; notice = ''; account = ''; period = 'All time'; from = ''; to = '';
  search = ''; side = ''; outcome = ''; page = 1; calendarMonth = this.day(new Date().toISOString()).slice(0, 7); calendarDay = '';
  privacy = false; startingBalance = 0; scale = 1;
  modal: 'trade' | 'import' | 'delete' | '' = ''; formTab = 'Execution'; form = this.blank(); entryLocal = ''; exitLocal = ''; pendingDelete?: JournalTrade;
  private focusBefore?: HTMLElement; private previousOverflow = '';
  private readonly textFields = (pairs: [keyof JournalTrade, string][], type: Field['type'] = 'text'): Field[] => pairs.map(([key, label]) => ({ key, label, type }));
  readonly fields: Record<string, Field[]> = {
    Execution: [
      ...this.textFields([['account','Account']]),
      {key:'symbol',label:'F&O underlying stock',type:'select',options:['']},
      {key:'segment',label:'Segment',type:'select',options:['Equity','Futures','Options']},
      ...this.textFields([['instrumentType','Contract / CE / PE'],['timeframe','Timeframe']]),
      {key:'direction',label:'Direction',type:'select',options:['LONG','SHORT']},
      ...(['entryPrice','exitPrice','quantity','lotSize','charges'] as const).map(key => ({key,label:({entryPrice:'Entry price ₹',exitPrice:'Exit price ₹ (blank = open)',quantity:'Position quantity (units)',lotSize:'Units per lot',charges:'Total charges ₹'} as const)[key],type:'number' as const,min:key==='charges'?0:0.000001})),
      {key:'exitReason',label:'Exit reason',type:'select',options:['','Target','Stop','Trailing','Manual','Other']},
      ...this.textFields([['chartLink','Chart / screenshot URL']]),
    ],
    'Plan & Evidence': [
      ...(['capital','riskPercent','stopPrice','targetPrice','recordedRisk','rsi'] as const).map(key => ({key,label:({capital:'Trading capital ₹',riskPercent:'Risk budget % (1 means 1%)',stopPrice:'Planned stop ₹',targetPrice:'Planned target ₹',recordedRisk:'Recorded risk ₹ (if no stop)',rsi:'RSI at entry'} as const)[key],type:'number' as const,min:key==='rsi'?0:0.000001,max:key==='riskPercent'||key==='rsi'?100:undefined})),
      ...this.textFields([['setup','Setup / pattern'],['marketTrend','Market trend / context'],['fibLevel','Fibonacci level'],['divergence','Divergence type']]),
      ...this.textFields([['reason','Reason for entry'],['evidence','Confirmation / evidence'],['supportResistance','Support / resistance'],['trendline','Trendline'],['volumeConfirmation','Volume confirmation']], 'textarea'),
    ],
    Psychology: [
      ...this.textFields([['emotionBefore','Emotion before entry'],['emotionDuring','Emotion during trade'],['emotionAfter','Emotion after exit']]),
      {key:'confidence',label:'Setup confidence (1–10)',type:'number',min:1,max:10},
      ...(['entryFollowed','stopFollowed','exitFollowed'] as const).map(key=>({key,label:({entryFollowed:'Entry rule followed?',stopFollowed:'Stop rule followed?',exitFollowed:'Exit rule followed?'} as const)[key],type:'boolean' as const})),
    ],
    Review: [
      ...this.textFields([['mistake','Mistakes / rules broken'],['didWell','What went well'],['learned','Lesson learned'],['notes','Notes']], 'textarea'),
      {key:'wouldTakeAgain',label:'Would take this setup again?',type:'boolean'},
      {key:'rating',label:'Trade rating (1–10)',type:'number',min:1,max:10},
    ],
  };
  readonly formTabs = ['Execution','Plan & Evidence','Psychology','Review'];
  ngOnInit(): void {
    this.subscriptions.add(this.marketApi.fnoStocks().subscribe({
      next: data => { this.fields['Execution'].find(field => field.key === 'symbol')!.options = ['', ...data.stocks.map(stock => stock.symbol)]; },
      error: () => this.error = 'Could not load the F&O stock list. Refresh to retry.'
    }));
    try { const s=JSON.parse(localStorage.getItem('tg-journal-settings') || '{}'); this.privacy=!!s.privacy; this.startingBalance=Number(s.balance)||0; } catch {}
    this.load(); this.subscriptions.add(this.api.reference().subscribe({next:r=>this.reference=r}));
  }
  ngOnDestroy(): void { this.subscriptions.unsubscribe(); if(this.modal) document.body.style.overflow=this.previousOverflow; }
  load(): void { this.loading=true; this.error=''; this.subscriptions.add(this.api.list().subscribe({next:r=>{this.trades=r.trades.map(t=>this.normalize(t));this.loading=false;},error:e=>{this.loading=false;this.fail(e);}})); }
  private normalize(t: JournalTrade): JournalTrade {
    const row={...t}; for(const field of ['entryPrice','exitPrice','charges','capital','riskPercent','stopPrice','targetPrice','recordedRisk','rsi'] as const) if(row[field]!=null) row[field]=Number(row[field]); return row;
  }
  blank(): JournalTrade { return {account:'Main account',symbol:'',segment:'Equity',instrumentType:'',timeframe:'Daily',direction:'LONG',entryAt:'',exitAt:null,entryPrice:0,exitPrice:null,quantity:1,lotSize:1,charges:0,capital:null,riskPercent:null,stopPrice:null,targetPrice:null,recordedRisk:null,setup:'',marketTrend:'',reason:'',evidence:'',fibLevel:'',rsi:null,divergence:'',supportResistance:'',trendline:'',volumeConfirmation:'',emotionBefore:'',emotionDuring:'',emotionAfter:'',confidence:null,rating:null,entryFollowed:null,stopFollowed:null,exitFollowed:null,wouldTakeAgain:null,mistake:'',didWell:'',learned:'',exitReason:'',chartLink:'',notes:''}; }
  day(iso: string): string { return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(iso)); }
  local(iso: string): string { const date=this.day(iso); const time=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(iso)); return `${date}T${time}`; }
  get accounts(): string[] { return [...new Set(this.trades.map(t=>t.account))].sort(); }
  get filtered(): JournalTrade[] { return this.memo('filtered',[this.trades,this.account,this.from,this.to],()=>this.trades.filter(t=>{const d=this.day(t.exitAt||t.entryAt);return (!this.account||t.account===this.account)&&(!this.from||d>=this.from)&&(!this.to||d<=this.to); })); }
  get closed(): JournalTrade[] { return this.memo('closed',[this.filtered],()=>this.filtered.filter(t=>t.netPnl!=null).sort((a,b)=>Date.parse(a.exitAt!)-Date.parse(b.exitAt!)||(a.id||0)-(b.id||0))); }
  get logRows(): JournalTrade[] { return this.memo('log',[this.filtered,this.search,this.side,this.outcome],()=>{ const query=this.search.toLowerCase();return this.filtered.filter(t=>(!query||`${t.symbol} ${t.setup} ${t.notes}`.toLowerCase().includes(query))&&(!this.side||t.direction===this.side)&&(!this.outcome||t.result===this.outcome)).sort((a,b)=>Date.parse(b.entryAt)-Date.parse(a.entryAt)); }); }
  get pagedRows(): JournalTrade[] { return this.logRows.slice((this.page-1)*25,this.page*25); }
  get pageCount(): number { return Math.max(1,Math.ceil(this.logRows.length/25)); }
  get stats() { return this.memo('stats',[this.closed,this.filtered],()=>{
    const rows=this.closed, values=rows.map(t=>t.netPnl!), wins=values.filter(v=>v>0),losses=values.filter(v=>v<0);
    const sum=(v:number[])=>v.reduce((a,b)=>a+b,0), average=(v:number[])=>v.length?sum(v)/v.length:null;
    let equity=0,peak=0,drawdown=0,streak=0,maxWin=0,maxLoss=0;
    for(const value of values){equity+=value;peak=Math.max(peak,equity);drawdown=Math.max(drawdown,peak-equity);streak=value>0?(streak>0?streak+1:1):value<0?(streak<0?streak-1:-1):0;maxWin=Math.max(maxWin,streak);maxLoss=Math.max(maxLoss,-streak);}
    const winning=sum(wins), losing=-sum(losses);
    return {count:rows.length,open:this.filtered.length-rows.length,net:sum(values),wins:wins.length,losses:losses.length,breakeven:values.filter(v=>v===0).length,winRate:rows.length?wins.length/rows.length*100:null,profitFactor:losing?winning/losing:winning?Infinity:null,expectancy:average(values),avgWin:average(wins),avgLoss:average(losses),largestWin:wins.length?Math.max(...wins):null,largestLoss:losses.length?Math.min(...losses):null,drawdown,streak,maxWin,maxLoss,averageR:average(rows.filter(t=>t.rMultiple!=null).map(t=>t.rMultiple!)),ruleViolations:this.filtered.reduce((n,t)=>n+[t.entryFollowed,t.stopFollowed,t.exitFollowed].filter(v=>v===false).length,0)};
  }); }
  get possibleReentries(): number { return this.memo('reentry',[this.filtered,this.trades],()=>{
    const accounts=new Map<string,JournalTrade[]>();
    for(const trade of this.trades.filter(t=>t.exitAt)) { const rows=accounts.get(trade.account)||[];rows.push(trade);accounts.set(trade.account,rows); }
    for(const rows of accounts.values())rows.sort((a,b)=>Date.parse(a.exitAt!)-Date.parse(b.exitAt!));
    let count=0;
    for(const trade of this.filtered){const rows=accounts.get(trade.account)||[];const entry=Date.parse(trade.entryAt);let low=0,high=rows.length;
      while(low<high){const mid=Math.floor((low+high)/2);if(Date.parse(rows[mid].exitAt!)<=entry)low=mid+1;else high=mid;}
      let index=low-1;while(index>=0&&rows[index].id===trade.id)index--;
      const prior=rows[index];if(prior&&prior.netPnl!=null&&prior.netPnl<0&&entry-Date.parse(prior.exitAt!)<300000)count++;
    }return count;
  }); }
  get daily(): {date:string;net:number;count:number}[] { const map=new Map<string,{date:string;net:number;count:number}>();for(const t of this.closed){const d=this.day(t.exitAt!);const r=map.get(d)||{date:d,net:0,count:0};r.net+=t.netPnl!;r.count++;map.set(d,r);}return [...map.values()].sort((a,b)=>a.date.localeCompare(b.date)); }
  get equity(): {date:string;value:number}[] { let value=this.startingBalance;return [{date:'Start',value},...this.closed.map(t=>({date:this.day(t.exitAt!),value:value+=t.netPnl!}))]; }
  get equityPath(): string { const points=this.equity;const values=points.map(p=>p.value);const min=Math.min(...values),max=Math.max(...values),range=max-min||1;return points.map((p,i)=>`${i?'L':'M'}${20+i/(Math.max(1,points.length-1))*760},${180-(p.value-min)/range*155}`).join(' '); }
  get dailyBars(): {date:string;net:number;x:number;y:number;height:number;width:number}[] {const rows=this.daily.slice(-60);const max=Math.max(1,...rows.map(r=>Math.abs(r.net)));return rows.map((r,i)=>({...r,x:20+i*760/rows.length+Math.max(0,(760/rows.length-36)/2),y:r.net>=0?105-r.net/max*85:105,height:Math.max(1,Math.abs(r.net)/max*85),width:Math.max(2,Math.min(36,760/rows.length-3))})); }
  get bestDays() { return [...this.daily].sort((a,b)=>b.net-a.net).slice(0,5); }
  breakdown(field: keyof JournalTrade): Breakdown[] { const map=new Map<string,Breakdown>();for(const t of this.closed){const label=String(t[field]||'Not recorded');const row=map.get(label)||{label,count:0,net:0,wins:0,width:0};row.count++;row.net+=t.netPnl!;row.wins+=t.netPnl!>0?1:0;map.set(label,row);}const rows=[...map.values()].sort((a,b)=>b.net-a.net);const max=Math.max(1,...rows.map(r=>Math.abs(r.net)));return rows.map(r=>({...r,width:Math.abs(r.net)/max*100})); }
  get sessions(): Breakdown[] { const labels=['Before 09:15','09:15–11:00','11:00–13:00','13:00–15:30','After 15:30'];const rows=labels.map(label=>({label,count:0,net:0,wins:0,width:0}));for(const t of this.closed){const local=this.local(t.entryAt).slice(11);const n=Number(local.slice(0,2))*60+Number(local.slice(3));const r=rows[n<555?0:n<660?1:n<780?2:n<930?3:4];r.count++;r.net+=t.netPnl!;}return rows; }
  get hourly(): {label:string;net:number;count:number;width:number}[] {const rows=Array.from({length:24},(_,i)=>({label:`${String(i).padStart(2,'0')}:00`,net:0,count:0,width:0}));for(const t of this.closed){const r=rows[Number(this.local(t.entryAt).slice(11,13))];r.net+=t.netPnl!;r.count++;}const max=Math.max(1,...rows.map(r=>Math.abs(r.net)));return rows.filter(r=>r.count).map(r=>({...r,width:Math.abs(r.net)/max*100})); }
  get distribution(): {label:string;count:number;positive:boolean;width:number}[] {const values=this.closed.map(t=>t.netPnl!);if(!values.length)return [];const min=Math.min(...values),max=Math.max(...values);if(min===max)return [{label:this.money(min),count:values.length,positive:min>=0,width:100}];const step=(max-min)/8;const bins=Array.from({length:8},(_,i)=>({label:`${this.money(min+i*step)} – ${this.money(min+(i+1)*step)}`,count:0,positive:min+(i+.5)*step>=0,width:0}));for(const v of values)bins[Math.min(7,Math.floor((v-min)/step))].count++;const highest=Math.max(...bins.map(b=>b.count));return bins.map(b=>({...b,width:b.count/highest*100})); }
  selectPeriod(period:string): void {this.period=period;this.page=1;this.calendarDay='';const today=this.day(new Date().toISOString());this.to=period==='All time'?'':today;const [y,m,d]=today.split('-').map(Number);const date=new Date(`${today}T12:00:00Z`);this.from=period==='Today'?today:period==='This month'?`${y}-${String(m).padStart(2,'0')}-01`:period==='YTD'?`${y}-01-01`:period==='This week'?this.day(new Date(date.getTime()-((date.getUTCDay()+6)%7)*86400000).toISOString()):''; }
  get calendarCells(): {date:string;day:number;net:number;count:number}[] {const [year,month]=this.calendarMonth.split('-').map(Number);if(!year||!month)return [];const first=new Date(Date.UTC(year,month-1,1));const padding=(first.getUTCDay()+6)%7;const count=new Date(Date.UTC(year,month,0)).getUTCDate();const daily=new Map(this.daily.map(d=>[d.date,d]));return [...Array.from({length:padding},()=>({date:'',day:0,net:0,count:0})),...Array.from({length:count},(_,i)=>{const date=`${this.calendarMonth}-${String(i+1).padStart(2,'0')}`;return {date,day:i+1,net:daily.get(date)?.net||0,count:daily.get(date)?.count||0};})]; }
  get calendarTrades(): JournalTrade[] {return this.closed.filter(t=>this.calendarDay&&this.day(t.exitAt!)===this.calendarDay);}
  openModal(modal: typeof this.modal): void {this.focusBefore=document.activeElement as HTMLElement;this.previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';this.modal=modal;setTimeout(()=>document.querySelector<HTMLElement>('.journal-modal input, .journal-modal button')?.focus());}
  closeModal(): void {if(this.saving)return;this.modal='';document.body.style.overflow=this.previousOverflow;this.focusBefore?.focus();}
  edit(trade?:JournalTrade): void {this.error='';this.form=trade?{...trade}:this.blank();this.entryLocal=trade?this.local(trade.entryAt):this.local(new Date().toISOString());this.exitLocal=trade?.exitAt?this.local(trade.exitAt):'';this.formTab='Execution';this.openModal('trade');}
  setField(field:Field,value:string): void { const parsed=field.type==='number'?(value===''?null:Number(value)):field.type==='boolean'?(value===''?null:value==='true'):value;this.form={...this.form,[field.key]:parsed}; }
  get livePlan() {const t=this.form;const risk=t.stopPrice!=null?Math.abs(Number(t.entryPrice)-Number(t.stopPrice)):null;const planned=risk!=null?risk*Number(t.quantity):t.recordedRisk;const budget=t.capital!=null&&t.riskPercent!=null?Number(t.capital)*Number(t.riskPercent)/100:null;const gross=t.exitPrice!=null?(Number(t.exitPrice)-Number(t.entryPrice))*(t.direction==='LONG'?1:-1)*Number(t.quantity):null;return {planned,budget,recommended:risk&&budget!=null?Math.floor(budget/(risk*Number(t.lotSize))):null,net:gross==null?null:gross-Number(t.charges||0),rr:risk&&t.targetPrice!=null?Math.abs(Number(t.targetPrice)-Number(t.entryPrice))/risk:null};}
  save(): void {if(this.saving)return;this.form={...this.form,entryAt:this.entryLocal?this.entryLocal+':00+05:30':'',exitAt:this.exitLocal?this.exitLocal+':00+05:30':null};this.saving=true;this.error='';this.subscriptions.add(this.api.save(this.form).subscribe({next:t=>{this.saving=false;const row=this.normalize(t);this.trades=[row,...this.trades.filter(t=>t.id!==row.id)];this.notice='Trade saved';this.closeModal();},error:e=>{this.saving=false;this.fail(e);}}));}
  askDelete(trade:JournalTrade): void {this.pendingDelete=trade;this.openModal('delete');}
  remove(): void {if(!this.pendingDelete?.id||this.saving)return;this.saving=true;this.subscriptions.add(this.api.remove(this.pendingDelete.id).subscribe({next:()=>{this.trades=this.trades.filter(t=>t.id!==this.pendingDelete!.id);this.saving=false;this.closeModal();this.notice='Trade deleted';},error:e=>{this.saving=false;this.fail(e);}}));}
  importProvided(): void {this.saving=true;this.subscriptions.add(this.api.importProvided().subscribe({next:r=>{this.saving=false;this.closeModal();this.notice=`Imported ${r.added} trade(s); ${r.duplicates} already present. Review source warnings in the imported trade notes.`;this.load();},error:e=>{this.saving=false;this.fail(e);}}));}
  exportCsv(): void {const rows=this.logRows;const fields=['id',...this.formTabs.flatMap(tab=>this.fields[tab].map(f=>f.key)),'entryAt','exitAt','grossPnl','netPnl','plannedRisk','plannedRR','rMultiple','result'];const escape=(v:unknown)=>{let s=String(v??'');if(/^\s*[=+@-]/.test(s)&&typeof v!=='number')s="'"+s;return '"'+s.replaceAll('"','""')+'"';};const csv=[fields.map(escape).join(','),...rows.map(t=>fields.map(f=>escape(t[f as keyof JournalTrade])).join(','))].join('\r\n');const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8;'}));const a=document.createElement('a');a.href=url;a.download='traders-gita-journal.csv';a.click();URL.revokeObjectURL(url);}
  saveSettings(): void {this.startingBalance=Math.max(0,Number(this.startingBalance)||0);localStorage.setItem('tg-journal-settings',JSON.stringify({privacy:this.privacy,balance:this.startingBalance}));this.notice='Display settings saved on this browser';}
  setScale(value:number): void {this.scale=Number.isFinite(value)?Math.max(.1,Math.min(100,value)):1;}
  money(value:number|null|undefined): string {return value==null?'—':this.privacy?'₹ ••••':new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(value);}
  number(value:number|null|undefined,digits=2): string {return value==null?'—':!Number.isFinite(value)?'∞':value.toFixed(digits);}
  private fail(e:any):void {const detail=e.error?.detail;this.error=typeof detail==='string'?detail:Array.isArray(detail)?detail.map(d=>`${d.loc?.slice(1).join('.')}: ${d.msg}`).join(' · '):'Journal unavailable. Restart the backend if this feature was just added.';}
  @HostListener('document:keydown', ['$event']) keyboard(event:KeyboardEvent):void {if(!this.modal)return;if(event.key==='Escape')this.closeModal();if(event.key==='Tab'){const controls=Array.from(document.querySelectorAll<HTMLElement>('.journal-modal button:not([disabled]),.journal-modal input:not([disabled]),.journal-modal select:not([disabled]),.journal-modal textarea:not([disabled])'));const first=controls[0],last=controls.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}}
}
