import { CommonModule } from '@angular/common';
import { Component, ElementRef, EventEmitter, OnDestroy, OnInit, Output, ViewChild, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Subscription, exhaustMap, switchMap, takeWhile, timeout, timer } from 'rxjs';
import { FocusedResponse, FocusedStock, MarketApiService, SelectedStock } from '../market-api.service';

@Component({ selector: 'app-focused', standalone: true, imports: [CommonModule], templateUrl: './focused.component.html', styleUrl: './focused.component.css' })
export class FocusedComponent implements OnInit, OnDestroy {
  private readonly api = inject(MarketApiService);
  private request?: Subscription;
  @Output() stockSelected = new EventEmitter<SelectedStock>();
  data: FocusedResponse | null = null;
  loading = false;
  error = '';
  stage = '';
  limit = 5;
  sortBy: 'size' | 'liquidity' | 'signal' | 'price' = 'size';
  minPrice = 0;
  minCap = 0;
  pages: Record<'bullish' | 'bearish', number> = { bullish: 0, bearish: 0 };
  resetPages(): void { this.pages = { bullish: 0, bearish: 0 }; }
  changeSort(value: string): void { this.sortBy = value as typeof this.sortBy; this.resetPages(); }
  changeMinPrice(value: string): void { this.minPrice = Math.max(0, Number(value) || 0); this.resetPages(); }
  changeMinCap(value: string): void { this.minCap = Math.max(0, Number(value) || 0); this.resetPages(); }
  ranked(side: 'bullish' | 'bearish'): FocusedStock[] {
    const stocks = (this.data?.[side] ?? []).filter(s => s.close >= this.minPrice && (!this.minCap || (s.marketCap ?? 0) >= this.minCap * 10000000));
    return [...stocks].sort((a, b) => {
      if (this.sortBy === 'size') return (b.marketCap ?? -1) - (a.marketCap ?? -1) || b.averageTurnover - a.averageTurnover || b.score - a.score || a.symbol.localeCompare(b.symbol);
      if (this.sortBy === 'liquidity') return b.averageTurnover - a.averageTurnover || b.score - a.score || a.symbol.localeCompare(b.symbol);
      if (this.sortBy === 'price') return b.close - a.close || b.score - a.score || a.symbol.localeCompare(b.symbol);
      return Number(b.tier.startsWith('SUPER')) - Number(a.tier.startsWith('SUPER')) || b.score - a.score || b.strongStrategyCount - a.strongStrategyCount || b.averageTurnover - a.averageTurnover || a.symbol.localeCompare(b.symbol);
    });
  }
  visible(side: 'bullish' | 'bearish'): FocusedStock[] { return this.ranked(side).slice(this.pages[side] * this.limit, (this.pages[side] + 1) * this.limit); }
  pageCount(side: 'bullish' | 'bearish'): number { return Math.max(1, Math.ceil(this.ranked(side).length / this.limit)); }
  pageRange(side: 'bullish' | 'bearish'): string {
    const total = this.ranked(side).length;
    return total ? `${this.pages[side] * this.limit + 1}-${Math.min((this.pages[side] + 1) * this.limit, total)} of ${total}` : '0 of 0';
  }
  movePage(side: 'bullish' | 'bearish', delta: number): void { this.pages[side] = Math.max(0, Math.min(this.pageCount(side) - 1, this.pages[side] + delta)); }
  selected: FocusedStock | null = null;
  @ViewChild('detailDialog') detailDialog?: ElementRef<HTMLDialogElement>;
  showReasons(stock: FocusedStock): void { this.selected = stock; this.detailDialog?.nativeElement.showModal(); }
  closeReasons(): void { this.detailDialog?.nativeElement.close(); this.selected = null; }
  readonly sides = [{ key: 'bullish' as const, label: 'Bullish focus', description: 'Strength with agreement across strategies' }, { key: 'bearish' as const, label: 'Bearish focus', description: 'Weakness with agreement across strategies' }];
  ngOnInit(): void { this.refresh(); }
  ngOnDestroy(): void { this.request?.unsubscribe(); }
  refresh(): void {
    if (this.loading) return;
    this.loading = true; this.error = '';
    this.stage = 'Checking latest scan';
    this.request = this.api.startFocused().pipe(
      timeout(15000),
      switchMap(job => timer(0, 1000).pipe(exhaustMap(() => this.api.focusedJob(job.id).pipe(timeout(15000))))),
      takeWhile(job => job.status === 'running', true)
    ).subscribe({
      next: job => {
        this.stage = job.stage;
        if (job.status === 'complete' && job.result) { this.data = job.result; this.resetPages(); this.loading = false; }
        if (job.status === 'failed') { this.error = job.error; this.loading = false; }
      },
      error: (error: HttpErrorResponse) => {
        this.loading = false;
        this.error = typeof error.error?.detail === 'string' ? error.error.detail : 'Could not finish the combined scan. Check the backend and retry.';
      }
    });
  }
  changeLimit(value: string): void { this.limit = Number(value); this.resetPages(); }
  open(stock: FocusedStock): void {
    this.stockSelected.emit({ key: stock.instrumentKey, symbol: stock.symbol, name: stock.name, exchange: stock.exchange,
      strategy: 'Focused', timeframe: '1d', status: stock.tier, price: stock.close,
      detail: stock.reasons.map(r => r.reason).join('; '), metrics: [
        { label: 'Reference entry', value: stock.plan.entry, compareToClose: false },
        { label: 'SL', value: stock.plan.stopLoss, compareToClose: false },
        { label: 'Target 1', value: stock.plan.target1, compareToClose: false },
        { label: 'Target 2', value: stock.plan.target2, compareToClose: false }
      ] });
  }
}
