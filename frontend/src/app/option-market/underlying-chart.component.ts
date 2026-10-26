import { CommonModule } from '@angular/common';
import { Component, ElementRef, Input, OnChanges, OnDestroy, ViewChild, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subscription, timeout } from 'rxjs';
import { CandlestickSeries, ColorType, createChart, IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { HistoricalCandle } from '../market-api.service';

@Component({
  selector: 'app-underlying-chart', standalone: true, imports: [CommonModule],
  template: `<section aria-label="Underlying price chart">
    <header><strong>{{ label }}</strong><label>Timeframe <select [value]="interval" (change)="changeInterval(+$any($event.target).value)"><option value="5">5m</option><option value="15">15m</option><option value="60">1h</option><option value="1440">1D</option></select></label><button type="button" (click)="load()" [disabled]="loading">Refresh</button></header>
    <p *ngIf="loading" role="status">Loading chart...</p>
    <p *ngIf="error" role="alert">{{ error }} <button type="button" (click)="load()">Retry</button></p>
    <p *ngIf="!loading && !error && !rows.length">No candles available for this contract and timeframe.</p>
    <p *ngIf="invalid">Invalid provider candles were excluded.</p>
    <div *ngIf="staleData && rows.length" class="stale-data-alert" role="alert"><strong>Old data</strong><span>Current prices could not be refreshed. Showing last available data.</span><span *ngIf="lastDataAt">Last candle: {{ lastDataAt | date:'dd MMM yyyy, HH:mm':'+0530' }} IST.</span><button type="button" (click)="load()" [disabled]="loading">{{ loading ? 'Refreshing...' : 'Retry refresh' }}</button></div>
    <div #host class="chart"></div><small>Upstox underlying prices - Updates every minute while visible</small>
  </section>`,
  styles: [`:host{display:block}header{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:12px 0}label{margin-left:auto}select,button{background:#172220;color:#d4e2dc;border:1px solid #35454c;border-radius:4px;padding:6px 10px}.chart{height:540px;max-height:70vh}p,small{color:#9fb4aa}`]
})
export class UnderlyingChartComponent implements OnChanges, OnDestroy {
  @Input() instrumentKey = '';
  @Input() label = '';
  private http = inject(HttpClient);
  private chart?: IChartApi;
  private series?: ISeriesApi<'Candlestick'>;
  private request?: Subscription;
  private timer = setInterval(() => { if (!document.hidden && !this.loading) this.load(); }, 60000);
  interval = 5; loading = false; error = ''; invalid = false; staleData = false;
  get lastDataAt(): string | null { return this.rows.at(-1)?.timestamp || null; }
  rows: HistoricalCandle[] = [];
  @ViewChild('host') set host(ref: ElementRef<HTMLElement> | undefined) {
    this.chart?.remove(); this.chart = undefined; this.series = undefined;
    if (!ref) return;
    this.chart = createChart(ref.nativeElement, {autoSize:true, layout:{background:{type:ColorType.Solid,color:'#101318'},textColor:'#aab8b1'},timeScale:{timeVisible:this.interval !== 1440}});
    this.series = this.chart.addSeries(CandlestickSeries, {upColor:'#49cba1',downColor:'#ed7882',wickUpColor:'#49cba1',wickDownColor:'#ed7882',borderVisible:false});
    this.draw();
  }
  ngOnChanges(): void { this.rows = []; this.draw(); this.load(); }
  changeInterval(interval: number): void { this.interval = interval; this.rows = []; this.draw(); this.load(); }
  load(): void {
    this.request?.unsubscribe();
    if (!this.instrumentKey) return;
    this.loading = true; this.error = ''; this.invalid = false;
    this.request = this.http.get<{candles:HistoricalCandle[];invalidCandles:number}>('/api/market/chart', {params:{instrument_key:this.instrumentKey,interval:this.interval}}).pipe(timeout(45000)).subscribe({
      next: data => { this.staleData = false; this.rows = data.candles; this.invalid = data.invalidCandles > 0; this.loading = false; this.draw(); },
      error: error => { this.staleData = true; this.loading = false; this.error = error.error?.detail || 'Chart unavailable. Connect Upstox and retry.'; }
    });
  }
  private draw(): void {
    this.chart?.applyOptions({timeScale:{timeVisible:this.interval !== 1440}});
    const unique = new Map<number, HistoricalCandle>();
    for (const row of this.rows) unique.set(new Date(row.timestamp).getTime(), row);
    this.series?.setData([...unique].sort((a,b)=>a[0]-b[0]).map(([stamp,row])=>({time:(this.interval === 1440 ? new Date(stamp + 19800000).toISOString().slice(0,10) : Math.floor(stamp/1000)) as Time,open:row.open,high:row.high,low:row.low,close:row.close})));
    this.chart?.timeScale().fitContent();
  }
  ngOnDestroy(): void { clearInterval(this.timer); this.request?.unsubscribe(); this.chart?.remove(); }
}
