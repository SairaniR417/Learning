import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, HostListener, Input, OnChanges, OnDestroy, ViewChild, inject } from '@angular/core';
import { Subscription, interval, timeout } from 'rxjs';
import { AutoscaleInfo, CandlestickSeries, ColorType, createChart, IChartApi, IPriceLine, ISeriesApi, LineSeries, UTCTimestamp } from 'lightweight-charts';
import { ChartQuote, HistoricalCandle, MarketApiService } from '../market-api.service';
import { bappuLevels, crossedBapuLevels } from './bappu-theory';
import { GhostPoint } from './ghost-rider.types';

@Component({
  selector: 'app-bappu-leg', standalone: true, imports: [CommonModule],
  templateUrl: './bappu-leg.component.html', styleUrl: './bappu-theory.component.css'
})
export class BappuLegComponent implements OnChanges, AfterViewInit, OnDestroy {
  @Input() underlyingKey = '';
  @Input() underlyingLabel = '';
  @Input() expiry = '';
  @Input() strike = 0;
  @Input() side: 'CE' | 'PE' = 'CE';
  @Input() timeframe = 5;
  @ViewChild('chartHost') chartHost?: ElementRef<HTMLElement>;
  private api = inject(MarketApiService);
  private quoteRequest?: Subscription;
  private historyRequest?: Subscription;
  private polling?: Subscription;
  private chart?: IChartApi;
  private series?: ISeriesApi<'Candlestick'>;
  private vwapSeries?: ISeriesApi<'Line'>;
  private lines: IPriceLine[] = [];
  private alerted = new Set<string>();
  private alertSession = '';
  alerts: { message: string; direction: 'BUY' | 'SELL'; time: string }[] = [];
  vwapPoints: GhostPoint[] = [];
  quote?: ChartQuote;
  candles: HistoricalCandle[] = [];
  quoteLoading = false;
  historyLoading = false;
  quoteError = '';
  historyError = '';
  get calculation() { return bappuLevels(this.quote); }
  get signal(): 'BUY' | 'SELL' | 'AT ATP' | 'UNAVAILABLE' {
    const price = this.quote?.price, atp = this.quote?.atp;
    if (typeof price !== 'number' || typeof atp !== 'number' || !Number.isFinite(price) || !Number.isFinite(atp) || price <= 0 || atp <= 0) return 'UNAVAILABLE';
    return price > atp ? 'BUY' : price < atp ? 'SELL' : 'AT ATP';
  }
  get latestVwap(): number | null { return this.vwapPoints.at(-1)?.vwap ?? null; }
  ngOnChanges(): void {
    this.cancel(); this.polling?.unsubscribe();
    this.quote = undefined; this.candles = []; this.vwapPoints = []; this.quoteError = this.historyError = '';
    this.alerted.clear(); this.alerts = []; this.alertSession = '';
    this.draw();
    if (!document.hidden) this.refresh();
    let ticks = 0;
    this.polling = interval(15000).subscribe(() => {
      if (document.hidden) return;
      this.loadQuote();
      if (++ticks % 4 === 0) this.loadHistory();
    });
  }
  ngAfterViewInit(): void {
    if (!this.chartHost) return;
    this.chart = createChart(this.chartHost.nativeElement, {
      autoSize: true, height: 340,
      layout: { background: { type: ColorType.Solid, color: '#000000' }, textColor: '#b8c9c4' },
      grid: { vertLines: { color: '#182521' }, horzLines: { color: '#182521' } },
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: unknown) =>
        typeof time === 'number' ? new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(time * 1000)) : '' },
      localization: { timeFormatter: (time: unknown) => typeof time === 'number' ? new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(time * 1000)) + ' IST' : '' }
    });
    this.series = this.chart.addSeries(CandlestickSeries, {
      upColor: '#55cba5', downColor: '#e78391', borderVisible: false, wickUpColor: '#55cba5', wickDownColor: '#e78391',
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const info = original();
        if (!info?.priceRange) return info;
        const prices = [this.quote?.dayLow, this.quote?.dayHigh, this.quote?.atp, ...(this.calculation?.targets.map(target => target.price) ?? [])]
          .filter((price): price is number => typeof price === 'number' && Number.isFinite(price) && price > 0);
        return { ...info, priceRange: {
          minValue: Math.min(info.priceRange.minValue, ...prices),
          maxValue: Math.max(info.priceRange.maxValue, ...prices)
        } };
      }
    });
    this.vwapSeries = this.chart.addSeries(LineSeries, {
      title: 'VWAP', color: '#4caf50', lineWidth: 2, priceLineVisible: false, crosshairMarkerVisible: true
    });
    this.draw(true);
  }
  refresh(): void { this.loadQuote(); this.loadHistory(); }
  loadQuote(): void {
    if (!this.underlyingKey || !this.expiry || !this.strike || this.quoteLoading) return;
    this.quoteLoading = true;
    this.quoteRequest = this.api.chartQuote(this.underlyingKey, this.expiry, this.strike, this.side).pipe(timeout(18000)).subscribe({
      next: quote => { this.checkLevels(quote); this.quote = quote; this.quoteLoading = false; this.quoteError = ''; this.drawLevels(); },
      error: error => { this.quoteLoading = false; this.quoteError = error.error?.detail || 'Latest quote unavailable. Retry refresh.'; }
    });
  }
  loadHistory(): void {
    if (!this.underlyingKey || !this.expiry || !this.strike || this.historyLoading) return;
    this.historyLoading = true;
    this.historyRequest = this.api.analyzeOption(this.underlyingKey, this.expiry, this.strike, this.side, this.timeframe).pipe(timeout(60000)).subscribe({
      next: analysis => {
        const first = !this.candles.length;
        this.candles = analysis.chartCandles ?? analysis.ghostRider?.candles ?? analysis.candles;
        this.vwapPoints = analysis.ghostRider?.points ?? [];
        this.historyLoading = false; this.historyError = ''; this.draw(first);
      },
      error: error => { this.historyLoading = false; this.historyError = error.error?.detail || 'Candle history unavailable. Retry refresh.'; }
    });
  }
  private draw(fit = false): void {
    this.series?.setData(this.candles.map(c => ({ time: Date.parse(c.timestamp) / 1000 as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));
    this.vwapSeries?.setData(this.vwapPoints.map(point => ({
      time: Date.parse(point.timestamp) / 1000 as UTCTimestamp,
      ...(point.vwap != null && Number.isFinite(point.vwap) ? { value: point.vwap, color: point.vwapColor } : {})
    })));
    this.drawLevels();
    if (fit) this.chart?.timeScale().fitContent();
  }
  private drawLevels(): void {
    if (!this.series) return;
    for (const line of this.lines) this.series.removePriceLine(line);
    this.lines = [];
    const add = (price: number | null | undefined, title: string, color: string) => {
      if (price != null && Number.isFinite(price) && price > 0) this.lines.push(this.series!.createPriceLine({ price, title, color, lineWidth: 1, axisLabelVisible: true }));
    };
    add(this.quote?.dayLow, 'DAY LOW', '#e78391');
    add(this.quote?.dayHigh, 'DAY HIGH', '#55cba5');
    add(this.quote?.atp, 'ATP', '#5da7ff');
    const levels = this.calculation;
    for (const target of levels?.targets ?? []) add(target.price, `${levels!.direction} ${target.multiple}×`, levels!.direction === 'SELL' ? '#ef9ca6' : '#55cba5');
  }
  private checkLevels(quote: ChartQuote): void {
    const session = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(quote.receivedAt));
    if (session !== this.alertSession) { this.alertSession = session; this.alerted.clear(); this.alerts = []; return; }
    const direction = bappuLevels(this.quote)?.direction;
    if (!direction) return;
    for (const target of crossedBapuLevels(this.quote, quote)) {
      const key = `${direction}:${target.multiple}`;
      if (this.alerted.has(key)) continue;
      this.alerted.add(key);
      const message = `${this.underlyingLabel || this.underlyingKey} ${this.expiry} ${this.strike} ${this.side} · ${direction} · ${target.multiple}× level ₹${target.price.toFixed(2)} reached · Current ₹${quote.price.toFixed(2)}`;
      this.alerts = [{ message, direction, time: quote.receivedAt }, ...this.alerts].slice(0, 10);
    }
  }
  @HostListener('document:visibilitychange') visibilityChanged(): void {
    if (document.hidden) this.cancel(); else this.refresh();
  }
  private cancel(): void { this.quoteRequest?.unsubscribe(); this.historyRequest?.unsubscribe(); this.quoteLoading = this.historyLoading = false; }
  ngOnDestroy(): void { this.cancel(); this.polling?.unsubscribe(); this.chart?.remove(); }
}
