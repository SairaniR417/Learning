import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild, inject } from '@angular/core';
import { EMPTY, Subscription, catchError, exhaustMap, tap, timer } from 'rxjs';
import { HistoricalCandle, Instrument, LtpQuote, MarketApiService } from './market-api.service';

const DEFAULT_WATCHLIST: Instrument[] = [
  { key: 'NSE_INDEX|Nifty 50', symbol: 'NIFTY 50', name: 'Nifty 50', exchange: 'NSE_INDEX' },
  { key: 'NSE_INDEX|Nifty Bank', symbol: 'BANKNIFTY', name: 'Nifty Bank', exchange: 'NSE_INDEX' },
  { key: 'NSE_INDEX|India VIX', symbol: 'INDIA VIX', name: 'India VIX', exchange: 'NSE_INDEX' },
  { key: 'NSE_EQ|INE002A01018', symbol: 'RELIANCE', name: 'Reliance Industries', exchange: 'NSE_EQ' },
  { key: 'NSE_EQ|INE009A01021', symbol: 'INFY', name: 'Infosys Limited', exchange: 'NSE_EQ' },
  { key: 'NSE_EQ|INE040A01034', symbol: 'HDFCBANK', name: 'HDFC Bank Limited', exchange: 'NSE_EQ' }
];
const WATCHLIST_KEY = 'market-desk-watchlist';

function dateInputValue(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent implements OnInit, AfterViewInit, OnDestroy {
  private readonly api = inject(MarketApiService);
  private refreshSubscription?: Subscription;
  private toastTimer?: ReturnType<typeof setTimeout>;
  private searchTimer?: ReturnType<typeof setTimeout>;
  private historySearchTimer?: ReturnType<typeof setTimeout>;
  private clockTimer?: ReturnType<typeof setInterval>;
  private resizeObserver?: ResizeObserver;
  private chartReady = false;

  @ViewChild('chart') private chart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('historyChart') private historyChart?: ElementRef<HTMLCanvasElement>;

  watchlist = this.loadWatchlist();
  quotes: Record<string, LtpQuote> = {};
  searchResults: Instrument[] = [];
  history: number[] = [];
  connected = false;
  configured = true;
  searchText = '';
  searchMessage = '';
  searchOpen = false;
  toast = '';
  updatedTime = 'LIVE FEED OFF';
  clock = '';
  marketLabel = 'Awaiting connection';
  historySearchText = '';
  historySearchResults: Instrument[] = [];
  historySearchMessage = '';
  historySearchOpen = false;
  selectedHistoryInstrument?: Instrument;
  historicalFrom = dateInputValue(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000));
  historicalTo = dateInputValue(new Date());
  historicalInterval = 'days:1';
  historicalCandles: HistoricalCandle[] = [];
  displayedCandles: HistoricalCandle[] = [];
  historicalLoading = false;
  demoMode = false;

  ngOnInit(): void {
    this.updateClock();
    this.clockTimer = window.setInterval(() => this.updateClock(), 1000);
    this.api.status().subscribe({
      next: (status) => {
        this.configured = status.configured;
        this.setConnected(status.connected);
      },
      error: () => this.showToast('Could not reach the Market Desk API.')
    });
    const params = new URLSearchParams(window.location.search);
    if (params.get('auth') === 'connected') this.showToast('Upstox connected. Live quotes are loading.');
    if (params.get('auth') === 'failed') this.showToast('Upstox authorization failed. Check app credentials and redirect URI.');
    if (params.get('setup') === '1') this.showToast('Add your Upstox API key and secret in the server .env file first.');
    if (params.has('auth') || params.has('setup')) window.history.replaceState({}, '', '/');
  }

  ngAfterViewInit(): void {
    this.chartReady = true;
    if (this.chart) {
      this.resizeObserver = new ResizeObserver(() => {
        this.drawChart();
        this.drawHistoryChart();
      });
      if (this.chart) this.resizeObserver.observe(this.chart.nativeElement);
      if (this.historyChart) this.resizeObserver.observe(this.historyChart.nativeElement);
    }
    this.drawChart();
  }

  ngOnDestroy(): void {
    this.refreshSubscription?.unsubscribe();
    this.resizeObserver?.disconnect();
    if (this.clockTimer) clearInterval(this.clockTimer);
    if (this.toastTimer) clearTimeout(this.toastTimer);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    if (this.historySearchTimer) clearTimeout(this.historySearchTimer);
  }

  get nifty(): LtpQuote | undefined { return this.quotes['NSE_INDEX|Nifty 50']; }
  get bankNifty(): LtpQuote | undefined { return this.quotes['NSE_INDEX|Nifty Bank']; }
  get indiaVix(): LtpQuote | undefined { return this.quotes['NSE_INDEX|India VIX']; }
  get niftyChange(): number | undefined { return this.changePercent(this.nifty); }
  get niftyDifference(): number | undefined {
    return this.nifty?.cp === undefined ? undefined : this.nifty.last_price - this.nifty.cp;
  }

  quoteFor(key: string): LtpQuote | undefined { return this.quotes[key]; }

  changePercent(quote?: LtpQuote): number | undefined {
    if (!quote?.cp) return undefined;
    return ((quote.last_price - quote.cp) / quote.cp) * 100;
  }

  formatPrice(value?: number): string {
    return value === undefined ? '--' : value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  formatChange(value?: number): string {
    if (value === undefined) return 'Waiting for data';
    return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
  }

  initials(symbol: string): string { return symbol.replace(/[^a-z0-9]/gi, '').slice(0, 2).toUpperCase() || 'IN'; }

  setConnected(connected: boolean): void {
    this.connected = connected;
    this.marketLabel = connected ? 'Live data connected' : 'Awaiting connection';
    this.refreshSubscription?.unsubscribe();
    if (connected) {
      this.updatedTime = 'LIVE QUOTES';
      this.refreshSubscription = timer(0, 5000).pipe(
        exhaustMap(() => this.refreshQuotes())
      ).subscribe();
    } else {
      this.updatedTime = 'LIVE FEED OFF';
    }
  }

  refreshQuotes() {
    if (!this.connected || !this.watchlist.length) return EMPTY;
    const keys = this.watchlist.map((instrument) => instrument.key);
    return this.api.quotes(keys).pipe(
      tap((response) => {
        for (const [responseKey, quote] of Object.entries(response.data)) {
          const key = (quote.instrument_token || responseKey.replace(':', '|')).replace(':', '|');
          if (!this.watchlist.some((item) => item.key === key)) continue;
          this.quotes[key] = quote;
          this.updateHistory(key, quote);
        }
        this.updatedTime = `UPDATED ${this.istTime()} IST`;
        this.drawChart();
      }),
      catchError((error: HttpErrorResponse) => {
        if (error.status === 401) {
          this.setConnected(false);
          this.showToast('Your Upstox session has expired. Please reconnect.');
        } else {
          this.showToast(error.error?.detail || 'Could not refresh market quotes.');
        }
        return EMPTY;
      })
    );
  }

  updateSearch(value: string): void {
    this.searchText = value;
    if (this.searchTimer) clearTimeout(this.searchTimer);
    if (value.trim().length < 2) {
      this.searchOpen = false;
      return;
    }
    this.searchTimer = setTimeout(() => this.search(value.trim()), 280);
  }

  search(query: string): void {
    this.searchOpen = true;
    this.searchMessage = 'Searching NSE instruments…';
    this.searchResults = [];
    this.api.search(query).subscribe({
      next: (result) => {
        this.searchResults = result.instruments;
        this.searchMessage = result.instruments.length ? '' : 'No matching NSE instruments.';
      },
      error: (error: HttpErrorResponse) => {
        this.searchMessage = error.error?.detail || 'Instrument search failed.';
      }
    });
  }

  updateHistorySearch(value: string): void {
    this.historySearchText = value;
    this.selectedHistoryInstrument = undefined;
    if (this.historySearchTimer) clearTimeout(this.historySearchTimer);
    if (value.trim().length < 2) {
      this.historySearchOpen = false;
      return;
    }
    this.historySearchTimer = setTimeout(() => this.searchHistoryInstruments(value.trim()), 280);
  }

  searchHistoryInstruments(query: string): void {
    if (!this.connected) return;
    this.historySearchOpen = true;
    this.historySearchMessage = 'Searching NSE instruments…';
    this.historySearchResults = [];
    this.api.search(query).subscribe({
      next: (result) => {
        this.historySearchResults = result.instruments;
        this.historySearchMessage = result.instruments.length ? '' : 'No matching NSE stocks or indices.';
      },
      error: (error: HttpErrorResponse) => {
        this.historySearchMessage = error.error?.detail || 'Upstox instrument search failed.';
      }
    });
  }

  selectHistoryInstrument(instrument: Instrument): void {
    this.demoMode = false;
    this.historicalCandles = [];
    this.displayedCandles = [];
    this.selectedHistoryInstrument = instrument;
    this.historySearchText = `${instrument.symbol} · ${instrument.exchange}`;
    this.historySearchOpen = false;
    this.historySearchResults = [];
  }

  loadHistorical(): void {
    if (!this.connected || !this.selectedHistoryInstrument || !this.historicalFrom || !this.historicalTo) return;
    if (this.historicalFrom > this.historicalTo) {
      this.showToast('The start date must be on or before the end date.');
      return;
    }
    this.historicalLoading = true;
    this.demoMode = false;
    this.historicalCandles = [];
    this.displayedCandles = [];
    const [unit, intervalValue] = this.historicalInterval.split(':');
    this.api.historical(
      this.selectedHistoryInstrument.key,
      unit,
      Number(intervalValue),
      this.historicalFrom,
      this.historicalTo
    ).subscribe({
      next: (result) => {
        this.historicalCandles = result.candles;
        this.displayedCandles = [...result.candles].reverse().slice(0, 100);
        this.historicalLoading = false;
        this.drawHistoryChart();
        if (!result.candles.length) this.showToast('No candles were returned for that instrument and date range.');
      },
      error: (error: HttpErrorResponse) => {
        this.historicalLoading = false;
        if (error.status === 401) this.setConnected(false);
        this.showToast(error.error?.detail || 'Could not load Upstox historical data.');
      }
    });
  }

  runDemo(): void {
    const today = new Date();
    this.selectedHistoryInstrument = {
      key: 'DEMO:SAMPLE',
      symbol: 'DEMO',
      name: 'Synthetic sample only',
      exchange: 'DEMO'
    };
    this.historySearchText = 'DEMO · SAMPLE ONLY';
    this.historicalInterval = 'days:1';
    this.historicalTo = dateInputValue(today);
    const candles: HistoricalCandle[] = [];
    let previousClose = 1240;
    for (let day = 13; day >= 0; day--) {
      const candleDate = new Date(today);
      candleDate.setDate(today.getDate() - day);
      const movement = Math.sin(day * 0.83) * 12 + (13 - day) * 1.9;
      const open = previousClose + Math.cos(day * 1.17) * 4;
      const close = 1240 + movement;
      candles.push({
        timestamp: `${dateInputValue(candleDate)}T00:00:00+0530`,
        open: Number(open.toFixed(2)),
        high: Number((Math.max(open, close) + 5 + (day % 3)).toFixed(2)),
        low: Number((Math.min(open, close) - 4 - (day % 2)).toFixed(2)),
        close: Number(close.toFixed(2)),
        volume: 85000 + ((day * 17391) % 125000)
      });
      previousClose = close;
    }
    this.historicalFrom = candles[0].timestamp.slice(0, 10);
    this.historicalCandles = candles;
    this.displayedCandles = [...candles].reverse();
    this.demoMode = true;
    this.drawHistoryChart();
  }

  addInstrument(instrument: Instrument): void {
    if (this.watchlist.some((item) => item.key === instrument.key)) {
      this.showToast(`${instrument.symbol} is already in your watchlist.`);
      return;
    }
    this.watchlist = [...this.watchlist, instrument];
    this.saveWatchlist();
    this.searchText = '';
    this.searchOpen = false;
    this.refreshQuotes().subscribe();
  }

  removeInstrument(key: string): void {
    this.watchlist = this.watchlist.filter((instrument) => instrument.key !== key);
    delete this.quotes[key];
    this.saveWatchlist();
    this.refreshQuotes().subscribe();
  }

  disconnect(): void {
    this.api.logout().subscribe({
      next: () => {
        this.quotes = {};
        this.history = [];
        this.historicalCandles = [];
        this.displayedCandles = [];
        this.demoMode = false;
        this.setConnected(false);
        this.drawChart();
        this.drawHistoryChart();
        this.showToast('Upstox disconnected.');
      },
      error: () => this.showToast('Could not disconnect Upstox.')
    });
  }

  get connectionCopy(): string {
    if (this.connected) return 'Authorized session active. Quotes refresh every five seconds while this page is open.';
    return this.configured
      ? 'Connect your Upstox account to authorize live market quotes. Your API secret stays on this server.'
      : 'Add your Upstox app credentials to the server environment before connecting.';
  }

  get historyConnectionCopy(): string {
    return this.connected
      ? 'Upstox session active. Historical candles and live quotes use the same secure connection.'
      : 'Connect your verified Upstox account to search instruments and request historical candles.';
  }

  get historicalIntervalLabel(): string {
    const [unit, interval] = this.historicalInterval.split(':');
    const names: Record<string, string> = { minutes: 'minute', hours: 'hour', days: 'day', weeks: 'week', months: 'month' };
    return `${interval} ${names[unit] || unit}${Number(interval) > 1 ? 's' : ''}`;
  }

  showToast(message: string): void {
    this.toast = message;
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast = '', 3400);
  }

  private updateHistory(key: string, quote: LtpQuote): void {
    if (key !== 'NSE_INDEX|Nifty 50') return;
    this.history = [...this.history, quote.last_price].slice(-55);
  }

  private drawChart(): void {
    if (!this.chartReady || !this.chart) return;
    const canvas = this.chart.nativeElement;
    const context = canvas.getContext('2d');
    if (!context) return;
    const bounds = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(bounds.width * ratio));
    canvas.height = Math.max(1, Math.floor(bounds.height * ratio));
    context.scale(ratio, ratio);
    const width = bounds.width;
    const height = bounds.height;
    context.clearRect(0, 0, width, height);
    if (this.history.length < 2) return;
    const min = Math.min(...this.history);
    const spread = Math.max(...this.history) - min || 1;
    const points = this.history.map((value, index) => ({
      x: (index / (this.history.length - 1)) * width,
      y: height - 8 - ((value - min) / spread) * (height - 20)
    }));
    context.beginPath();
    points.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
    context.lineTo(width, height);
    context.lineTo(0, height);
    context.closePath();
    context.fillStyle = 'rgba(40,116,77,.08)';
    context.fill();
    context.beginPath();
    points.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
    context.strokeStyle = '#28744d';
    context.lineWidth = 1.8;
    context.stroke();
  }

  private drawHistoryChart(): void {
    if (!this.chartReady || !this.historyChart) return;
    const canvas = this.historyChart.nativeElement;
    const context = canvas.getContext('2d');
    if (!context) return;
    const bounds = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(bounds.width * ratio));
    canvas.height = Math.max(1, Math.floor(bounds.height * ratio));
    context.scale(ratio, ratio);
    context.clearRect(0, 0, bounds.width, bounds.height);
    if (this.historicalCandles.length < 2) return;
    const closes = this.historicalCandles.map((candle) => candle.close);
    const min = Math.min(...closes);
    const spread = Math.max(...closes) - min || 1;
    context.beginPath();
    closes.forEach((value, index) => {
      const x = (index / (closes.length - 1)) * bounds.width;
      const y = bounds.height - 8 - ((value - min) / spread) * (bounds.height - 20);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.strokeStyle = '#5b46d5';
    context.lineWidth = 1.8;
    context.stroke();
  }

  private loadWatchlist(): Instrument[] {
    try {
      const saved = localStorage.getItem(WATCHLIST_KEY);
      const parsed: unknown = saved ? JSON.parse(saved) : null;
      return Array.isArray(parsed) ? parsed as Instrument[] : [...DEFAULT_WATCHLIST];
    } catch {
      return [...DEFAULT_WATCHLIST];
    }
  }

  private saveWatchlist(): void { localStorage.setItem(WATCHLIST_KEY, JSON.stringify(this.watchlist)); }
  private updateClock(): void { this.clock = `${this.istTime()} IST`; }
  private istTime(): string {
    return new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date());
  }
}