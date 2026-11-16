import { CommonModule } from '@angular/common';
import { Component, HostListener, Input, OnChanges, OnDestroy, inject } from '@angular/core';
import { Subscription, timeout } from 'rxjs';
import { MarketApiService, OptionChain } from '../market-api.service';
import { backendUrl } from '../backend-url';
import { BappuLegComponent } from './bappu-leg.component';

@Component({
  selector: 'app-bappu-theory', standalone: true, imports: [CommonModule, BappuLegComponent],
  templateUrl: './bappu-theory.component.html', styleUrl: './bappu-theory.component.css'
})
export class BappuTheoryComponent implements OnChanges, OnDestroy {
  @Input() underlyingKey = '';
  @Input() underlyingLabel = '';
  @Input() backToChart?: () => void;
  private api = inject(MarketApiService);
  private expiryRequest?: Subscription;
  private chainRequest?: Subscription;
  readonly loginUrl = backendUrl('/auth/upstox');
  expiries: string[] = [];
  expiry = '';
  chain?: OptionChain;
  ceStrike = 0;
  peStrike = 0;
  timeframe = 5;
  loading = false;
  error = '';
  needsConnection = false;
  get strikes(): number[] { return this.chain?.rows.map(row => row.strike) ?? []; }
  ngOnChanges(): void {
    this.cancel(); this.expiries = []; this.expiry = ''; this.chain = undefined;
    this.ceStrike = this.peStrike = 0; this.error = '';
    if (!document.hidden) this.loadExpiries();
  }
  loadExpiries(): void {
    if (!this.underlyingKey || this.loading) return;
    this.loading = true; this.error = ''; this.needsConnection = false;
    this.expiryRequest = this.api.optionExpiries(this.underlyingKey).pipe(timeout(20000)).subscribe({
      next: result => {
        this.expiries = result.expiries; this.loading = false;
        this.selectExpiry(this.expiries.includes(this.expiry) ? this.expiry : this.expiries[0] ?? '');
      },
      error: error => this.fail(error)
    });
  }
  selectExpiry(expiry: string): void {
    this.chainRequest?.unsubscribe(); this.expiry = expiry; this.chain = undefined;
    this.ceStrike = this.peStrike = 0; this.error = ''; this.loading = false;
    if (!expiry) return;
    this.loading = true;
    this.chainRequest = this.api.optionChain(this.underlyingKey, expiry).pipe(timeout(20000)).subscribe({
      next: chain => {
        this.chain = chain;
        const atm = chain.atmStrike;
        this.ceStrike = this.peStrike = atm != null && this.strikes.includes(atm) ? atm : 0;
        this.loading = false;
      },
      error: error => this.fail(error)
    });
  }
  selectStrike(side: 'CE' | 'PE', value: string): void {
    const strike = Number(value);
    const selected = this.strikes.includes(strike) ? strike : 0;
    if (side === 'CE') this.ceStrike = selected; else this.peStrike = selected;
  }
  private fail(error: { status?: number; error?: { detail?: string } }): void {
    this.loading = false; this.needsConnection = error.status === 401;
    this.error = error.error?.detail || 'Could not load contracts. Retry.';
  }
  @HostListener('document:visibilitychange') visibilityChanged(): void {
    if (document.hidden) this.cancel(); else if (!this.chain) this.loadExpiries();
  }
  private cancel(): void { this.expiryRequest?.unsubscribe(); this.chainRequest?.unsubscribe(); this.loading = false; }
  ngOnDestroy(): void { this.cancel(); }
}
