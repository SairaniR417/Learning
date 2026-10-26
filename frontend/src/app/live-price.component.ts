import { CommonModule } from '@angular/common';
import { Component, HostListener, Input, OnChanges, OnDestroy, inject } from '@angular/core';
import { Subscription, timeout } from 'rxjs';
import { ChartQuote, MarketApiService } from './market-api.service';

@Component({
  selector: 'app-live-price', standalone: true, imports: [CommonModule],
  template: `<div class="live-price" [class.old]="failed">
    <strong>{{ (quote?.price ?? fallbackPrice) | number:'1.2-2' }}</strong>
    <span>{{ quote ? (failed ? 'Old quoted price' : 'Latest traded price') : 'Last candle price' }}</span>
    <small *ngIf="quote">Quote received {{ quote.receivedAt | date:'dd MMM, HH:mm:ss':'+0530' }} IST</small>
    <small *ngIf="!quote && fallbackAt">Candle {{ fallbackAt | date:'dd MMM, HH:mm':'+0530' }} IST</small>
    <small *ngIf="!failed">{{ loading ? 'Updating price...' : 'Price refreshes every 15 seconds' }}</small>
    <span *ngIf="failed" class="old-message" role="alert"><b>Old data</b> - latest price unavailable. <button type="button" (click)="load()" [disabled]="loading">Retry price</button></span>
  </div>`,
  styles: [`.live-price{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 12px;padding:10px 0;color:#b8c9c4}.live-price>strong{font-size:22px;color:#e8f3ed}.live-price small{font-size:11px}.live-price.old{color:#ffe2a4}.old-message{padding:6px 10px;background:#352810;border:1px solid #b68126;border-radius:4px}.old-message button{background:transparent;color:inherit;border:1px solid #b68126;border-radius:4px;padding:4px 8px}`]
})
export class LivePriceComponent implements OnChanges, OnDestroy {
  @Input() instrumentKey = '';
  @Input() expiry = '';
  @Input() strike = 0;
  @Input() side: 'CE' | 'PE' = 'CE';
  @Input() fallbackPrice?: number;
  @Input() fallbackAt?: string | null;
  private api = inject(MarketApiService);
  private request?: Subscription;
  private timer?: ReturnType<typeof setInterval>;
  private selection = '';
  quote?: ChartQuote;
  loading = false;
  failed = false;
  ngOnChanges(): void {
    const selection = JSON.stringify([this.instrumentKey,this.expiry,this.strike,this.side]);
    if (selection === this.selection) return;
    this.selection = selection;
    this.request?.unsubscribe(); clearInterval(this.timer);
    this.quote = undefined; this.failed = false; this.loading = false;
    this.load();
    this.timer = setInterval(() => { if (!document.hidden && !this.loading) this.load(); },15000);
  }
  load(): void {
    if (!this.instrumentKey || document.hidden || this.loading) return;
    this.request?.unsubscribe(); this.loading = true;
    this.request = this.api.chartQuote(this.instrumentKey,this.expiry,this.strike,this.side).pipe(timeout(18000)).subscribe({
      next: quote => { this.quote = quote; this.loading = false; this.failed = false; },
      error: () => { this.loading = false; this.failed = true; }
    });
  }
  @HostListener('document:visibilitychange') visibilityChanged(): void {
    if (document.hidden) { this.request?.unsubscribe(); this.loading = false; }
    else this.load();
  }
  ngOnDestroy(): void { this.request?.unsubscribe(); clearInterval(this.timer); }
}
