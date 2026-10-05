import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { AfterViewInit, Component, ElementRef, HostListener, OnDestroy, OnInit, ViewChild, inject } from '@angular/core';
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
  SMA
} from 'technicalindicators';
import { detectCandlestickPatterns } from './candlestick-patterns';
import { detectTraderGitaPatterns, TraderGitaPatternGroup } from './traders-gita-patterns';
import { DrishtiDashboardComponent } from './drishti/drishti-dashboard.component';

type StudyName = 'sma20' | 'sma50' | 'ema9' | 'ema20' | 'ema50' | 'ema200' | 'bollinger' | 'rsi' | 'macd' | 'supportResistance' | 'patterns' | 'fibonacci' | 'emaSignal';
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
  ema9?: number;
  ema20?: number;
  ema50?: number;
  ema200?: number;
  emaAlignment: 'Bullish' | 'Bearish' | 'Mixed' | 'Needs 200 candles';
  bullishSetup: boolean;
  bullishEntry: boolean;
  bullishCrossover: boolean;
  bearishCrossover: boolean;
  ema20Rising: boolean;
  ema50Rising: boolean;
  pullbackNearEma: boolean;
  bullishRejection: boolean;
  breaksRejectionHigh: boolean;
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
  entryPrice: number;
};
type GhostRiderSnapshot = {
  bullPct: number; bearPct: number; scoreTotal: number; scoreAvailable: number; bias: string;
  closeAboveVwap: boolean; rsi: number; rsi5m?: number; macdBullish: boolean; adx: number;
  emaBullish: boolean; atr: number; volumeHigh: boolean; cross: 'BUY' | 'SELL' | 'WAIT';
  signal: 'LONG' | 'SHORT' | 'WAIT'; entry?: number; stop?: number; targets: number[]; targetHits: boolean[]; retest: boolean;
};
type GhostRiderVisibilityKey = 'ema9' | 'ema21' | 'vwap' | 'signals' | 'dashboard' | 'entry' | 'stop' | 'tp1' | 'tp2' | 'tp3' | 'tp4' | 'tp5';
type TraderGitaPatternSetting = 'dojiPct' | 'smallBodyPct' | 'longBodyMult' | 'wickBodyMult' | 'tinyWickPct' | 'avgBodyLen' | 'trendLen' | 'tweezerTicks';
type GhostRiderResult = {
  snapshot: GhostRiderSnapshot;
  ema9: (number | undefined)[]; ema21: (number | undefined)[]; vwap: (number | undefined)[];
  markers: PatternMarker[]; candleColors: (string | undefined)[];
};
type KnowledgePattern = { name: string; family: string; bias: string; candles: string; description: string; rule: string };
type FibonacciSummary = { direction: 'upswing' | 'downswing'; start: string; end: string; low: number; high: number };
type CandleDrawing = { x: number; high: number; low: number; open: number; close: number; bodyTop: number; bodyHeight: number; color: string };

function candleDiagram(...values: [open: number, close: number, high: number, low: number][]): CandleDrawing[] {
  const centers = values.length === 1 ? [50] : values.length === 2 ? [36, 64] : values.length === 3 ? [20, 50, 80] : values.map((_, index) => 12 + (76 * index) / (values.length - 1));
  return values.map(([open, close, high, low], index) => ({
    x: centers[index], open, close, high, low,
    bodyTop: Math.min(open, close),
    bodyHeight: Math.max(Math.abs(close - open), 2),
    color: Math.abs(close - open) <= 1.5 ? '#8070b5' : close < open ? '#438c6a' : '#c45b4b'
  }));
}

const KNOWLEDGE_DIAGRAMS: Record<string, CandleDrawing[]> = {
  'Doji': candleDiagram([35, 35.8, 12, 58]),
  'Long-Legged Doji': candleDiagram([35, 35.8, 8, 61]),
  'Cross Doji': candleDiagram([35, 35.8, 14, 57]),
  'Hammer': candleDiagram([23, 28, 17, 59]),
  'Hanging Man': candleDiagram([23, 28, 17, 59]),
  'Inverted Hammer': candleDiagram([51, 46, 12, 56]),
  'Shooting Star': candleDiagram([51, 46, 12, 56]),
  'Bullish Marubozu': candleDiagram([48, 16, 16, 48]),
  'Bearish Marubozu': candleDiagram([16, 48, 16, 48]),
  'Opening and Closing Marubozu Variants': candleDiagram([48, 16, 16, 46]),
  'Spinning Top': candleDiagram([32, 35, 12, 58]),
  'Bullish Engulfing': candleDiagram([22, 43, 14, 51], [48, 19, 15, 54]),
  'Bearish Engulfing': candleDiagram([43, 22, 14, 51], [17, 48, 11, 54]),
  'Piercing Line': candleDiagram([18, 43, 12, 47], [54, 27, 26, 59]),
  'Piercing Pattern (Piercing Line)': candleDiagram([18, 43, 12, 47], [54, 27, 26, 59]),
  'Dark Cloud Cover': candleDiagram([43, 18, 12, 47], [26, 53, 9, 59]),
  'Bullish Harami': candleDiagram([17, 48, 12, 53], [38, 29, 25, 43]),
  'Bearish Harami': candleDiagram([48, 17, 12, 53], [29, 38, 25, 43]),
  'Morning Star': candleDiagram([15, 38, 10, 42], [32, 34, 27, 40], [43, 19, 16, 50]),
  'Evening Star': candleDiagram([42, 19, 10, 48], [29, 27, 25, 34], [17, 43, 10, 50]),
  'Bullish Abandoned Baby': candleDiagram([15, 38, 10, 42], [32, 33, 28, 38], [43, 19, 16, 50]),
  'Bearish Abandoned Baby': candleDiagram([42, 19, 10, 48], [29, 28, 25, 35], [17, 43, 10, 50]),
  'Three White Soldiers': candleDiagram([49, 37, 33, 55], [43, 29, 25, 49], [35, 19, 15, 43]),
  'Three Black Crows': candleDiagram([20, 34, 13, 43], [27, 42, 19, 49], [35, 51, 27, 57]),
  'Rising Three Methods': candleDiagram([49, 25, 22, 52], [31, 37, 28, 42], [34, 40, 30, 44], [38, 43, 34, 47], [48, 18, 15, 51]),
  'Falling Three Methods': candleDiagram([18, 42, 15, 48], [36, 30, 27, 40], [39, 33, 30, 43], [42, 37, 33, 46], [20, 49, 17, 53])
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
  imports: [CommonModule, DrishtiDashboardComponent],
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
  activeTab: 'dashboard' | 'knowledge' | 'drishti' = 'dashboard';
  readonly knowledgePatterns: KnowledgePattern[] = [
    { name: 'Doji', family: 'One candle', bias: 'Neutral', candles: '1 candle', description: 'Open and close are nearly equal, leaving a very small real body. It shows indecision for that candle.', rule: 'Body is at most 10% of the full high-to-low range.' },
    { name: 'Long-Legged Doji', family: 'One candle', bias: 'Neutral / indecision', candles: '1 candle after a strong move', description: 'A tiny body sits between long upper and lower shadows. Price moved widely in both directions, then closed near its open.', rule: 'Body is at most 10% of range; upper and lower shadows are each at least 30% of range. Look for context and a later candle to establish direction.' },
    { name: 'Cross Doji', family: 'One candle', bias: 'Neutral', candles: '1 candle', description: 'A cross-like Doji has nearly equal open and close with relatively balanced shadows. It marks indecision; nearby levels and the next move add context.', rule: 'Body is at most 10% of range; upper and lower shadow lengths differ by no more than 15% of range.' },
    { name: 'Hammer', family: 'One candle', bias: 'Bullish candidate', candles: '1 candle after a decline', description: 'A small body sits near the high with a long lower shadow. Sellers pushed price down, but it recovered before the close.', rule: 'Body is at most 35% of range; lower shadow is at least twice the body and 55% of range; upper shadow is at most 25%; prior three-candle move is down.' },
    { name: 'Hanging Man', family: 'One candle', bias: 'Bearish candidate', candles: '1 candle after a rise', description: 'It has the same shape as a Hammer, but appears after a rise. The long lower shadow signals selling pressure during the candle.', rule: 'Hammer shape with a positive prior three-candle move.' },
    { name: 'Inverted Hammer', family: 'One candle', bias: 'Bullish candidate', candles: '1 candle after a decline', description: 'A small body sits near the low with a long upper shadow. Buyers pushed price up intrabar; the following price action matters for confirmation.', rule: 'Body is at most 35% of range; upper shadow is at least twice the body and 55% of range; lower shadow is at most 25%; prior three-candle move is down.' },
    { name: 'Shooting Star', family: 'One candle', bias: 'Bearish candidate', candles: '1 candle after a rise', description: 'It has the same shape as an Inverted Hammer, but appears after a rise. The long upper shadow shows rejection of higher prices.', rule: 'Inverted Hammer shape with a positive prior three-candle move.' },
    { name: 'Bullish Marubozu', family: 'One candle', bias: 'Bullish momentum', candles: '1 candle', description: 'A strong bullish candle opens near its low and closes near its high, showing directional buying pressure during the candle.', rule: 'Close is above open; upper and lower shadows are each at most 10% of range. Treat as context-dependent momentum, especially after a breakout or during a trend.' },
    { name: 'Bearish Marubozu', family: 'One candle', bias: 'Bearish momentum', candles: '1 candle', description: 'A strong bearish candle opens near its high and closes near its low, showing directional selling pressure during the candle.', rule: 'Close is below open; upper and lower shadows are each at most 10% of range. Compare with the trend, nearby levels, and recent volume.' },
    { name: 'Opening and Closing Marubozu Variants', family: 'One candle', bias: 'Directional', candles: '1 candle', description: 'These variants have one very small shadow and one more visible shadow. The small shadow identifies the opening or closing extreme.', rule: 'Bullish opening: tiny lower shadow; bullish closing: tiny upper shadow. Bearish opening: tiny upper shadow; bearish closing: tiny lower shadow. The opposite shadow remains more visible.' },
    { name: 'Spinning Top', family: 'One candle', bias: 'Indecision', candles: '1 candle', description: 'A small body with visible shadows on both sides shows that buyers and sellers both moved price without a decisive close.', rule: 'Body is at most 30% of range; upper and lower shadows are each longer than the body. After a trend it may mark a pause; inside a range it may be noise.' },
    { name: 'Bullish Engulfing', family: 'Two candles', bias: 'Bullish candidate', candles: '2 candles after a decline', description: 'A bullish candle’s body covers the previous bearish candle’s body, suggesting buyers overwhelmed the prior session’s move.', rule: 'Previous candle bearish; current candle bullish and its body fully engulfs the previous body; current body is larger; prior move is down.' },
    { name: 'Bearish Engulfing', family: 'Two candles', bias: 'Bearish candidate', candles: '2 candles after a rise', description: 'A bearish candle’s body covers the previous bullish candle’s body, suggesting sellers overwhelmed the prior session’s move.', rule: 'Previous candle bullish; current candle bearish and its body fully engulfs the previous body; current body is larger; prior move is up.' },
    { name: 'Piercing Pattern (Piercing Line)', family: 'Two candles', bias: 'Bullish candidate', candles: '2 candles after a decline', description: 'A bearish candle is followed by a bullish candle that opens below the prior low and closes above the prior body’s midpoint, but below its open.', rule: 'Prior candle bearish; current bullish; open below prior low; close above prior midpoint but below prior open; prior move is down.' },
    { name: 'Dark Cloud Cover', family: 'Two candles', bias: 'Bearish candidate', candles: '2 candles after a rise', description: 'A bullish candle is followed by a bearish candle that opens above the prior high and closes below the prior body’s midpoint, but above its open.', rule: 'Prior candle bullish; current bearish; open above prior high; close below prior midpoint but above prior open; prior move is up.' },
    { name: 'Bullish Harami', family: 'Two candles', bias: 'Bullish candidate', candles: '2 candles after a decline', description: 'The second candle’s real body fits inside the first candle’s larger bearish body. It can suggest that downward momentum is easing.', rule: 'Prior candle bearish; current real body is inside prior real body; prior move is down.' },
    { name: 'Bearish Harami', family: 'Two candles', bias: 'Bearish candidate', candles: '2 candles after a rise', description: 'The second candle’s real body fits inside the first candle’s larger bullish body. It can suggest that upward momentum is easing.', rule: 'Prior candle bullish; current real body is inside prior real body; prior move is up.' },
    { name: 'Morning Star', family: 'Three candles', bias: 'Bullish candidate', candles: '3 candles after a decline', description: 'A bearish candle is followed by a small-bodied pause and then a bullish candle that closes above the first candle’s midpoint.', rule: 'First candle bearish; middle body at most 35% of its range; third candle bullish and closes above the first candle midpoint; prior move is down.' },
    { name: 'Evening Star', family: 'Three candles', bias: 'Bearish candidate', candles: '3 candles after a rise', description: 'A bullish candle is followed by a small-bodied pause and then a bearish candle that closes below the first candle’s midpoint.', rule: 'First candle bullish; middle body at most 35% of its range; third candle bearish and closes below the first candle midpoint; prior move is up.' },
    { name: 'Bullish Abandoned Baby', family: 'Three candles', bias: 'Bullish candidate', candles: '3 candles after a decline; gaps required', description: 'A bearish candle is followed by an isolated Doji below it, then a bullish candle that gaps above the Doji. The gaps are central to the classic pattern.', rule: 'First candle bearish; middle Doji range gaps below candle 1; third candle bullish and its range gaps above the Doji. Rare on many intraday markets; confirm the gaps and data.' },
    { name: 'Bearish Abandoned Baby', family: 'Three candles', bias: 'Bearish candidate', candles: '3 candles after a rise; gaps required', description: 'A bullish candle is followed by an isolated Doji above it, then a bearish candle that gaps below the Doji. The gaps are central to the classic pattern.', rule: 'First candle bullish; middle Doji range gaps above candle 1; third candle bearish and its range gaps below the Doji. Rare on many intraday markets; confirm the gaps and data.' },
    { name: 'Three White Soldiers', family: 'Three candles', bias: 'Bullish pattern', candles: '3 candles', description: 'Three consecutive bullish candles with substantial bodies and successively higher closes show sustained buying during those candles.', rule: 'All three candles bullish; each body is at least 55% of its range; closes rise consecutively.' },
    { name: 'Three Black Crows', family: 'Three candles', bias: 'Bearish pattern', candles: '3 candles', description: 'Three consecutive bearish candles with substantial bodies and successively lower closes show sustained selling during those candles.', rule: 'All three candles bearish; each body is at least 55% of its range; closes fall consecutively.' },
    { name: 'Rising Three Methods', family: 'Continuation', bias: 'Bullish continuation', candles: '5 candles in an uptrend', description: 'A long bullish candle is followed by smaller bearish candles contained within its range, then another bullish candle resumes the move.', rule: 'Candle 1 bullish and long; candles 2–4 smaller and contained in candle 1 range; candle 5 bullish and closes above candle 1 close. A break below candle 1 low weakens the setup.' },
    { name: 'Falling Three Methods', family: 'Continuation', bias: 'Bearish continuation', candles: '5 candles in a downtrend', description: 'A long bearish candle is followed by smaller bullish candles contained within its range, then another bearish candle resumes the move.', rule: 'Candle 1 bearish and long; candles 2–4 smaller and contained in candle 1 range; candle 5 bearish and closes below candle 1 close. A break above candle 1 high weakens the setup.' }
  ];
  readonly knowledgeFamilies = ['One candle', 'Two candles', 'Three candles', 'Continuation'];
  selectedKnowledgeChapter = 'One candle';
  readonly fibonacciKnowledgeChapter = 'Fibonacci Retracement';
  readonly cprKnowledgeChapter = 'Central Pivot Range (CPR)';
  private knowledgeScrollScheduled = false;
  readonly knowledgePatternsByFamily: Record<string, KnowledgePattern[]> = {
    'One candle': this.knowledgePatterns.filter((pattern) => pattern.family === 'One candle'),
    'Two candles': this.knowledgePatterns.filter((pattern) => pattern.family === 'Two candles'),
    'Three candles': this.knowledgePatterns.filter((pattern) => pattern.family === 'Three candles'),
    'Continuation': this.knowledgePatterns.filter((pattern) => pattern.family === 'Continuation')
  };
  readonly fibonacciLevels = [
    { ratio: 0, percent: '0%', description: 'End of the selected swing' },
    { ratio: 0.236, percent: '23.6%', description: 'Shallow retracement reference' },
    { ratio: 0.382, percent: '38.2%', description: 'Common retracement reference' },
    { ratio: 0.5, percent: '50%', description: 'Midpoint reference; not a Fibonacci ratio' },
    { ratio: 0.618, percent: '61.8%', description: 'Golden-ratio retracement reference' },
    { ratio: 0.786, percent: '78.6%', description: 'Deeper retracement reference' },
    { ratio: 1, percent: '100%', description: 'Start of the selected swing' }
  ];
  fibonacciSummary?: FibonacciSummary;

  patternsFor(family: string): KnowledgePattern[] {
    return this.knowledgePatternsByFamily[family] ?? [];
  }

  knowledgeChapterTitle(family: string): string {
    const titles: Record<string, string> = {
      'One candle': 'One-Candle Patterns',
      'Two candles': 'Two-Candle Patterns',
      'Three candles': 'Three-Candle Patterns',
      'Continuation': 'Continuation Patterns',
      'Fibonacci Retracement': 'Fibonacci Retracement'
    };
    return titles[family] ?? family;
  }

  selectKnowledgeChapter(family: string): void {
    this.selectedKnowledgeChapter = family;
    requestAnimationFrame(() => document.getElementById(this.knowledgeChapterId(family))?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }

  @HostListener('window:scroll')
  syncKnowledgeChapterToScroll(): void {
    if (this.activeTab !== 'knowledge' || this.knowledgeScrollScheduled) return;
    this.knowledgeScrollScheduled = true;
    requestAnimationFrame(() => {
      this.knowledgeScrollScheduled = false;
      const chapters = [...this.knowledgeFamilies, this.fibonacciKnowledgeChapter, this.cprKnowledgeChapter];
      let activeChapter = chapters[0];
      for (const chapter of chapters) {
        const section = document.getElementById(this.knowledgeChapterId(chapter));
        if (section && section.getBoundingClientRect().top <= 120) activeChapter = chapter;
      }
      this.selectedKnowledgeChapter = activeChapter;
    });
  }

  knowledgeChapterId(family: string): string {
    return `knowledge-${family.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  }

  patternDiagram(name: string): CandleDrawing[] {
    return KNOWLEDGE_DIAGRAMS[name] ?? [];
  }

  @ViewChild('chart') private chart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('historyChart') private historyChart?: ElementRef<HTMLDivElement>;
  @ViewChild('historyChartWrap') private historyChartWrap?: ElementRef<HTMLDivElement>;
  @ViewChild('studyPanelGroup') private studyPanelGroup?: ElementRef<HTMLDivElement>;

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
  historySearchText = 'NIFTY 50';
  historyMarket: 'cash' | 'commodities' = 'cash';
  historySearchResults: Instrument[] = [];
  historySearchMessage = '';
  historySearchOpen = false;
  selectedHistoryInstrument?: Instrument = { key: 'NSE_INDEX|Nifty 50', symbol: 'NIFTY 50', name: 'Nifty 50', exchange: 'NSE_INDEX' };
  historicalFrom = dateInputValue(new Date(Date.now() - 400 * 24 * 60 * 60 * 1000));
  historicalTo = dateInputValue(new Date());
  historicalInterval = 'days:1';
  loadedHistoricalInterval = 'days:1';
  historicalCandles: HistoricalCandle[] = [];
  displayedCandles: HistoricalCandle[] = [];
  historicalLoading = false;
  chartIsFullscreen = false;

  fullscreenChart = true;
  technicalSnapshot?: TechnicalSnapshot;
  companyProfile?: CompanyProfile;
  corporateActions: CorporateAction[] = [];
  fundamentalsLoading = false;
  riskBudget = 0;
  plannerInstrumentType: 'underlying' | 'option' = 'underlying';
  plannerOptionType: 'call' | 'put' = 'call';
  plannerExpiryMonth = '';
  plannerLotSize = 1;
  plannerEntry = 0;
  plannerManualStop = 0;
  plannerStopMethod: 'swing' | 'atr' | 'ema20' | 'manual' = 'swing';
  targetRMultiple = 2;
  riskDirection: 'long' | 'short' | '' = '';
  movingAveragesEnabled = true;
  movingAverageOpacity = 100;
  ghostRiderEnabled = false;
  ghostRiderAtrMultiplier = 1.5;
  ghostRiderSnapshot?: GhostRiderSnapshot;
  ghostRiderVisibility: Record<GhostRiderVisibilityKey, boolean> = {
    ema9: true, ema21: true, vwap: true, signals: true, dashboard: true,
    entry: true, stop: true, tp1: true, tp2: true, tp3: true, tp4: true, tp5: true
  };
  tradersGitaIdentifierEnabled = false;
  tradersGitaConfirmedOnly = true;
  tradersGitaShowTrendNames = true;
  tradersGitaGroups: Record<TraderGitaPatternGroup, boolean> = { single: true, two: true, three: true, continuation: true };
  tradersGitaSettings: Record<TraderGitaPatternSetting, number> = {
    dojiPct: 0.10, smallBodyPct: 0.30, longBodyMult: 1.2, wickBodyMult: 2, tinyWickPct: 0.10,
    avgBodyLen: 14, trendLen: 5, tweezerTicks: 5
  };
  readonly studies: Record<StudyName, boolean> = {
    sma20: false,
    sma50: false,
    ema9: true,
    ema20: true,
    ema50: true,
    ema200: true,
    bollinger: false,
    rsi: false,
    macd: false,
    supportResistance: false,
    patterns: false,
    fibonacci: false,
    emaSignal: true
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
  private analysisPriceLines: IPriceLine[] = [];
  private ghostRiderPriceLines: IPriceLine[] = [];
  private trendlineStart?: TrendlinePoint;

  ngOnInit(): void {
    this.updateClock();
    this.clockTimer = window.setInterval(() => this.updateClock(), 1000);
    this.api.status().subscribe({
      next: (status) => {
        this.configured = status.configured;
        this.setConnected(status.connected);
      },
      error: () => this.showToast("Could not reach the Trader's Gita data service.")
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
      this.resizeObserver = new ResizeObserver(() => this.drawChart());
      this.resizeObserver.observe(this.chart.nativeElement);
    }
    this.initializeAnalysisCharts();
    this.drawChart();
    if (this.historicalCandles.length) this.drawHistoryChart();
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
  get analysisMode(): boolean { return this.fullscreenChart && this.activeTab === 'dashboard'; }
  get modernInterface(): boolean { return this.fullscreenChart || this.activeTab === 'knowledge' || this.activeTab === 'drishti'; }
  get activeMovingAverageCount(): number { return [this.studies.sma20, this.studies.sma50, this.studies.ema9, this.studies.ema20, this.studies.ema50, this.studies.ema200].filter(Boolean).length; }
  openSelectedChart(): void {
    this.closeStudyPanels();
    this.fullscreenChart = true;
    this.activeTab = 'dashboard';
  }

  openKnowledge(): void {
    this.closeStudyPanels();
    this.activeTab = 'knowledge';
  }

  openDrishti(): void {
    this.closeStudyPanels();
    this.activeTab = 'drishti';
  }

  private closeStudyPanels(): void {
    this.studyPanelGroup?.nativeElement.querySelectorAll<HTMLDetailsElement>(':scope > details.moving-average-menu').forEach((panel) => { panel.open = false; });
  }
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
    const wasConnected = this.connected;
    this.connected = connected;
    this.marketLabel = connected ? 'Live data connected' : 'Awaiting connection';
    this.refreshSubscription?.unsubscribe();
    if (connected) {
      this.updatedTime = 'LIVE QUOTES';
      if (!wasConnected && this.selectedHistoryInstrument) this.loadHistorical();
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
    this.historicalCandles = [];
    this.displayedCandles = [];
    this.technicalSnapshot = undefined;
    this.selectedHistoryInstrument = instrument;
    this.historySearchText = `${instrument.symbol} · ${instrument.exchange}`;
    this.historySearchOpen = false;
    this.historySearchResults = [];
    this.riskDirection = '';
    this.plannerEntry = 0;
    this.plannerManualStop = 0;
    this.loadEquityFundamentals(instrument);
    this.loadHistorical();
  }

  setHistoryMarket(market: 'cash' | 'commodities'): void {
    this.historyMarket = market;
    this.historySearchText = '';
    this.historySearchResults = [];
    this.historySearchOpen = false;
    this.selectedHistoryInstrument = market === 'cash' ? { key: 'NSE_INDEX|Nifty 50', symbol: 'NIFTY 50', name: 'Nifty 50', exchange: 'NSE_INDEX' } : undefined;
    this.historySearchText = market === 'cash' ? 'NIFTY 50' : '';
    this.historicalCandles = [];
    this.displayedCandles = [];
    this.technicalSnapshot = undefined;
    this.companyProfile = undefined;
    this.corporateActions = [];
    this.riskDirection = '';
    this.plannerEntry = 0;
    this.plannerManualStop = 0;
    this.drawHistoryChart();
    if (this.connected && market === 'cash') { this.loadHistorical(); }
  }

  loadHistorical(): void {
    if (!this.selectedHistoryInstrument || !this.historicalFrom || !this.historicalTo) return;
    if (this.historicalFrom > this.historicalTo) {
      this.showToast('The start date must be on or before the end date.');
      return;
    }
    if (!this.connected) return;
    this.historicalLoading = true;
    this.historicalCandles = [];
    this.displayedCandles = [];
    this.technicalSnapshot = undefined;
    const requestedInterval = this.historicalInterval;
    const [unit, intervalValue] = requestedInterval.split(':');
    this.api.historical(
      this.selectedHistoryInstrument.key,
      unit,
      Number(intervalValue),
      this.historicalFrom,
      this.historicalTo
    ).subscribe({
      next: (result) => {
        this.loadedHistoricalInterval = requestedInterval;
        this.historicalCandles = result.candles;
        this.displayedCandles = [...result.candles].reverse().slice(0, 100);
        this.technicalSnapshot = this.calculateTechnicalSnapshot(result.candles);
        this.historicalLoading = false;
        this.fullscreenChart = true;
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

  async toggleChartFullscreen(): Promise<void> {
    const chart = this.historyChartWrap?.nativeElement;
    if (!chart) return;
    try {
      if (document.fullscreenElement === chart) await document.exitFullscreen();
      else {
        if (document.fullscreenElement) await document.exitFullscreen();
        await chart.requestFullscreen();
      }
    } catch {
      this.showToast('Full-screen mode is not available in this browser.');
    }
  }

  @HostListener('document:fullscreenchange')
  onFullscreenChange(): void {
    this.chartIsFullscreen = document.fullscreenElement === this.historyChartWrap?.nativeElement;
    requestAnimationFrame(() => this.drawHistoryChart());
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
    return `This view uses ${this.loadedHistoricalIntervalLabel} candles over ${this.historicalFrom} to ${this.historicalTo}. That describes the data interval, not a recommended holding period.`;
  }

  get historicalIntervalLabel(): string {
    const [unit, interval] = this.historicalInterval.split(':');
    const names: Record<string, string> = { minutes: 'minute', hours: 'hour', days: 'day', weeks: 'week', months: 'month' };
    return `${interval} ${names[unit] || unit}${Number(interval) > 1 ? 's' : ''}`;
  }

  get loadedHistoricalIntervalLabel(): string {
    const [unit, interval] = this.loadedHistoricalInterval.split(':');
    const label = unit === 'minutes' ? 'minute' : unit === 'hours' ? 'hour' : unit === 'weeks' ? 'week' : unit === 'months' ? 'month' : 'day';
    return `${interval} ${label}${interval === '1' ? '' : 's'}`;
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
    if (!snapshot || !this.selectedHistoryInstrument || !this.riskDirection) return undefined;
    const entryPrice = this.plannerEntry > 0 ? this.plannerEntry : snapshot.lastClose;
    const direction = this.riskDirection === 'long' ? 1 : -1;
    const buffer = (snapshot.atr || 0) * 0.1;
    const stopPrice = this.plannerStopMethod === 'manual'
      ? this.plannerManualStop
      : this.plannerStopMethod === 'atr'
        ? entryPrice - direction * (snapshot.atr || 0) * 1.5
        : this.plannerStopMethod === 'ema20'
          ? (snapshot.ema20 || entryPrice) - direction * buffer
          : this.riskDirection === 'long' ? snapshot.lowestLow20 - buffer : snapshot.highestHigh20 + buffer;
    const riskPerUnit = Math.abs(entryPrice - stopPrice);
    if (!stopPrice || !riskPerUnit || (this.riskDirection === 'long' ? stopPrice >= entryPrice : stopPrice <= entryPrice)) return undefined;
    const defaultLotSize = this.historyMarket === 'commodities' ? Math.max(1, this.selectedHistoryInstrument.lot_size || 1) : 1;
    const lotSize = Math.max(1, Math.floor(this.plannerLotSize || defaultLotSize));
    const riskPerLot = riskPerUnit * lotSize;
    const lots = this.riskBudget > 0 ? Math.floor(this.riskBudget / riskPerLot) : 0;
    const units = lots * lotSize;
    return {
      lots,
      units,
      riskPerUnit,
      riskUsed: units * riskPerUnit,
      entryPrice,
      stopPrice,
      targetPrice: entryPrice + direction * riskPerUnit * this.targetRMultiple
    };
  }

  get emaChecklist(): { label: string; complete: boolean }[] {
    const s = this.technicalSnapshot;
    if (!s) return [];
    return [
      { label: 'Price above EMA 200', complete: s.ema200 !== undefined && s.lastClose > s.ema200 },
      { label: 'EMA 9 > EMA 20 > EMA 50', complete: s.ema9 !== undefined && s.ema20 !== undefined && s.ema50 !== undefined && s.ema9 > s.ema20 && s.ema20 > s.ema50 },
      { label: 'EMA 20 and EMA 50 rising', complete: s.ema20Rising && s.ema50Rising },
      { label: 'Pullback near EMA 20 or EMA 50', complete: s.pullbackNearEma },
      { label: 'Bullish rejection closes above prior high', complete: s.breaksRejectionHigh }
    ];
  }

  get emaChecklistCount(): number {
    return this.emaChecklist.filter((item) => item.complete).length;
  }

  setRiskBudget(value: string): void {
    this.riskBudget = Math.max(0, Number(value) || 0);
    this.refreshTradePlan();
  }

  setTargetRMultiple(value: string): void {
    this.targetRMultiple = Math.min(5, Math.max(0.5, Number(value) || 2));
    this.refreshTradePlan();
  }

  setRiskDirection(direction: 'long' | 'short'): void {
    this.riskDirection = direction;
    this.refreshTradePlan();
  }

  setPlannerStopMethod(method: 'swing' | 'atr' | 'ema20' | 'manual'): void {
    this.plannerStopMethod = method;
    this.refreshTradePlan();
  }

  refreshTradePlan(): void {
    this.drawHistoryChart();
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
    const ema9Values = closes.length >= 9 ? EMA.calculate({ period: 9, values: closes }) : [];
    const ema20Values = closes.length >= 20 ? EMA.calculate({ period: 20, values: closes }) : [];
    const ema50Values = closes.length >= 50 ? EMA.calculate({ period: 50, values: closes }) : [];
    const ema200Values = closes.length >= 200 ? EMA.calculate({ period: 200, values: closes }) : [];
    const rsiValues = closes.length >= 15 ? RSI.calculate({ period: 14, values: closes }) : [];
    const adx = adxValues.at(-1);
    const atr = atrValues.at(-1);
    const ema9 = ema9Values.at(-1);
    const ema20 = ema20Values.at(-1);
    const ema50 = ema50Values.at(-1);
    const ema200 = ema200Values.at(-1);
    const previousEma9 = ema9Values.at(-2);
    const previousEma20 = ema20Values.at(-2);
    const previousEma50 = ema50Values.at(-2);
    const previousEma200 = ema200Values.at(-2);
    const setup = ema9 !== undefined && ema20 !== undefined && ema50 !== undefined && ema200 !== undefined && latestClose > ema9 && ema9 > ema20 && ema20 > ema50 && ema50 > ema200;
    const previousSetup = previousEma9 !== undefined && previousEma20 !== undefined && previousEma50 !== undefined && previousEma200 !== undefined && closes.at(-2)! > previousEma9 && previousEma9 > previousEma20 && previousEma20 > previousEma50 && previousEma50 > previousEma200;
    const emaAlignment = ema200 === undefined ? 'Needs 200 candles' : setup ? 'Bullish' : latestClose < ema9! && ema9! < ema20! && ema20! < ema50! && ema50! < ema200! ? 'Bearish' : 'Mixed';
    const last = candles.at(-1)!;
    const prior = candles.at(-2)!;
    const ema20Rising = ema20 !== undefined && previousEma20 !== undefined && ema20 > previousEma20;
    const ema50Rising = ema50 !== undefined && previousEma50 !== undefined && ema50 > previousEma50;
    const pullbackTolerance = (atr || latestClose * 0.005) * 0.5;
    const pullbackNearEma = ema20 !== undefined && ema50 !== undefined && ((last.low <= ema20 + pullbackTolerance && last.close >= ema20 - pullbackTolerance) || (last.low <= ema50 + pullbackTolerance && last.close >= ema50 - pullbackTolerance));
    const bullishRejection = pullbackNearEma && last.close > last.open && last.close >= (ema20 || last.close);
    const breaksRejectionHigh = bullishRejection && last.close > prior.high;
    const bullishCrossover = ema9 !== undefined && ema20 !== undefined && previousEma9 !== undefined && previousEma20 !== undefined && previousEma9 <= previousEma20 && ema9 > ema20 && latestClose > ema9 && latestClose > ema20 && (ema50Rising || latestClose > (ema50 || latestClose));
    const bearishCrossover = ema9 !== undefined && ema20 !== undefined && previousEma9 !== undefined && previousEma20 !== undefined && previousEma9 >= previousEma20 && ema9 < ema20 && latestClose < ema9 && latestClose < ema20 && (!ema50Rising || latestClose < (ema50 || latestClose));
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
      ema9, ema20, ema50, ema200, emaAlignment, bullishSetup: setup, bullishEntry: setup && !previousSetup,
      bullishCrossover, bearishCrossover, ema20Rising, ema50Rising, pullbackNearEma, bullishRejection, breaksRejectionHigh,
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

  setMovingAveragesEnabled(enabled: boolean): void {
    this.movingAveragesEnabled = enabled;
    this.drawHistoryChart();
  }

  setMovingAverageOpacity(value: string): void {
    this.movingAverageOpacity = Math.min(100, Math.max(10, Number(value) || 10));
    this.drawHistoryChart();
  }

  private movingAverageColor(hex: string): string {
    const value = hex.replace('#', '');
    const red = parseInt(value.slice(0, 2), 16);
    const green = parseInt(value.slice(2, 4), 16);
    const blue = parseInt(value.slice(4, 6), 16);
    return `rgba(${red}, ${green}, ${blue}, ${this.movingAverageOpacity / 100})`;
  }

  setGhostRiderEnabled(enabled: boolean): void {
    this.ghostRiderEnabled = enabled;
    this.drawHistoryChart();
  }

  setGhostRiderAtrMultiplier(value: string): void {
    this.ghostRiderAtrMultiplier = Math.min(5, Math.max(0.1, Number(value) || 1.5));
    this.drawHistoryChart();
  }

  setGhostRiderVisibility(key: GhostRiderVisibilityKey, visible: boolean): void {
    this.ghostRiderVisibility = { ...this.ghostRiderVisibility, [key]: visible };
    this.drawHistoryChart();
  }

  setTradersGitaIdentifierEnabled(enabled: boolean): void {
    this.tradersGitaIdentifierEnabled = enabled;
    this.drawHistoryChart();
  }

  setTradersGitaGroup(group: TraderGitaPatternGroup, enabled: boolean): void {
    this.tradersGitaGroups = { ...this.tradersGitaGroups, [group]: enabled };
    this.drawHistoryChart();
  }

  setTradersGitaSetting(key: TraderGitaPatternSetting, value: string): void {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;
    const bounds: Record<TraderGitaPatternSetting, [number, number]> = {
      dojiPct: [0.01, 0.5], smallBodyPct: [0.05, 0.8], longBodyMult: [0.5, 3], wickBodyMult: [1, 5],
      tinyWickPct: [0.01, 0.4], avgBodyLen: [3, 100], trendLen: [2, 50], tweezerTicks: [0, 100]
    };
    const [minimum, maximum] = bounds[key];
    const bounded = Math.min(maximum, Math.max(minimum, parsed));
    this.tradersGitaSettings = { ...this.tradersGitaSettings, [key]: key === 'avgBodyLen' || key === 'trendLen' || key === 'tweezerTicks' ? Math.round(bounded) : bounded };
    this.drawHistoryChart();
  }

  setTradersGitaConfirmedOnly(confirmedOnly: boolean): void {
    this.tradersGitaConfirmedOnly = confirmedOnly;
    this.drawHistoryChart();
  }

  setTradersGitaShowTrendNames(showTrendNames: boolean): void {
    this.tradersGitaShowTrendNames = showTrendNames;
    this.drawHistoryChart();
  }

  private calculateGhostRider(candles: HistoricalCandle[], times: Time[]): GhostRiderResult | undefined {
    if (candles.length < 35) return undefined;
    const closes = candles.map((c) => c.close);
    const e9Values = EMA.calculate({ period: 9, values: closes });
    const e21Values = EMA.calculate({ period: 21, values: closes });
    const rsiValues = RSI.calculate({ period: 14, values: closes });
    const atrValues = ATR.calculate({ high: candles.map(c => c.high), low: candles.map(c => c.low), close: closes, period: 14 });
    const adxValues = ADX.calculate({ high: candles.map(c => c.high), low: candles.map(c => c.low), close: closes, period: 14 });
    const macdValues = MACD.calculate({ values: closes, fastPeriod: 12, slowPeriod: 26, signalPeriod: 9, SimpleMAOscillator: false, SimpleMASignal: false });
    const volumeAverageValues = SMA.calculate({ period: 20, values: candles.map(c => c.volume) });
    const align = (values: number[]): (number | undefined)[] => [...Array(Math.max(0, candles.length - values.length)).fill(undefined), ...values];
    const e9 = align(e9Values);
    const e21 = align(e21Values);
    const rsi = align(rsiValues);
    const atr = align(atrValues);
    const adx = align(adxValues.map(value => value.adx));
    const volAvg = align(volumeAverageValues);
    const macd = [...Array(Math.max(0, candles.length - macdValues.length)).fill(undefined), ...macdValues.map(value => value.MACD)];
    const macdSignal = [...Array(Math.max(0, candles.length - macdValues.length)).fill(undefined), ...macdValues.map(value => value.signal)];

    let session = '';
    let sessionPV = 0;
    let sessionVolume = 0;
    const vwap: (number | undefined)[] = candles.map(candle => {
      const day = candle.timestamp.slice(0, 10);
      if (day !== session) { session = day; sessionPV = 0; sessionVolume = 0; }
      const typical = (candle.high + candle.low + candle.close) / 3;
      sessionPV += typical * candle.volume;
      sessionVolume += candle.volume;
      return sessionVolume ? sessionPV / sessionVolume : undefined;
    });

    let rsi5m: number | undefined;
    if (this.loadedHistoricalInterval === 'minutes:5') {
      rsi5m = RSI.calculate({ period: 14, values: closes }).at(-1);
    } else if (this.loadedHistoricalInterval === 'minutes:1') {
      const groups = new Map<number, number>();
      candles.forEach(candle => {
        const epoch = Date.parse(candle.timestamp);
        if (Number.isFinite(epoch)) groups.set(Math.floor(epoch / 300_000), candle.close);
      });
      const fiveMinuteCloses = [...groups.values()];
      if (fiveMinuteCloses.length >= 15) rsi5m = RSI.calculate({ period: 14, values: fiveMinuteCloses }).at(-1);
    }
    const scoreAvailable = rsi5m === undefined ? 6 : 7;
    let signalState: 'LONG' | 'SHORT' | 'WAIT' = 'WAIT';
    let entry: number | undefined;
    let stop: number | undefined;
    let targets: number[] = [];
    let targetHits = [false, false, false, false, false];
    let cross: GhostRiderSnapshot['cross'] = 'WAIT';
    const markers: PatternMarker[] = [];
    const candleColors: (string | undefined)[] = Array(candles.length).fill(undefined);

    for (let i = 1; i < candles.length; i++) {
      const previous9 = e9[i - 1], previous21 = e21[i - 1], current9 = e9[i], current21 = e21[i];
      const crossUp = previous9 !== undefined && previous21 !== undefined && current9 !== undefined && current21 !== undefined && previous9 <= previous21 && current9 > current21;
      const crossDown = previous9 !== undefined && previous21 !== undefined && current9 !== undefined && current21 !== undefined && previous9 >= previous21 && current9 < current21;
      const triggerBuy: boolean = crossUp && signalState !== 'LONG';
      const triggerSell: boolean = crossDown && signalState !== 'SHORT';
      if (triggerBuy || triggerSell) {
        signalState = triggerBuy ? 'LONG' : 'SHORT';
        cross = i === candles.length - 1 ? triggerBuy ? 'BUY' : 'SELL' : 'WAIT';
        entry = candles[i].close;
        const risk = (atr[i] || 0) * this.ghostRiderAtrMultiplier;
        stop = triggerBuy ? entry - risk : entry + risk;
        targets = Array.from({ length: 5 }, (_, index) => entry! + (triggerBuy ? 1 : -1) * risk * (index + 1));
        targetHits = [false, false, false, false, false];
        markers.push({ time: times[i], position: triggerBuy ? 'belowBar' : 'aboveBar', color: triggerBuy ? '#159447' : '#dc453f', shape: triggerBuy ? 'arrowUp' : 'arrowDown', text: triggerBuy ? 'GR BUY' : 'GR SELL', name: triggerBuy ? 'Ghost Rider buy' : 'Ghost Rider sell' });
        candleColors[i] = '#16191d';
      }
      if (signalState === 'LONG') targets.forEach((target, index) => { if (candles[i].high >= target) targetHits[index] = true; });
      if (signalState === 'SHORT') targets.forEach((target, index) => { if (candles[i].low <= target) targetHits[index] = true; });
      const retest = current9 !== undefined && current21 !== undefined && (signalState === 'LONG' && candles[i].low <= current9 && candles[i].low > current21 || signalState === 'SHORT' && candles[i].high >= current9 && candles[i].high < current21);
      if (retest && !markers.some(marker => marker.time === times[i])) candleColors[i] = '#f59e0b';
    }

    const lastIndex = candles.length - 1;
    const last = candles[lastIndex];
    const bullChecks = [last.close > (vwap[lastIndex] ?? Infinity), (rsi[lastIndex] ?? 0) > 50, (macd[lastIndex] ?? -Infinity) > (macdSignal[lastIndex] ?? Infinity), (e9[lastIndex] ?? -Infinity) > (e21[lastIndex] ?? Infinity), (adx[lastIndex] ?? 0) > 25 && last.close > (e9[lastIndex] ?? Infinity), last.volume > (volAvg[lastIndex] ?? Infinity) && last.close > last.open];
    const bearChecks = [last.close < (vwap[lastIndex] ?? -Infinity), (rsi[lastIndex] ?? Infinity) < 50, (macd[lastIndex] ?? Infinity) < (macdSignal[lastIndex] ?? -Infinity), (e9[lastIndex] ?? Infinity) < (e21[lastIndex] ?? -Infinity), (adx[lastIndex] ?? 0) > 25 && last.close < (e9[lastIndex] ?? -Infinity), last.volume > (volAvg[lastIndex] ?? Infinity) && last.close < last.open];
    if (rsi5m !== undefined) { bullChecks.push(rsi5m > 50); bearChecks.push(rsi5m < 50); }
    const bullScore = bullChecks.filter(Boolean).length;
    const bearScore = bearChecks.filter(Boolean).length;
    const bullPct = Math.round(bullScore / scoreAvailable * 100);
    const bearPct = Math.round(bearScore / scoreAvailable * 100);
    const diff = bullPct - bearPct;
    const bias = diff >= 40 ? 'STRONG BULL' : diff <= -40 ? 'STRONG BEAR' : bullPct > bearPct ? 'MILD BULL' : 'MILD BEAR';
    const isRetest = candleColors[lastIndex] === '#f59e0b';
    return {
      snapshot: {
        bullPct, bearPct, scoreTotal: bullScore, scoreAvailable, bias,
        closeAboveVwap: last.close > (vwap[lastIndex] ?? last.close), rsi: rsi[lastIndex] || 0, rsi5m,
        macdBullish: (macd[lastIndex] ?? 0) > (macdSignal[lastIndex] ?? 0), adx: adx[lastIndex] || 0,
        emaBullish: (e9[lastIndex] ?? 0) > (e21[lastIndex] ?? 0), atr: atr[lastIndex] || 0,
        volumeHigh: last.volume > (volAvg[lastIndex] ?? Infinity), cross, signal: signalState,
        entry, stop, targets, targetHits, retest: isRetest
      },
      ema9: e9, ema21: e21, vwap, markers, candleColors
    };
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
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350'
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
      layout: { background: { type: ColorType.Solid, color: '#0b0e11' }, textColor: '#848e9c', fontFamily: 'Manrope, sans-serif', fontSize: 10 },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      rightPriceScale: { borderColor: '#2b3139' },
      timeScale: { borderColor: '#2b3139', timeVisible: this.isIntraday(), secondsVisible: false },
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
    const unit = this.loadedHistoricalInterval.split(':')[0];
    const candles = [...this.historicalCandles].sort((left, right) => left.timestamp.localeCompare(right.timestamp));
    const times = candles.map((candle) => this.chartTime(candle.timestamp, unit));
    const ghostRider = this.ghostRiderEnabled ? this.calculateGhostRider(candles, times) : undefined;
    this.ghostRiderSnapshot = ghostRider?.snapshot;
    const tradersGitaMarkers = this.tradersGitaIdentifierEnabled ? this.detectTradersGitaMarkers(candles, times) : [];
    const candleData: CandlestickData<Time>[] = candles.map((candle, index) => ({
      time: times[index],
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
      color: ghostRider && this.ghostRiderVisibility.signals ? ghostRider.candleColors[index] : undefined,
      borderColor: ghostRider && this.ghostRiderVisibility.signals ? ghostRider.candleColors[index] : undefined,
      wickColor: ghostRider && this.ghostRiderVisibility.signals ? ghostRider.candleColors[index] : undefined
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
    if (ghostRider) {
      if (this.ghostRiderVisibility.ema9) this.addAlignedOverlay(ghostRider.ema9, times, 'Ghost Rider EMA 9', '#21a05a');
      if (this.ghostRiderVisibility.ema21) this.addAlignedOverlay(ghostRider.ema21, times, 'Ghost Rider EMA 21', '#df4e55');
      if (this.ghostRiderVisibility.vwap) this.addAlignedOverlay(ghostRider.vwap, times, 'Ghost Rider VWAP', '#7186ff');
    }
    if (this.movingAveragesEnabled && this.studies.sma20 && closes.length >= 20) {
      this.addOverlay(SMA.calculate({ period: 20, values: closes }), 19, times, 'SMA 20', this.movingAverageColor('#d18b35'));
    }
    if (this.movingAveragesEnabled && this.studies.sma50 && closes.length >= 50) {
      this.addOverlay(SMA.calculate({ period: 50, values: closes }), 49, times, 'SMA 50', this.movingAverageColor('#28744d'));
    }
    if (this.movingAveragesEnabled && this.studies.ema9 && closes.length >= 9) this.addOverlay(EMA.calculate({ period: 9, values: closes }), 8, times, 'EMA 9', this.movingAverageColor('#f0b90b'));
    if (this.movingAveragesEnabled && this.studies.ema20 && closes.length >= 20) this.addOverlay(EMA.calculate({ period: 20, values: closes }), 19, times, 'EMA 20', this.movingAverageColor('#2962ff'));
    if (this.movingAveragesEnabled && this.studies.ema50 && closes.length >= 50) this.addOverlay(EMA.calculate({ period: 50, values: closes }), 49, times, 'EMA 50', this.movingAverageColor('#26a69a'));
    if (this.movingAveragesEnabled && this.studies.ema200 && closes.length >= 200) this.addOverlay(EMA.calculate({ period: 200, values: closes }), 199, times, 'EMA 200', this.movingAverageColor('#e91e63'));
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
    if (this.studies.fibonacci) this.drawFibonacci(candles);
    if (this.studies.patterns) this.detectedPatterns = this.detectPatterns(candles, times);
    else this.detectedPatterns = [];
    const bullishEntryMarkers: PatternMarker[] = [];
    if (this.movingAveragesEnabled && this.studies.emaSignal && closes.length >= 200) {
      const e9 = EMA.calculate({ period: 9, values: closes });
      const e20 = EMA.calculate({ period: 20, values: closes });
      const e50 = EMA.calculate({ period: 50, values: closes });
      const e200 = EMA.calculate({ period: 200, values: closes });
      const offset = closes.length - e200.length;
      for (let index = 1; index < e200.length; index++) {
        const candleIndex = index + offset;
        const currentSetup = closes[candleIndex] > e9[candleIndex - 8] && e9[candleIndex - 8] > e20[candleIndex - 19] && e20[candleIndex - 19] > e50[candleIndex - 49] && e50[candleIndex - 49] > e200[index];
        const previousSetup = closes[candleIndex - 1] > e9[candleIndex - 9] && e9[candleIndex - 9] > e20[candleIndex - 20] && e20[candleIndex - 20] > e50[candleIndex - 50] && e50[candleIndex - 50] > e200[index - 1];
        if (currentSetup && !previousSetup) bullishEntryMarkers.push({ time: times[candleIndex], position: 'belowBar', color: '#16834a', shape: 'arrowUp', text: 'EMA BUY', name: 'EMA bullish entry' });
      }
    }
    if (this.candleSeries) {
      this.markerPlugin ??= createSeriesMarkers(this.candleSeries, []);
      this.markerPlugin.setMarkers([...this.detectedPatterns, ...bullishEntryMarkers, ...tradersGitaMarkers, ...(ghostRider && this.ghostRiderVisibility.signals ? ghostRider.markers : [])]);
    }
    const plan = this.riskScenario;
    if (plan && this.candleSeries) {
      this.analysisPriceLines.push(this.candleSeries.createPriceLine({ price: plan.entryPrice, color: '#9aa4b2', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'ENTRY' }));
      this.analysisPriceLines.push(this.candleSeries.createPriceLine({ price: plan.stopPrice, color: '#ff7168', lineWidth: 2, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'STOP' }));
      this.analysisPriceLines.push(this.candleSeries.createPriceLine({ price: plan.targetPrice, color: '#36c99a', lineWidth: 2, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `${this.targetRMultiple}R` }));
    }
    if (ghostRider && this.candleSeries) {
      const state = ghostRider.snapshot;
      if (state.entry !== undefined && state.stop !== undefined) {
        if (this.ghostRiderVisibility.entry) this.ghostRiderPriceLines.push(this.candleSeries.createPriceLine({ price: state.entry, color: '#3687e8', lineWidth: 2, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: 'GR ENTRY' }));
        if (this.ghostRiderVisibility.stop) this.ghostRiderPriceLines.push(this.candleSeries.createPriceLine({ price: state.stop, color: '#e24848', lineWidth: 2, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: 'GR SL' }));
        const targetColors = ['#38bdf8', '#a78bfa', '#fbbf24', '#fb7185', '#22c55e'];
        state.targets.forEach((target, index) => {
          const key = `tp${index + 1}` as GhostRiderVisibilityKey;
          if (this.ghostRiderVisibility[key]) this.ghostRiderPriceLines.push(this.candleSeries!.createPriceLine({ price: target, color: targetColors[index], lineWidth: 1, lineStyle: state.targetHits[index] ? LineStyle.Solid : LineStyle.Dashed, axisLabelVisible: true, title: `GR TP${index + 1}${state.targetHits[index] ? ' ✓' : ''}` }));
        });
      }
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

  private addAlignedOverlay(values: (number | undefined)[], times: Time[], title: string, color: string): void {
    if (!this.historyChartApi) return;
    const series = this.historyChartApi.addSeries(LineSeries, { color, lineWidth: 2, title, lastValueVisible: false, priceLineVisible: false });
    series.setData(values.flatMap((value, index) => value === undefined || !Number.isFinite(value) ? [] : [{ time: times[index], value }]));
    this.overlaySeries.push(series);
  }

  private clearAnalysisOverlays(): void {
    if (this.historyChartApi) {
      for (const series of this.overlaySeries) this.historyChartApi.removeSeries(series);
    }
    this.overlaySeries = [];
    if (this.candleSeries) {
      for (const line of this.analysisPriceLines) this.candleSeries.removePriceLine(line);
      for (const line of this.ghostRiderPriceLines) this.candleSeries.removePriceLine(line);
    }
    this.analysisPriceLines = [];
    this.ghostRiderPriceLines = [];
    this.fibonacciSummary = undefined;
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
    nearSupport.forEach((price, index) => this.analysisPriceLines.push(this.candleSeries!.createPriceLine({ price, color: '#28744d99', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `S${index + 1}` })));
    nearResistance.forEach((price, index) => this.analysisPriceLines.push(this.candleSeries!.createPriceLine({ price, color: '#c45b4b99', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `R${index + 1}` })));
  }

  private drawFibonacci(candles: HistoricalCandle[]): void {
    if (!this.candleSeries || candles.length < 2) return;
    let lowIndex = 0;
    let highIndex = 0;
    for (let index = 1; index < candles.length; index++) {
      if (candles[index].low < candles[lowIndex].low) lowIndex = index;
      if (candles[index].high > candles[highIndex].high) highIndex = index;
    }
    const low = candles[lowIndex].low;
    const high = candles[highIndex].high;
    const span = high - low;
    if (!(span > 0)) return;
    const upswing = lowIndex < highIndex;
    this.fibonacciSummary = {
      direction: upswing ? 'upswing' : 'downswing',
      start: candles[upswing ? lowIndex : highIndex].timestamp.slice(0, 16).replace('T', ' '),
      end: candles[upswing ? highIndex : lowIndex].timestamp.slice(0, 16).replace('T', ' '),
      low,
      high
    };
    const fibLevels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
    fibLevels.forEach((ratio, index) => {
      const price = upswing ? high - span * ratio : low + span * ratio;
      const color = ratio === 0.618 ? '#8065bd' : ratio === 0.5 ? '#a08cce' : '#a08cce88';
      this.analysisPriceLines.push(this.candleSeries!.createPriceLine({
        price,
        color,
        lineWidth: ratio === 0.618 ? 2 : 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `Fib ${Math.round(ratio * 1000) / 10}%`
      }));
    });
  }

  private detectPatterns(candles: HistoricalCandle[], times: Time[]): PatternMarker[] {
    return detectCandlestickPatterns(candles).map((match): PatternMarker => {
      const bullish = match.direction === 'bullish';
      const bearish = match.direction === 'bearish';
      return {
        time: times[match.index],
        text: match.marker,
        name: match.name,
        position: bullish ? 'belowBar' : 'aboveBar',
        color: bullish ? '#28744d' : bearish ? '#c45b4b' : '#8070b5',
        shape: bullish ? 'arrowUp' : bearish ? 'arrowDown' : 'circle'
      };
    }).slice(-60);
  }

  private detectTradersGitaMarkers(candles: HistoricalCandle[], times: Time[]): PatternMarker[] {
    const tickSize = this.selectedHistoryInstrument?.tick_size || 0.05;
    return detectTraderGitaPatterns(candles, {
      ...this.tradersGitaSettings,
      tickSize,
      showTrendNames: this.tradersGitaShowTrendNames,
      confirmedOnly: this.tradersGitaConfirmedOnly,
      groups: this.tradersGitaGroups
    }).map((match): PatternMarker => {
      const bullish = match.direction === 'bullish';
      const bearish = match.direction === 'bearish';
      return {
        time: times[match.index],
        position: bullish ? 'belowBar' : 'aboveBar',
        color: bullish ? '#25a878' : bearish ? '#e05258' : '#9b83e8',
        shape: bullish ? 'arrowUp' : bearish ? 'arrowDown' : 'circle',
        text: match.shortName,
        name: `Candlestick: ${match.name}`
      };
    }).slice(-500);
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
