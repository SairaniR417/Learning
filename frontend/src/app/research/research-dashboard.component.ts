import { StockChoicesComponent } from '../shared/stock-choices.component';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, inject } from '@angular/core';
import { ResearchValueDirective } from './research-value.directive';
import { Subscription, timeout } from 'rxjs';
import { MarketApiService, OptionUnderlying } from '../market-api.service';
import { OptionAnalysisComponent } from '../option-market/option-analysis.component';
import { OptionChainComponent } from '../stock-details/option-chain.component';
import { ResearchChartComponent } from './research-chart.component';
import { Frame, Levels, RESEARCH_VIEWS, ResearchSnapshot, ResearchStock } from './research.types';

@Component({ selector: 'app-research-dashboard', standalone: true,
  imports: [StockChoicesComponent, CommonModule, ResearchValueDirective, ResearchChartComponent, OptionAnalysisComponent, OptionChainComponent],
  templateUrl: './research-dashboard.component.html', styleUrl: './research-dashboard.component.css' })
export class ResearchDashboardComponent implements OnInit, OnChanges, OnDestroy {
  @Input() view = 'research_radar';
  @Output() viewChange = new EventEmitter<string>();
  readonly views = RESEARCH_VIEWS;
  readonly frames: Frame[] = ['hourly','daily','weekly','monthly'];
  readonly regimes = ['quarterly','monthly','weekly','daily','hourly'];
  private http = inject(HttpClient);
  private api = inject(MarketApiService);
  private request?: Subscription;
  private indicesRequest?: Subscription;
  snapshot?: ResearchSnapshot;
  loading = false; error = ''; query = ''; direction = ''; sector = ''; period = 'daily'; frame: Frame = 'daily'; page = 0;
  selectedKey = ''; indices: OptionUnderlying[] = []; indexKey = ''; indexError = ''; indexMode = 'chart'; indexFrame = '1h';
  importText = ''; importError = ''; imported: { symbol: string; price: string; cpr: string; sutradhar: string }[] = [];
  legs = [{ side: 'BUY', type: 'CE', strike: 0, premium: 0, quantity: 1 }, { side: 'SELL', type: 'CE', strike: 0, premium: 0, quantity: 1 }];
  get title(): string { return this.views.find(v => v.id === this.view)?.name ?? 'Research'; }
  get stocks(): ResearchStock[] { return this.snapshot?.stocks ?? []; }
  get filtered(): ResearchStock[] { const q = this.query.trim().toLowerCase(); return this.stocks.filter(s => (!q || `${s.symbol} ${s.name}`.toLowerCase().includes(q)) && (!this.direction || s.bias === this.direction) && (!this.sector || s.sector === this.sector)); }
  get selected(): ResearchStock | undefined { return this.stocks.find(s => s.key === this.selectedKey) ?? this.filtered[0]; }
  get available(): number { return this.stocks.filter(s => s.price !== null).length; }
  count(bias: string): number { return this.stocks.filter(s => s.bias === bias).length; }
  get pressureCounts(): { label: string; count: number; tone: string }[] { return ['BUYING','SELLING','NEUTRAL','UNAVAILABLE'].map(label => ({ label, count: this.filtered.filter(s => s.pressure['1h'].state === label).length, tone: this.tone(label) })); }
  get tiles(): ResearchStock[] { return this.filtered.slice(this.safePage * 12, this.safePage * 12 + 12); }
  get trendCandidates(): ResearchStock[] { return this.filtered.filter(s => s.trendlines[this.frame === 'monthly' ? 'monthly' : 'weekly']?.length); }
  get totalPages(): number { return Math.max(1,Math.ceil((this.view === 'research_trends' ? this.trendCandidates : this.filtered).length / 12)); }
  get safePage(): number { return Math.min(this.page, this.totalPages - 1); }
  get trendStocks(): ResearchStock[] { return this.trendCandidates.slice(this.safePage * 12, this.safePage * 12 + 12); }
  level(s: ResearchStock): Levels | null { return s.levels[this.period]; }
  get narrow(): number { return this.filtered.filter(s => this.level(s)?.narrow).length; }
  get aligned(): number { return this.filtered.filter(s => this.level(s)?.position === s.sutradharPosition && ['ABOVE','BELOW'].includes(s.sutradharPosition)).length; }
  get index(): OptionUnderlying | undefined { return this.indices.find(i => i.key === this.indexKey); }
  tone(value: string | null | undefined): string { return /BULL|BUYING|ABOVE|HH/.test(value ?? '') ? 'up' : /BEAR|SELLING|BELOW|LH/.test(value ?? '') ? 'down' : 'muted'; }
  num(value: number | null | undefined, digits = 2): string { return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits }); }
  time(value: string | null | undefined): string { return value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' }) + ' IST' : 'No stored candle'; }
  ngOnChanges(): void { this.page = 0; if (this.view === 'research_trends' && !['weekly','monthly'].includes(this.frame)) this.frame = 'weekly'; }
  ngOnInit(): void {
    this.load();
    this.indicesRequest = this.api.optionUnderlyings().subscribe({ next: data => { this.indices = data.underlyings.filter(i => i.group === 'Indices'); this.indexKey = this.indices[0]?.key ?? ''; }, error: () => this.indexError = 'Index instruments could not be loaded. Connect Upstox and retry.' });
  }
  load(): void {
    this.request?.unsubscribe(); this.loading = true; this.error = '';
    this.request = this.http.get<ResearchSnapshot>('/api/research/dashboard').pipe(timeout(90000)).subscribe({ next: data => { this.snapshot = data; this.loading = false; if (!this.selectedKey) this.selectedKey = data.stocks.find(s => s.price !== null)?.key ?? ''; }, error: e => { this.loading = false; this.error = typeof e.error?.detail === 'string' ? e.error.detail : 'Research data could not load. Check the backend and stored candle sync, then retry.'; } });
  }
  open(s: ResearchStock, view = 'research_stock'): void { this.selectedKey = s.key; this.viewChange.emit(view); }
  chooseStock(symbol: string): void { this.query = symbol; this.page = 0; if (symbol) this.selectedKey = this.stocks.find(s => s.symbol === symbol)?.key ?? ''; }
  setView(value: string): void { this.page = 0; this.viewChange.emit(value); }
  chartLevels(s: ResearchStock): { label: string; value: number; color?: string }[] { const p = this.level(s); return p ? this.view === 'research_camarilla' ? [{label:'R4',value:p.r4,color:'#ed697e'},{label:'R3',value:p.r3,color:'#ed697e'},{label:'S3',value:p.s3,color:'#35c99a'},{label:'S4',value:p.s4,color:'#35c99a'}] : [{label:'TC',value:p.tc},{label:'P',value:p.pivot},{label:'BC',value:p.bc}] : []; }
  get pattern(): string { const b = this.selected?.charts[this.frame]; if (!b?.length) return 'No completed candles available.'; const last = b[b.length-1], prev = b[b.length-2]; const range = last.high-last.low, body = Math.abs(last.close-last.open); if (range <= 0) return 'Flat candle; no range.'; if (prev && last.close > last.open && prev.close < prev.open && last.open <= prev.close && last.close >= prev.open) return 'Bullish engulfing body on the last completed candle. Watch resistance and follow-through volume.'; if (prev && last.close < last.open && prev.close > prev.open && last.open >= prev.close && last.close <= prev.open) return 'Bearish engulfing body on the last completed candle. Watch support and follow-through volume.'; if (body <= range*.1) return 'Doji: small body relative to range. Indecision; direction needs follow-through.'; if (body > 0 && Math.min(last.open,last.close)-last.low >= body*2 && last.high-Math.max(last.open,last.close) <= range*.15) return 'Long lower wick / hammer-shaped candle. Reversal is unconfirmed without trend context and follow-through.'; if (body > 0 && last.high-Math.max(last.open,last.close) >= body*2 && Math.min(last.open,last.close)-last.low <= range*.15) return 'Long upper wick / shooting-star-shaped candle. Rejection needs follow-through confirmation.'; return 'No engulfing, doji or long-wick pattern detected on the last completed candle.'; }
  parse(): void { this.importError = ''; this.imported = []; const lines = this.importText.trim().split(/\r?\n/).filter(Boolean); if (!/^symbol,price,cpr,sutradhar$/i.test(lines[0]?.trim() ?? '')) { this.importError = 'Use CSV with the header: symbol,price,cpr,sutradhar. Imported observations stay separate from stored market data.'; return; } for (const line of lines.slice(1)) { const parts = line.split(',').map(x => x.trim()); if (parts.length !== 4 || !parts[0] || !Number.isFinite(Number(parts[1])) || Number(parts[1]) <= 0 || !parts.slice(2).every(p => ['ABOVE','BELOW','INSIDE','UNAVAILABLE'].includes(p.toUpperCase()))) { this.imported = []; this.importError = 'Each row needs a symbol, positive price, and ABOVE / BELOW / INSIDE / UNAVAILABLE for both positions.'; return; } this.imported.push({symbol:parts[0],price:parts[1],cpr:parts[2].toUpperCase(),sutradhar:parts[3].toUpperCase()}); } }
  exportCsv(): void { const rows = [['Symbol','Price','Daily change %','Aligned trend','Daily trend','Weekly trend','Monthly trend','Hourly pressure','Candle time'], ...this.filtered.map(s => [s.symbol,s.price,s.changePct,s.bias,s.regimes['daily'].bias,s.regimes['weekly'].bias,s.regimes['monthly'].bias,s.pressure['1h'].state,s.asOf])]; const csv = rows.map(row => row.map(v => '"' + String(v ?? '').replace(/"/g,'""') + '"').join(',')).join('\r\n'); const url = URL.createObjectURL(new Blob([csv], {type:'text/csv'})); const a = document.createElement('a'); a.href = url; a.download = 'market-research.csv'; a.click(); URL.revokeObjectURL(url); }
  get validLegs(): boolean { return this.legs.every(l => Number.isFinite(l.strike) && l.strike > 0 && Number.isFinite(l.premium) && l.premium >= 0 && Number.isInteger(l.quantity) && l.quantity > 0); }
  payoff(price: number): number { return this.legs.reduce((sum,l) => sum + (l.side === 'BUY' ? 1 : -1) * ((l.type === 'CE' ? Math.max(price-l.strike,0) : Math.max(l.strike-price,0))-l.premium)*l.quantity,0); }
  get payoffPoints(): string { if (!this.validLegs) return ''; const low = Math.min(...this.legs.map(l=>l.strike))*.9, high = Math.max(...this.legs.map(l=>l.strike))*1.1; const vals = Array.from({length:101},(_,i)=>this.payoff(low+(high-low)*i/100)); const max = Math.max(...vals.map(Math.abs),1); return vals.map((v,i)=>`${20+i*4.6},${100-v/max*80}`).join(' '); }
  ngOnDestroy(): void { this.request?.unsubscribe(); this.indicesRequest?.unsubscribe(); }
}
