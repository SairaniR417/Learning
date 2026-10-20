import { OptionChainComponent } from './option-chain.component';
import { CommonModule } from '@angular/common';
import { Component, ElementRef, EventEmitter, HostListener, Input, NgZone, OnChanges, OnDestroy, Output, ViewChild, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { CandlestickSeries, HistogramSeries, ColorType, CrosshairMode, createChart, IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { MarketApiService, SelectedStock, StockHistory, StockNews, CompanyProfile, CorporateAction, HistoricalCandle, Instrument } from '../market-api.service';

@Component({ selector: 'app-stock-details', standalone: true, imports: [CommonModule, OptionChainComponent], templateUrl: './stock-details.component.html', styleUrl: './stock-details.component.css' })
export class StockDetailsComponent implements OnChanges, OnDestroy {
  @Input() stock: SelectedStock | null = null;
  @Output() stockSelected = new EventEmitter<SelectedStock>();
  searchQuery = '';
  searchResults: Instrument[] = [];
  searchLoading = false;
  searchError = '';
  searchFinished = false;
  private searchTimer?: ReturnType<typeof setTimeout>;
  private searchSubscription?: Subscription;
  searchStock(query: string): void {
    clearTimeout(this.searchTimer); this.searchSubscription?.unsubscribe();
    this.searchQuery = query; this.searchResults = []; this.searchError = ''; this.searchFinished = false;
    const term = query.trim(); this.searchLoading = term.length >= 2;
    if (!this.searchLoading) return;
    this.searchTimer = setTimeout(() => {
      this.searchSubscription = this.api.search(term).subscribe({ next: data => {
        this.searchResults = data.instruments;
        this.searchLoading = false; this.searchFinished = true;
      }, error: error => { this.searchError = error.error?.detail || 'Unable to search stocks. Please try again.'; this.searchLoading = false; this.searchFinished = true; } });
    }, 300);
  }
  chooseStock(instrument: Instrument): void {
    this.searchStock('');
    this.stockSelected.emit({ key: instrument.key, symbol: instrument.symbol, name: instrument.name, exchange: instrument.exchange });
  }
  private api = inject(MarketApiService);
  private zone = inject(NgZone);
  private chartApi?: IChartApi;
  private candleSeries?: ISeriesApi<'Candlestick'>;
  private volumeSeries?: ISeriesApi<'Histogram'>;
  expanded = false;
  private previousOverflow = '';
  activeTab = 'overview';
  readonly tabs = [{ id: 'overview', label: 'Overview' }, { id: 'company', label: 'Company' }, { id: 'news', label: 'News' }, { id: 'actions', label: 'Actions' }, { id: 'history', label: 'History' }, { id: 'options', label: 'Option Chain' }];
  hoveredCandle: HistoricalCandle | null = null;
  @ViewChild('chartHost') set chartHost(ref: ElementRef<HTMLElement> | undefined) {
    this.chartApi?.remove(); this.chartApi = undefined;
    this.candleSeries = undefined; this.volumeSeries = undefined;
    if (!ref) return;
    this.chartApi = createChart(ref.nativeElement, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#101318' }, textColor: '#9ba6b5', fontSize: 11 },
      grid: { vertLines: { color: '#ffffff06' }, horzLines: { color: '#ffffff08' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2b323c', scaleMargins: { top: .08, bottom: .25 } },
      timeScale: { borderColor: '#2b323c', rightOffset: 3, barSpacing: 8, minBarSpacing: .5 },
      localization: { locale: 'en-IN' }
    });
    this.candleSeries = this.chartApi.addSeries(CandlestickSeries, { upColor: '#49cba1', downColor: '#ed7882', wickUpColor: '#49cba1', wickDownColor: '#ed7882', borderVisible: false, priceFormat: { type: 'price', precision: 2, minMove: .01 } });
    this.volumeSeries = this.chartApi.addSeries(HistogramSeries, { priceScaleId: 'volume', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    this.volumeSeries.priceScale().applyOptions({ scaleMargins: { top: .82, bottom: 0 }, visible: false });
    this.chartApi.subscribeCrosshairMove(event => {
      const data = this.candleSeries ? event.seriesData.get(this.candleSeries) : undefined;
      const selected = data ? this.chart.find(c => c.timestamp.slice(0, 10) === String(data.time)) ?? null : null;
      this.zone.run(() => this.hoveredCandle = selected);
    });
    this.drawChart();
  }
  private subscriptions = new Subscription();
  history?: StockHistory; news?: StockNews; profile?: CompanyProfile; actions: CorporateAction[] = [];
  historyError = ''; newsError = ''; profileError = ''; actionsError = ''; quoteError = '';
  loading = false; newsLoading = false; profileLoading = false; actionsLoading = false;
  quote: number | null = null; quoteAt = ''; page = 1; range = '1M';
  chart: HistoricalCandle[] = [];
  readonly ranges = ['1M', '6M', '1Y', '5Y', 'ALL'];
  get isin(): string { return this.stock?.key.split('|')[1] ?? ''; }
  get signalTone(): string {
    const status = this.stock?.status ?? '';
    if (/BEARISH|SELL|WEAKENED|DECLINER/.test(status)) return 'bearish';
    if (/BULLISH|BUY|ALIGNED|GAINER/.test(status)) return 'bullish';
    return 'neutral';
  }
  get signalTitle(): string { return (this.stock?.status ?? 'Strategy match').replaceAll('_', ' ').toLowerCase(); }
  get signalMetrics(): { label: string; value: number; compareToClose: boolean }[] {
    const metrics = this.stock?.metrics ?? [];
    return metrics.filter((metric, index) => Number.isFinite(metric.value) && metrics.findIndex(other => other.label === metric.label) === index);
  }
  get confirmationChecks(): { label: string; passed?: boolean }[] {
    return (this.stock?.checks ?? []).filter(check => check.passed !== undefined).map(check => ({
      ...check, label: /^RSI\b/.test(check.label) ? 'RSI momentum' : check.label
    }));
  }
  get passedChecks(): number { return this.confirmationChecks.filter(check => check.passed).length; }
  get divergenceEvidence(): { label: string }[] { return this.stock?.strategy === 'RSI Divergence' ? (this.stock.checks ?? []).filter(check => check.passed === undefined && !check.label.startsWith('Current RSI')) : []; }
  ngOnChanges(): void { this.activeTab = 'overview'; this.load(); }
  ngOnDestroy(): void { clearTimeout(this.searchTimer); this.searchSubscription?.unsubscribe(); this.subscriptions.unsubscribe(); this.chartApi?.remove(); if (this.expanded) document.body.style.overflow = this.previousOverflow; }
  load(): void {
    this.subscriptions.unsubscribe(); this.subscriptions = new Subscription();
    this.history = undefined; this.news = undefined; this.profile = undefined; this.actions = []; this.chart = [];
    this.historyError = this.newsError = this.profileError = this.actionsError = this.quoteError = '';
    this.quote = null; this.quoteAt = ''; this.page = 1; this.range = '1M'; this.hoveredCandle = null;
    this.candleSeries?.setData([]); this.volumeSeries?.setData([]);
    this.newsLoading = this.profileLoading = this.actionsLoading = false;
    if (!this.stock) return;
    this.loadHistory(1); this.loadNews();
    const stock = this.stock;
    this.subscriptions.add(this.api.quotes([stock.key]).subscribe({ next: response => {
      const quote = Object.values(response.data).find(q => q.instrument_token === stock.key) ?? Object.values(response.data)[0];
      if (quote) { this.quote = quote.last_price; this.quoteAt = new Date().toISOString(); }
    }, error: () => this.quoteError = 'Live quote unavailable. Stored closing prices remain available.' }));
    if (!/^IN[A-Z0-9]{10}$/.test(this.isin)) { this.profileError = this.actionsError = 'Company fundamentals are available for Indian cash equities with an ISIN.'; return; }
    this.profileLoading = this.actionsLoading = true;
    this.subscriptions.add(this.api.companyProfile(this.isin).subscribe({ next: data => { this.profile = data; this.profileLoading = false; }, error: e => { this.profileError = e.error?.detail || 'Company profile unavailable from Upstox.'; this.profileLoading = false; } }));
    this.subscriptions.add(this.api.corporateActions(this.isin).subscribe({ next: data => { this.actions = data.actions; this.actionsLoading = false; }, error: e => { this.actionsError = e.error?.detail || 'Corporate actions unavailable from Upstox.'; this.actionsLoading = false; } }));
  }
  loadHistory(page: number): void {
    if (!this.stock) return;
    this.loading = true; this.historyError = '';
    this.subscriptions.add(this.api.stockHistory(this.stock.key, page).subscribe({ next: data => {
      this.history = data; this.page = page;
      if (page === 1) {
        const valid = data.chart.filter(c => [c.open, c.high, c.low, c.close, c.volume].every(Number.isFinite));
        this.chart = [...new Map(valid.map(c => [c.timestamp.slice(0, 10), c])).values()].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
        if (data.chart.length && !this.chart.length) this.historyError = 'Restart the API to load full OHLCV data for candlesticks.';
        this.drawChart();
      }
      this.loading = false;
    }, error: e => { this.historyError = e.error?.detail || 'Price history unavailable.'; this.loading = false; } }));
  }
  loadNews(): void {
    if (!this.stock || this.newsLoading) return;
    this.newsLoading = true; this.newsError = '';
    this.subscriptions.add(this.api.stockNews(this.stock.symbol, this.stock.name).subscribe({ next: data => { this.news = data; this.newsLoading = false; }, error: e => { this.newsError = e.error?.detail || 'News unavailable.'; this.newsLoading = false; } }));
  }
  get visibleChart(): HistoricalCandle[] {
    const months: Record<string, number> = { '1M': 1, '6M': 6, '1Y': 12, '5Y': 60 };
    if (!months[this.range] || !this.chart.length) return this.chart;
    const cutoff = new Date(this.chart[this.chart.length - 1].timestamp); cutoff.setMonth(cutoff.getMonth() - months[this.range]);
    return this.chart.filter(c => new Date(c.timestamp) >= cutoff);
  }
  private drawChart(): void {
    this.candleSeries?.setData(this.chart.map(c => ({ time: c.timestamp.slice(0, 10) as Time, open: c.open, high: c.high, low: c.low, close: c.close })));
    this.volumeSeries?.setData(this.chart.map(c => ({ time: c.timestamp.slice(0, 10) as Time, value: c.volume, color: c.close >= c.open ? '#49cba150' : '#ed788250' })));
    this.setRange(this.range);
  }
  setRange(range: string): void {
    this.range = range;
    const data = this.visibleChart;
    if (!data.length || !this.chartApi) return;
    if (range === 'ALL' || data.length === 1) this.chartApi.timeScale().fitContent();
    else this.chartApi.timeScale().setVisibleRange({ from: data[0].timestamp.slice(0, 10) as Time, to: data[data.length - 1].timestamp.slice(0, 10) as Time });
  }
  toggleFullscreen(): void {
    this.expanded = !this.expanded;
    if (this.expanded) { this.previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
    else document.body.style.overflow = this.previousOverflow;
  }
  @HostListener('document:keydown.escape') closeFullscreen(): void { if (this.expanded) this.toggleFullscreen(); }
  get selectedCandle(): HistoricalCandle | null { return this.hoveredCandle ?? this.chart[this.chart.length - 1] ?? null; }
  get returnPct(): number | null { const c = this.visibleChart; return c.length > 1 && c[0].close ? (c[c.length - 1].close / c[0].close - 1) * 100 : null; }
  get pages(): number { return Math.ceil((this.history?.total ?? 0) / 50); }
  get indicators(): { label: string; value: number | null }[] {
    const values = this.chart.map(c => c.close);
    const ema = (period: number): number | null => values.length < period ? null : values.reduce((average, value, i) => i ? value * 2 / (period + 1) + average * (1 - 2 / (period + 1)) : value, 0);
    const sma = (period: number): number | null => values.length < period ? null : values.slice(-period).reduce((sum, value) => sum + value, 0) / period;
    return [{ label: 'EMA 9', value: ema(9) }, { label: 'EMA 20', value: ema(20) }, { label: 'SMA 50', value: sma(50) }, { label: 'SMA 200', value: sma(200) }];
  }
}
