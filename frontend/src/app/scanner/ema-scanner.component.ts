import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { EmaScannerResponse, Instrument, MarketApiService } from '../market-api.service';

type ScannerTimeframe = { label: string; unit: string; interval: number };

function localDateInput(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

@Component({
  selector: 'app-ema-scanner',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './ema-scanner.component.html',
  styleUrl: './ema-scanner.component.css'
})
export class EmaScannerComponent implements OnInit, OnDestroy {
  private readonly api = inject(MarketApiService);
  private scanSubscription?: Subscription;
  private universeSubscription?: Subscription;
  readonly timeframes: ScannerTimeframe[] = [
    { label: 'Daily', unit: 'days', interval: 1 },
    { label: 'Weekly', unit: 'weeks', interval: 1 },
    { label: 'Monthly', unit: 'months', interval: 1 },
    { label: '1 hour', unit: 'hours', interval: 1 },
    { label: '15 minutes', unit: 'minutes', interval: 15 }
  ];
  timeframe = 'days:1';
  to = localDateInput(new Date());
  from = this.defaultStartDate();
  loading = false;
  error = '';
  response?: EmaScannerResponse;
  hasScanned = false;
  stocks: Instrument[] = [];
  stockSearch = '';
  universeLoading = false;
  universeError = '';
  stockPage = 0;
  readonly stocksPerPage = 100;

  ngOnInit(): void {
    this.loadStocks();
  }

  ngOnDestroy(): void {
    this.scanSubscription?.unsubscribe();
    this.universeSubscription?.unsubscribe();
  }

  private defaultStartDate(): string {
    const start = new Date();
    start.setDate(start.getDate() - 730);
    return localDateInput(start);
  }

  get selectedTimeframe(): ScannerTimeframe {
    return this.timeframes.find((item) => `${item.unit}:${item.interval}` === this.timeframe) ?? this.timeframes[0];
  }

  get filteredStocks(): Instrument[] {
    const query = this.stockSearch.trim().toLowerCase();
    if (!query) return this.stocks;
    return this.stocks.filter((stock) => `${stock.symbol} ${stock.name}`.toLowerCase().includes(query));
  }

  get visibleStocks(): Instrument[] {
    const start = this.stockPage * this.stocksPerPage;
    return this.filteredStocks.slice(start, start + this.stocksPerPage);
  }

  get stockPageCount(): number {
    return Math.ceil(this.filteredStocks.length / this.stocksPerPage);
  }

  get stockPageEnd(): number {
    return Math.min((this.stockPage + 1) * this.stocksPerPage, this.filteredStocks.length);
  }

  loadStocks(): void {
    this.universeLoading = true;
    this.universeError = '';
    this.universeSubscription = this.api.nseEquityUniverse().subscribe({
      next: ({ stocks }) => { this.stocks = stocks; this.universeLoading = false; },
      error: (error: HttpErrorResponse) => {
        this.universeError = typeof error.error?.detail === 'string' ? error.error.detail : 'Could not load the NSE stock list.';
        this.universeLoading = false;
      }
    });
  }

  searchStocks(value: string): void {
    this.stockSearch = value;
    this.stockPage = 0;
  }

  changeStockPage(offset: number): void {
    this.stockPage = Math.max(0, Math.min(this.stockPage + offset, this.stockPageCount - 1));
  }

  setTimeframe(value: string): void {
    this.timeframe = value;
    const period = this.selectedTimeframe;
    const days = period.unit === 'minutes' ? 30
      : period.unit === 'hours' ? 90
        : period.unit === 'weeks' ? 1825
          : period.unit === 'months' ? 7300
            : 730;
    const start = new Date();
    start.setDate(start.getDate() - days);
    this.from = localDateInput(start);
  }

  scan(): void {
    if (this.loading) return;
    if (!this.from || !this.to || this.from > this.to) {
      this.error = 'Choose a valid date range. The start date must be on or before the end date.';
      return;
    }
    this.loading = true;
    this.error = '';
    this.response = undefined;
    this.hasScanned = true;
    const period = this.selectedTimeframe;
    this.scanSubscription = this.api.scanEmaUniverse(period.unit, period.interval, this.from, this.to).subscribe({
      next: (response) => { this.response = response; this.loading = false; },
      error: (error: HttpErrorResponse) => {
        this.error = typeof error.error?.detail === 'string'
          ? error.error.detail
          : error.message || 'The market scan could not be completed.';
        this.loading = false;
      }
    });
  }

  formatPrice(value: number | null): string {
    if (value === null || value === undefined) return '—';
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value);
  }
}
