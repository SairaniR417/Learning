import { CommonModule } from '@angular/common';
import { Component, Input, OnChanges, OnDestroy, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { MarketApiService, OptionChain, OptionLeg } from '../market-api.service';

@Component({
  selector: 'app-option-chain', standalone: true, imports: [CommonModule],
  templateUrl: './option-chain.component.html', styleUrl: './option-chain.component.css'
})
export class OptionChainComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) stockKey = '';
  private readonly api = inject(MarketApiService);
  private expiryRequest?: Subscription;
  private chainRequest?: Subscription;
  expiries: string[] = [];
  expiry = '';
  loading = false;
  loadingExpiries = false;
  error = '';
  needsConnection = false;
  data?: OptionChain;
  showGreeks = false;
  readonly marketColumns: { key: keyof OptionLeg; label: string }[] = [
    {key: 'oi', label: 'OI'}, {key: 'volume', label: 'Volume'},
    {key: 'iv', label: 'IV'}, {key: 'bid_price', label: 'Bid ₹'},
    {key: 'ask_price', label: 'Ask ₹'}, {key: 'ltp', label: 'LTP ₹'}
  ];
  readonly greekColumns: { key: keyof OptionLeg; label: string }[] = [
    {key: 'delta', label: 'Delta'}, {key: 'gamma', label: 'Gamma'},
    {key: 'theta', label: 'Theta'}, {key: 'vega', label: 'Vega'}
  ];
  get columns() { return this.showGreeks ? [...this.greekColumns, ...this.marketColumns] : this.marketColumns; }
  ngOnChanges(): void { this.expiry = ''; this.expiries = []; this.refresh(); }
  ngOnDestroy(): void { this.expiryRequest?.unsubscribe(); this.chainRequest?.unsubscribe(); }
  refresh(): void {
    this.expiryRequest?.unsubscribe(); this.chainRequest?.unsubscribe();
    this.data = undefined; this.error = ''; this.needsConnection = false;
    this.loading = false; this.loadingExpiries = true;
    this.expiryRequest = this.api.optionExpiries(this.stockKey).subscribe({
      next: result => {
        this.expiries = result.expiries;
        this.expiry = this.expiries.includes(this.expiry) ? this.expiry : this.expiries[0] ?? '';
        this.loadingExpiries = false;
        if (this.expiry) this.selectExpiry(this.expiry);
      },
      error: error => this.fail(error)
    });
  }
  selectExpiry(expiry: string): void {
    this.chainRequest?.unsubscribe();
    this.expiry = expiry; this.data = undefined; this.error = ''; this.needsConnection = false;
    if (!expiry) return;
    this.loading = true;
    this.chainRequest = this.api.optionChain(this.stockKey, expiry).subscribe({
      next: data => { this.data = data; this.loading = false; },
      error: error => this.fail(error)
    });
  }
  private fail(error: { status?: number; error?: { detail?: unknown } }): void {
    this.loading = this.loadingExpiries = false;
    this.needsConnection = error.status === 401;
    this.error = typeof error.error?.detail === 'string' ? error.error.detail : 'Could not load the option chain. Please retry.';
  }
  format(value: number | null, key: string): string {
    if (value == null) return '—';
    return value.toLocaleString('en-IN', {
      maximumFractionDigits: key === 'gamma' ? 4 : ['oi', 'volume'].includes(key) ? 0 : 2
    });
  }
}
