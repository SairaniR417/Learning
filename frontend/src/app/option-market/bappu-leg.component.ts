import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, HostListener, Input, OnChanges, OnDestroy, ViewChild, inject } from '@angular/core';
import { Subscription, interval, timeout } from 'rxjs';
import { AutoscaleInfo, CandlestickSeries, ColorType, createChart, IChartApi, IPriceLine, ISeriesApi, UTCTimestamp } from 'lightweight-charts';
import { ChartQuote, HistoricalCandle, MarketApiService } from '../market-api.service';
import { bappuLevels } from './bappu-theory';

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
  private lines: IPriceLine[] = [];
  quote?: ChartQuote;
  candles: HistoricalCandle[] = [];
  quoteLoading = false;
  historyLoading = false;
  quoteError = '';
  historyError = '';
  get calculation() { return bappuLevels(this.quote); }
  ngOnChanges(): void {
    this.cancel(); this.polling?.unsubscribe();
    this.quote = undefined; this.candles = []; this.quoteError = this.historyError = '';
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
        const prices = [this.quote?.dayLow, this.quote?.atp, ...(this.calculation?.targets.map(target => target.price) ?? [])]
          .filter((price): price is number => typeof price === 'number' && Number.isFinite(price) && price > 0);
        return { ...info, priceRange: {
          minValue: Math.min(info.priceRange.minValue, ...prices),
          maxValue: Math.max(info.priceRange.maxValue, ...prices)
        } };
      }
    });
    this.draw(true);
  }
  refresh(): void { this.loadQuote(); this.loadHistory(); }
  loadQuote(): void {
    if (!this.underlyingKey || !this.expiry || !this.strike || this.quoteLoading) return;
    this.quoteLoading = true;
    this.quoteRequest = this.api.chartQuote(this.underlyingKey, this.expiry, this.strike, this.side).pipe(timeout(18000)).subscribe({
      next: quote => { this.quote = quote; this.quoteLoading = false; this.quoteError = ''; this.drawLevels(); },
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
        this.historyLoading = false; this.historyError = ''; this.draw(first);
      },
      error: error => { this.historyLoading = false; this.historyError = error.error?.detail || 'Candle history unavailable. Retry refresh.'; }
    });
  }
  private draw(fit = false): void {
    this.series?.setData(this.candles.map(c => ({ time: Date.parse(c.timestamp) / 1000 as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));
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
    add(this.quote?.atp, 'ATP', '#5da7ff');
    for (const target of this.calculation?.targets ?? []) add(target.price, target.multiple + '×', '#55cba5');
  }
  @HostListener('document:visibilitychange') visibilityChanged(): void {
    if (document.hidden) this.cancel(); else this.refresh();
  }
  private cancel(): void { this.quoteRequest?.unsubscribe(); this.historyRequest?.unsubscribe(); this.quoteLoading = this.historyLoading = false; }
  ngOnDestroy(): void { this.cancel(); this.polling?.unsubscribe(); this.chart?.remove(); }
}
