import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild, inject } from '@angular/core';
import {
  CandlestickData,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineData,
  LineSeries,
  LineStyle,
  MouseEventParams,
  Time,
  UTCTimestamp,
  createChart,
  createSeriesMarkers
} from 'lightweight-charts';
import { EMPTY, Subscription, catchError, exhaustMap, tap, timer } from 'rxjs';
import { CompanyProfile, CorporateAction, HistoricalCandle, Instrument, LtpQuote, MarketApiService } from './market-api.service';
import {
  ADX,
  ATR,
  BollingerBands,
  EMA,
  MACD,
  RSI,
  SMA,
  bearishengulfingpattern,
  bullishengulfingpattern,
  doji,
  hammerpattern,
  shootingstar
} from 'technicalindicators';

type StudyName = 'sma20' | 'sma50' | 'ema20' | 'bollinger' | 'rsi' | 'macd' | 'supportResistance' | 'patterns';
type PatternInput = { open: number[]; high: number[]; low: number[]; close: number[] };
type TrendlinePoint = { time: Time; price: number; logical: number };
type PatternMarker = { time: Time; position: 'aboveBar' | 'belowBar'; color: string; shape: 'arrowDown' | 'arrowUp' | 'circle'; text: string; name: string };
type TechnicalSnapshot = {
  lastClose: number;
  changePercent: number;
  adx?: number;
  positiveDi?: number;
  negativeDi?: number;
  atr?: number;
  atrPercent?: number;
  sma20?: number;
  sma50?: number;
  rsi?: number;
  averageVolume20?: number;
  highestHigh20: number;
  lowestLow20: number;
  priceStructure: string;
  trendStrength: string;
  directionalPressure: string;
};
type RiskScenario = {
  lots: number;
  units: number;
  riskPerUnit: number;
  riskUsed: number;
  stopPrice: number;
  targetPrice: number;
};

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
  @ViewChild('historyChart') private historyChart?: ElementRef<HTMLDivElement>;

  watchlist = this.loadWatchlist();
  quotes: Record<string, LtpQuote> = {};
  searchResults: Instrument[] = [];
  history: number[] = [];
  connected = false;
  configured = true;
  searchText = '';
  watchlistMarket: 'cash' | 'commodities' = 'cash';
  searchMessage = '';
  searchOpen = false;
  toast = '';
  updatedTime = 'LIVE FEED OFF';
  clock = '';
  marketLabel = 'Awaiting connection';
  historySearchText = '';
  historyMarket: 'cash' | 'commodities' = 'cash';
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
  technicalSnapshot?: TechnicalSnapshot;
  companyProfile?: CompanyProfile;
  corporateActions: CorporateAction[] = [];
  fundamentalsLoading = false;
  riskBudget = 0;
  stopAtrMultiple = 2;
  targetRMultiple = 2;
  riskDirection: 'long' | 'short' | '' = '';
  readonly studies: Record<StudyName, boolean> = {
    sma20: true,
    sma50: false,
    ema20: false,
    bollinger: false,
    rsi: false,
    macd: false,
    supportResistance: true,
    patterns: true
  };
  trendlineMode = false;
  trendlineHint = '';
  detectedPatterns: PatternMarker[] = [];
  private historyChartApi?: IChartApi;
  private candleSeries?: ISeriesApi<'Candlestick'>;
  private rsiSeries?: ISeriesApi<'Line'>;
  private macdSeries?: ISeriesApi<'Line'>;
  private macdSignalSeries?: ISeriesApi<'Line'>;
  private macdHistogramSeries?: ISeriesApi<'Histogram'>;
  private markerPlugin?: ISeriesMarkersPluginApi<Time>;
  private overlaySeries: ISeriesApi<'Line'>[] = [];
  private trendlineSeries: ISeriesApi<'Line'>[] = [];
  private supportPriceLines: IPriceLine[] = [];
  private trendlineStart?: TrendlinePoint;

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
        this.historyChartApi?.timeScale().fitContent();
      });
      if (this.chart) this.resizeObserver.observe(this.chart.nativeElement);
    }
    this.initializeAnalysisCharts();
    if (this.historyChart) this.resizeObserver?.observe(this.historyChart.nativeElement);
    this.drawChart();
  }

  ngOnDestroy(): void {
    this.refreshSubscription?.unsubscribe();
    this.resizeObserver?.disconnect();
    this.historyChartApi?.remove();
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
    this.searchMessage = this.watchlistMarket === 'cash' ? 'Searching cash-market stocks…' : 'Searching MCX futures…';
    this.searchResults = [];
    this.api.search(query, this.watchlistMarket).subscribe({
      next: (result) => {
        this.searchResults = result.instruments;
        this.searchMessage = result.instruments.length ? '' : 'No matching instruments in this market.';
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
    this.historySearchMessage = this.historyMarket === 'cash' ? 'Searching cash-market stocks…' : 'Searching MCX futures…';
    this.historySearchResults = [];
    this.api.search(query, this.historyMarket).subscribe({
      next: (result) => {
        this.historySearchResults = result.instruments;
        this.historySearchMessage = result.instruments.length ? '' : 'No matching instruments in this market.';
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
    this.technicalSnapshot = undefined;
    this.selectedHistoryInstrument = instrument;
    this.historySearchText = `${instrument.symbol} · ${instrument.exchange}`;
    this.historySearchOpen = false;
    this.historySearchResults = [];
    this.riskDirection = '';
    this.loadEquityFundamentals(instrument);
  }

  setHistoryMarket(market: 'cash' | 'commodities'): void {
    this.historyMarket = market;
    this.historySearchText = '';
    this.historySearchResults = [];
    this.historySearchOpen = false;
    this.selectedHistoryInstrument = undefined;
    this.historicalCandles = [];
    this.displayedCandles = [];
    this.technicalSnapshot = undefined;
    this.companyProfile = undefined;
    this.corporateActions = [];
    this.riskDirection = '';
    this.demoMode = false;
    this.drawHistoryChart();
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
    this.technicalSnapshot = undefined;
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
        this.technicalSnapshot = this.calculateTechnicalSnapshot(result.candles);
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
    this.companyProfile = undefined;
    this.corporateActions = [];
    this.historicalInterval = 'days:1';
    this.historicalTo = dateInputValue(today);
    const candles: HistoricalCandle[] = [];
    let previousClose = 1240;
    for (let day = 79; day >= 0; day--) {
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
    this.technicalSnapshot = this.calculateTechnicalSnapshot(candles);
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
        this.technicalSnapshot = undefined;
        this.companyProfile = undefined;
        this.corporateActions = [];
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

  get globalContextNote(): string {
    if (this.historyMarket === 'commodities') {
      return 'Commodity prices can respond to global benchmarks, USD/INR, inventories, and policy. Cross-market correlations are not calculated in this view.';
    }
    const sector = this.companyProfile?.sector;
    return sector
      ? `${sector} sector. Macro sensitivity is not inferred from price candles; compare relevant benchmarks and company disclosures.`
      : 'Global and sector effects are not inferred from price candles alone.';
  }

  get holdingWindowNote(): string {
    return `This view uses ${this.historicalIntervalLabel} candles over ${this.historicalFrom} to ${this.historicalTo}. That describes the data interval, not a recommended holding period.`;
  }

  get historicalIntervalLabel(): string {
    const [unit, interval] = this.historicalInterval.split(':');
    const names: Record<string, string> = { minutes: 'minute', hours: 'hour', days: 'day', weeks: 'week', months: 'month' };
    return `${interval} ${names[unit] || unit}${Number(interval) > 1 ? 's' : ''}`;
  }

  get hasTrendlines(): boolean { return this.trendlineSeries.length > 0; }

  get patternSummary(): { name: string; count: number }[] {
    const counts = new Map<string, number>();
    for (const pattern of this.detectedPatterns.slice(-30)) counts.set(pattern.name, (counts.get(pattern.name) || 0) + 1);
    return Array.from(counts, ([name, count]) => ({ name, count }));
  }

  get dividendActions(): CorporateAction[] {
    return this.corporateActions.filter((action) => action.name.toLowerCase().includes('dividend'));
  }

  get riskScenario(): RiskScenario | undefined {
    const snapshot = this.technicalSnapshot;
    if (!snapshot?.atr || !this.selectedHistoryInstrument || !this.riskBudget || !this.riskDirection) return undefined;
    const lotSize = this.historyMarket === 'commodities' ? Math.max(1, this.selectedHistoryInstrument.lot_size || 1) : 1;
    const riskPerUnit = snapshot.atr * this.stopAtrMultiple;
    const riskPerLot = riskPerUnit * lotSize;
    const lots = Math.floor(this.riskBudget / riskPerLot);
    const units = lots * lotSize;
    const direction = this.riskDirection === 'long' ? 1 : -1;
    return {
      lots,
      units,
      riskPerUnit,
      riskUsed: units * riskPerUnit,
      stopPrice: snapshot.lastClose - direction * riskPerUnit,
      targetPrice: snapshot.lastClose + direction * riskPerUnit * this.targetRMultiple
    };
  }

  setRiskBudget(value: string): void {
    this.riskBudget = Math.max(0, Number(value) || 0);
  }

  setStopAtrMultiple(value: string): void {
    this.stopAtrMultiple = Math.min(5, Math.max(0.5, Number(value) || 2));
  }

  setTargetRMultiple(value: string): void {
    this.targetRMultiple = Math.min(5, Math.max(0.5, Number(value) || 2));
  }

  private calculateTechnicalSnapshot(inputCandles: HistoricalCandle[]): TechnicalSnapshot | undefined {
    const candles = [...inputCandles].sort((left, right) => left.timestamp.localeCompare(right.timestamp));
    if (candles.length < 2) return undefined;
    const closes = candles.map((candle) => candle.close);
    const latestClose = closes[closes.length - 1];
    const adxValues = ADX.calculate({ high: candles.map((candle) => candle.high), low: candles.map((candle) => candle.low), close: closes, period: 14 });
    const atrValues = ATR.calculate({ high: candles.map((candle) => candle.high), low: candles.map((candle) => candle.low), close: closes, period: 14 });
    const sma20Values = closes.length >= 20 ? SMA.calculate({ period: 20, values: closes }) : [];
    const sma50Values = closes.length >= 50 ? SMA.calculate({ period: 50, values: closes }) : [];
    const rsiValues = closes.length >= 15 ? RSI.calculate({ period: 14, values: closes }) : [];
    const adx = adxValues.at(-1);
    const atr = atrValues.at(-1);
    const recentCandles = candles.slice(-20);
    const structure = this.describePriceStructure(candles);
    return {
      lastClose: latestClose,
      changePercent: ((latestClose - closes[0]) / closes[0]) * 100,
      adx: adx?.adx,
      positiveDi: adx?.pdi,
      negativeDi: adx?.mdi,
      atr,
      atrPercent: atr === undefined ? undefined : atr / latestClose * 100,
      sma20: sma20Values.at(-1),
      sma50: sma50Values.at(-1),
      rsi: rsiValues.at(-1),
      averageVolume20: recentCandles.length ? recentCandles.reduce((total, candle) => total + candle.volume, 0) / recentCandles.length : undefined,
      highestHigh20: Math.max(...recentCandles.map((candle) => candle.high)),
      lowestLow20: Math.min(...recentCandles.map((candle) => candle.low)),
      priceStructure: structure,
      trendStrength: adx !== undefined ? adx.adx >= 25 ? 'Trend strength elevated' : adx.adx >= 20 ? 'Trend strength developing' : 'Weak or ranging trend' : 'Needs more candles',
      directionalPressure: adx !== undefined ? adx.pdi > adx.mdi ? '+DI above -DI' : adx.mdi > adx.pdi ? '-DI above +DI' : 'DI balanced' : 'Needs more candles'
    };
  }

  private describePriceStructure(candles: HistoricalCandle[]): string {
    const highs: number[] = [];
    const lows: number[] = [];
    for (let index = 2; index < candles.length - 2; index++) {
      const neighborhood = candles.slice(index - 2, index + 3);
      const high = candles[index].high;
      const low = candles[index].low;
      if (neighborhood.every((candle, offset) => offset === 2 || high >= candle.high)) highs.push(high);
      if (neighborhood.every((candle, offset) => offset === 2 || low <= candle.low)) lows.push(low);
    }
    if (highs.length < 2 || lows.length < 2) return 'Not enough swing points';
    const higherHighs = highs.at(-1)! > highs.at(-2)!;
    const higherLows = lows.at(-1)! > lows.at(-2)!;
    const lowerHighs = highs.at(-1)! < highs.at(-2)!;
    const lowerLows = lows.at(-1)! < lows.at(-2)!;
    if (higherHighs && higherLows) return 'Higher highs and higher lows';
    if (lowerHighs && lowerLows) return 'Lower highs and lower lows';
    return 'Mixed swing structure';
  }

  private loadEquityFundamentals(instrument: Instrument): void {
    this.companyProfile = undefined;
    this.corporateActions = [];
    if (!instrument.isin) return;
    this.fundamentalsLoading = true;
    let pending = 2;
    const done = () => {
      pending--;
      if (pending === 0) this.fundamentalsLoading = false;
    };
    this.api.companyProfile(instrument.isin).subscribe({
      next: (profile) => { this.companyProfile = profile; done(); },
      error: () => done()
    });
    this.api.corporateActions(instrument.isin).subscribe({
      next: (response) => { this.corporateActions = response.actions; done(); },
      error: () => done()
    });
  }

  setStudy(study: StudyName, enabled: boolean): void {
    this.studies[study] = enabled;
    this.drawHistoryChart();
  }

  toggleTrendlineMode(): void {
    this.trendlineMode = !this.trendlineMode;
    this.trendlineStart = undefined;
    this.trendlineHint = this.trendlineMode ? 'Click two points on the chart to draw a trendline.' : '';
  }

  undoTrendline(): void {
    const series = this.trendlineSeries.pop();
    if (series && this.historyChartApi) this.historyChartApi.removeSeries(series);
    if (!this.trendlineSeries.length) this.trendlineMode = false;
    this.trendlineHint = '';
  }

  clearTrendlines(): void {
    for (const series of this.trendlineSeries) this.historyChartApi?.removeSeries(series);
    this.trendlineSeries = [];
    this.trendlineMode = false;
    this.trendlineStart = undefined;
    this.trendlineHint = '';
  }

  private initializeAnalysisCharts(): void {
    if (this.historyChart) {
      this.historyChartApi = this.createChart(this.historyChart.nativeElement);
      this.candleSeries = this.historyChartApi.addSeries(CandlestickSeries, {
        upColor: '#28744d',
        downColor: '#c45b4b',
        borderVisible: false,
        wickUpColor: '#28744d',
        wickDownColor: '#c45b4b'
      });
      this.historyChartApi.subscribeClick(this.handleTrendlineClick);
    }
  }

  get analysisChartHeight(): number {
    return 390 + (this.studies.rsi ? 130 : 0) + (this.studies.macd ? 150 : 0);
  }

  private createChart(container: HTMLDivElement): IChartApi {
    return createChart(container, {
      autoSize: true,
      height: this.analysisChartHeight,
      layout: { background: { type: ColorType.Solid, color: '#fafaf7' }, textColor: '#747a71' },
      grid: { vertLines: { color: '#e8e9e2' }, horzLines: { color: '#e8e9e2' } },
      rightPriceScale: { borderColor: '#dedfd8' },
      timeScale: { borderColor: '#dedfd8', timeVisible: this.isIntraday(), secondsVisible: false },
      crosshair: { mode: CrosshairMode.Magnet }
    });
  }

  private isIntraday(): boolean {
    return this.historicalInterval.startsWith('minutes:') || this.historicalInterval.startsWith('hours:');
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
    if (!this.chartReady || !this.historyChartApi || !this.candleSeries) return;
    this.syncStudyPanes();
    const unit = this.historicalInterval.split(':')[0];
    const candles = [...this.historicalCandles].sort((left, right) => left.timestamp.localeCompare(right.timestamp));
    const candleData: CandlestickData<Time>[] = candles.map((candle) => ({
      time: this.chartTime(candle.timestamp, unit),
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close
    }));
    this.candleSeries.setData(candleData);
    this.clearAnalysisOverlays();

    if (candles.length < 2) {
      this.markerPlugin?.setMarkers([]);
      this.rsiSeries?.setData([]);
      this.macdSeries?.setData([]);
      this.macdSignalSeries?.setData([]);
      this.macdHistogramSeries?.setData([]);
      return;
    }

    const closes = candles.map((candle) => candle.close);
    const times = candleData.map((candle) => candle.time);
    if (this.studies.sma20 && closes.length >= 20) {
      this.addOverlay(SMA.calculate({ period: 20, values: closes }), 19, times, 'SMA 20', '#d18b35');
    }
    if (this.studies.sma50 && closes.length >= 50) {
      this.addOverlay(SMA.calculate({ period: 50, values: closes }), 49, times, 'SMA 50', '#28744d');
    }
    if (this.studies.ema20 && closes.length >= 20) {
      this.addOverlay(EMA.calculate({ period: 20, values: closes }), 19, times, 'EMA 20', '#5b46d5');
    }
    if (this.studies.bollinger && closes.length >= 20) {
      const bands = BollingerBands.calculate({ period: 20, values: closes, stdDev: 2 });
      const bandOffset = closes.length - bands.length;
      this.addOverlay(bands.map((band) => band.upper), bandOffset, times, 'BB Upper', '#8c7cbd');
      this.addOverlay(bands.map((band) => band.middle), bandOffset, times, 'BB Mid', '#a39ab9');
      this.addOverlay(bands.map((band) => band.lower), bandOffset, times, 'BB Lower', '#8c7cbd');
    }

    if (this.studies.rsi && this.rsiSeries) {
      const rsi = RSI.calculate({ period: 14, values: closes });
      const offset = closes.length - rsi.length;
      this.rsiSeries.setData(rsi.map((value, index) => ({ time: times[index + offset], value })));
    }

    if (this.studies.macd && this.macdSeries && this.macdSignalSeries && this.macdHistogramSeries) {
      const macd = MACD.calculate({ values: closes, fastPeriod: 12, slowPeriod: 26, signalPeriod: 9, SimpleMAOscillator: false, SimpleMASignal: false });
      const offset = closes.length - macd.length;
      const macdLine: LineData<Time>[] = [];
      const signalLine: LineData<Time>[] = [];
      const histogram = [] as { time: Time; value: number; color: string }[];
      macd.forEach((point, index) => {
        const time = times[index + offset];
        if (point.MACD !== undefined) macdLine.push({ time, value: point.MACD });
        if (point.signal !== undefined) signalLine.push({ time, value: point.signal });
        if (point.histogram !== undefined) histogram.push({ time, value: point.histogram, color: point.histogram >= 0 ? '#28744d55' : '#c45b4b55' });
      });
      this.macdSeries.setData(macdLine);
      this.macdSignalSeries.setData(signalLine);
      this.macdHistogramSeries.setData(histogram);
    }

    if (this.studies.supportResistance) this.drawSupportResistance(candles);
    if (this.studies.patterns) {
      this.detectedPatterns = this.detectPatterns(candles, times);
      if (this.candleSeries) {
        this.markerPlugin ??= createSeriesMarkers(this.candleSeries, []);
        this.markerPlugin.setMarkers(this.detectedPatterns);
      }
    } else {
      this.detectedPatterns = [];
      this.markerPlugin?.setMarkers([]);
    }
    this.historyChartApi.timeScale().fitContent();
  }

  private syncStudyPanes(): void {
    if (!this.historyChartApi) return;
    if (this.studies.rsi && !this.rsiSeries) {
      const pane = this.historyChartApi.addPane(false);
      pane.moveTo(1);
      pane.setStretchFactor(1.2);
      this.rsiSeries = this.historyChartApi.addSeries(LineSeries, { color: '#5b46d5', lineWidth: 2, title: 'RSI 14' }, pane.paneIndex());
      this.rsiSeries.createPriceLine({ price: 70, color: '#c45b4b80', lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '70' });
      this.rsiSeries.createPriceLine({ price: 30, color: '#28744d80', lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '30' });
    } else if (!this.studies.rsi && this.rsiSeries) {
      this.historyChartApi.removeSeries(this.rsiSeries);
      this.rsiSeries = undefined;
    }

    if (this.studies.macd && !this.macdSeries) {
      const pane = this.historyChartApi.addPane(false);
      pane.moveTo(this.studies.rsi ? 2 : 1);
      pane.setStretchFactor(1.3);
      const paneIndex = pane.paneIndex();
      this.macdHistogramSeries = this.historyChartApi.addSeries(HistogramSeries, { title: 'Histogram', base: 0 }, paneIndex);
      this.macdSeries = this.historyChartApi.addSeries(LineSeries, { color: '#28744d', lineWidth: 2, title: 'MACD' }, paneIndex);
      this.macdSignalSeries = this.historyChartApi.addSeries(LineSeries, { color: '#c45b4b', lineWidth: 1, title: 'Signal' }, paneIndex);
    } else if (!this.studies.macd && this.macdSeries) {
      this.historyChartApi.removeSeries(this.macdHistogramSeries!);
      this.historyChartApi.removeSeries(this.macdSeries);
      this.historyChartApi.removeSeries(this.macdSignalSeries!);
      this.macdHistogramSeries = undefined;
      this.macdSeries = undefined;
      this.macdSignalSeries = undefined;
    }
    this.historyChartApi.panes()[0]?.setStretchFactor(5);
  }

  private chartTime(timestamp: string, unit: string): Time {
    if (unit === 'minutes' || unit === 'hours') {
      return Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;
    }
    const [year, month, day] = timestamp.slice(0, 10).split('-').map(Number);
    return { year, month, day };
  }

  private addOverlay(values: number[], offset: number, times: Time[], title: string, color: string): void {
    if (!this.historyChartApi) return;
    const series = this.historyChartApi.addSeries(LineSeries, { color, lineWidth: 2, title, lastValueVisible: false, priceLineVisible: false });
    series.setData(values.map((value, index) => ({ time: times[index + offset], value })));
    this.overlaySeries.push(series);
  }

  private clearAnalysisOverlays(): void {
    if (this.historyChartApi) {
      for (const series of this.overlaySeries) this.historyChartApi.removeSeries(series);
    }
    this.overlaySeries = [];
    if (this.candleSeries) {
      for (const line of this.supportPriceLines) this.candleSeries.removePriceLine(line);
    }
    this.supportPriceLines = [];
  }

  private drawSupportResistance(candles: HistoricalCandle[]): void {
    if (!this.candleSeries || candles.length < 7) return;
    const supports: number[] = [];
    const resistances: number[] = [];
    for (let index = 2; index < candles.length - 2; index++) {
      const candle = candles[index];
      const neighbors = candles.slice(index - 2, index + 3).filter((_, offset) => offset !== 2);
      if (neighbors.every((item) => candle.low <= item.low)) supports.push(candle.low);
      if (neighbors.every((item) => candle.high >= item.high)) resistances.push(candle.high);
    }
    const lastClose = candles[candles.length - 1].close;
    const nearSupport = supports.filter((level) => level < lastClose).sort((a, b) => b - a).slice(0, 2);
    const nearResistance = resistances.filter((level) => level > lastClose).sort((a, b) => a - b).slice(0, 2);
    nearSupport.forEach((price, index) => this.supportPriceLines.push(this.candleSeries!.createPriceLine({ price, color: '#28744d99', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `S${index + 1}` })));
    nearResistance.forEach((price, index) => this.supportPriceLines.push(this.candleSeries!.createPriceLine({ price, color: '#c45b4b99', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `R${index + 1}` })));
  }

  private detectPatterns(candles: HistoricalCandle[], times: Time[]): PatternMarker[] {
    const detectors = [
      { name: 'Doji', marker: 'D', shape: 'circle' as const, color: '#8070b5', position: 'aboveBar' as const, detect: doji as unknown as (input: PatternInput) => boolean, lookback: 1 },
      { name: 'Bullish engulfing', marker: 'BE', shape: 'arrowUp' as const, color: '#28744d', position: 'belowBar' as const, detect: bullishengulfingpattern as unknown as (input: PatternInput) => boolean, lookback: 2 },
      { name: 'Bearish engulfing', marker: 'SE', shape: 'arrowDown' as const, color: '#c45b4b', position: 'aboveBar' as const, detect: bearishengulfingpattern as unknown as (input: PatternInput) => boolean, lookback: 2 },
      { name: 'Hammer pattern', marker: 'H', shape: 'arrowUp' as const, color: '#438c6a', position: 'belowBar' as const, detect: hammerpattern as unknown as (input: PatternInput) => boolean, lookback: 5 },
      { name: 'Shooting star', marker: 'SS', shape: 'arrowDown' as const, color: '#bc7254', position: 'aboveBar' as const, detect: shootingstar as unknown as (input: PatternInput) => boolean, lookback: 5 }
    ];
    const markers: PatternMarker[] = [];
    for (let index = 0; index < candles.length; index++) {
      for (const detector of detectors) {
        if (index + 1 < detector.lookback) continue;
        const sample = candles.slice(index + 1 - detector.lookback, index + 1);
        const input = {
          open: sample.map((candle) => candle.open),
          high: sample.map((candle) => candle.high),
          low: sample.map((candle) => candle.low),
          close: sample.map((candle) => candle.close)
        };
        try {
          if (detector.detect(input)) markers.push({ time: times[index], text: detector.marker, name: detector.name, position: detector.position, color: detector.color, shape: detector.shape });
        } catch {
          continue;
        }
      }
    }
    return markers.slice(-60);
  }

  private handleTrendlineClick = (event: MouseEventParams<Time>): void => {
    if (!this.trendlineMode || !this.historyChartApi || !this.candleSeries || !event.time || !event.point || event.logical === undefined) return;
    const price = this.candleSeries.coordinateToPrice(event.point.y);
    const point: TrendlinePoint = { time: event.time, price: Number(price), logical: Number(event.logical) };
    if (!this.trendlineStart) {
      this.trendlineStart = point;
      this.trendlineHint = 'First point set. Click the second point.';
      return;
    }
    const points = [this.trendlineStart, point].sort((left, right) => left.logical - right.logical);
    const series = this.historyChartApi.addSeries(LineSeries, { color: '#5b46d5', lineWidth: 2, lineStyle: LineStyle.LargeDashed, title: 'Trendline', lastValueVisible: false, priceLineVisible: false });
    series.setData(points.map((item) => ({ time: item.time, value: item.price })));
    this.trendlineSeries.push(series);
    this.trendlineStart = undefined;
    this.trendlineMode = false;
    this.trendlineHint = 'Trendline added.';
  };

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