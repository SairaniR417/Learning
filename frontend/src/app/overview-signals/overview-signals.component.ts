import { StockChoicesComponent } from '../shared/stock-choices.component';
import { CommonModule } from '@angular/common';
import { Component, EventEmitter, OnDestroy, OnInit, Output, inject } from '@angular/core';
import { Subscription, timer, switchMap, takeWhile } from 'rxjs';
import { IndicatorPosition, MarketApiService, OverviewSignals, OverviewSignalStock, SelectedStock } from '../market-api.service';

@Component({
  selector: 'app-overview-signals', standalone: true, imports: [StockChoicesComponent, CommonModule],
  templateUrl: './overview-signals.component.html', styleUrl: './overview-signals.component.css'
})
export class OverviewSignalsComponent implements OnInit, OnDestroy {
  @Output() stockSelected = new EventEmitter<SelectedStock>();
  private readonly api = inject(MarketApiService);
  private request?: Subscription;
  private historyRequest?: Subscription;
  private historyPoll?: Subscription;
  readonly frames = ['1m', '5m', '15m', '30m', '1h', '1d', '1w'];
  timeframe = '1h';
  data: OverviewSignals | null = null;
  loading = false;
  error = '';
  search = '';
  vwapFilter = '';
  sma20Filter = '';
  sma50Filter = '';
  crossFilter = '';
  syncing = false;
  syncMessage = '';
  syncError = '';
  ngOnInit(): void { this.refresh(); }
  ngOnDestroy(): void { this.request?.unsubscribe(); this.historyRequest?.unsubscribe(); this.historyPoll?.unsubscribe(); }
  selectFrame(frame: string): void {
    this.historyRequest?.unsubscribe(); this.historyPoll?.unsubscribe();
    this.syncing = false; this.syncMessage = ''; this.syncError = '';
    this.timeframe = frame; this.refresh();
  }
  get needsHistory(): number { return this.data?.stocks.filter(s => s.bars < 51).length ?? 0; }
  loadHistory(): void {
    if (this.syncing) return;
    this.syncing = true; this.syncError = '';
    this.syncMessage = `Loading missing ${this.timeframe} history from Upstox. This can take several minutes; the server continues if you leave this tab.`;
    this.historyRequest = this.api.loadOverviewHistory(this.timeframe).subscribe({
      next: result => {
        if (result.job_id === null) { this.syncing = false; this.syncMessage = 'History is already sufficient.'; this.refresh(); return; }
        this.historyPoll = timer(0, 3000).pipe(
          switchMap(() => this.api.overviewHistoryJob(result.job_id!)),
          takeWhile(job => job.status === 'pending' || job.status === 'running', true)
        ).subscribe({
          next: job => {
            if (job.status === 'pending' || job.status === 'running') return;
            this.syncing = false;
            this.syncMessage = job.status === 'complete' ? 'History loaded. Signals refreshed.' : '';
            this.syncError = job.status === 'complete' ? '' : job.status === 'partial' ? 'Some history requests failed. Available signals have refreshed; retry to load the remaining stocks.' : 'History could not be loaded. Check the Upstox connection and retry.';
            this.refresh();
          },
          error: () => { this.syncing = false; this.syncMessage = ''; this.syncError = 'Could not check history progress. Click Load missing history to reconnect to the running job.'; }
        });
      },
      error: error => {
        this.syncing = false; this.syncMessage = '';
        this.syncError = typeof error.error?.detail === 'string' ? error.error.detail : 'Could not start history loading. Connect Upstox and retry.';
      }
    });
  }
  refresh(): void {
    this.request?.unsubscribe();
    this.data = null; this.error = ''; this.loading = true;
    this.request = this.api.overviewSignals(this.timeframe).subscribe({
      next: data => { this.data = data; this.loading = false; },
      error: error => {
        this.loading = false;
        this.error = typeof error.error?.detail === 'string' ? error.error.detail : 'Unable to load stored stock signals. Please retry.';
      }
    });
  }
  reset(): void { this.search = this.vwapFilter = this.sma20Filter = this.sma50Filter = this.crossFilter = ''; }
  get stocks(): OverviewSignalStock[] {
    const query = this.search.trim().toLowerCase();
    return (this.data?.stocks ?? []).filter(s =>
      (!query || s.symbol.toLowerCase().includes(query) || s.name.toLowerCase().includes(query)) &&
      (!this.vwapFilter || s.vwapPosition === this.vwapFilter) &&
      (!this.sma20Filter || s.sma20Position === this.sma20Filter) &&
      (!this.sma50Filter || s.sma50Position === this.sma50Filter) &&
      (!this.crossFilter || (this.crossFilter === 'above' || this.crossFilter === 'below' ? s.maTrend === this.crossFilter : s.crossover === this.crossFilter))
    );
  }
  get available(): number { return this.data?.stocks.filter(s => s.price !== null).length ?? 0; }
  label(value: IndicatorPosition): string { return value === 'above' ? 'Above' : value === 'below' ? 'Below' : value === 'at' ? 'At' : 'Unavailable'; }
  signalHint(stock: OverviewSignalStock, kind: 'vwap' | 'sma20' | 'sma50' | 'trend' | 'cross'): string {
    const number = (value: number | null) => value == null ? 'unavailable' : value.toFixed(2);
    const values = `Close ${number(stock.price)}; SMA 20 ${number(stock.sma20)}; SMA 50 ${number(stock.sma50)}. ${this.timeframe} timeframe; periods count candles.`;
    const context = `${values}${stock.asOf ? ` Data as of ${new Date(stock.asOf).toLocaleString('en-IN', {timeZone:'Asia/Kolkata'})} IST.` : ''}${stock.historyNote ? '\n' + stock.historyNote : ''}`;
    if (kind === 'cross') return `${stock.crossover === 'bullish' ? 'SMA 20 crossed above SMA 50 on the latest completed candle.' : stock.crossover === 'bearish' ? 'SMA 20 crossed below SMA 50 on the latest completed candle.' : stock.bars >= 51 ? 'No SMA 20 / 50 cross on the latest completed candle.' : 'Insufficient history to compare the latest and previous SMA values.'}\n${context}`;
    if (kind === 'trend') return `SMA 20 is ${stock.maTrend ? this.label(stock.maTrend).toLowerCase() : 'unavailable relative to'} SMA 50. This is their current position; it does not establish a fresh crossover.\n${context}`;
    const label = kind === 'vwap' ? this.data?.vwapLabel ?? 'VWAP' : kind === 'sma20' ? 'SMA 20' : 'SMA 50';
    const value = stock[kind], position = kind === 'vwap' ? stock.vwapPosition : kind === 'sma20' ? stock.sma20Position : stock.sma50Position;
    return `Close ${number(stock.price)}; ${label} ${number(value)}. Price position: ${this.label(position).toLowerCase()}. A price position alone does not establish a new cross.\n${context}`;
  }
  open(stock: OverviewSignalStock): void {
    this.stockSelected.emit({ key: stock.key, symbol: stock.symbol, name: stock.name, exchange: stock.exchange, timeframe: this.timeframe });
  }
}
