import { StockChoicesComponent } from '../shared/stock-choices.component';
import { GoldenInputs,defaultGoldenSettings } from '../option-market/golden-cross.types';
import { SuryavanshiInputs,defaultSuryavanshiSettings } from '../option-market/suryavanshi.types';
import { backendUrl } from '../backend-url';
import { OptionChainComponent } from '../stock-details/option-chain.component';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, Input, OnChanges, OnDestroy, OnInit, EventEmitter, Output, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { AgGridAngular } from 'ag-grid-angular';
import { CellStyleModule, ClientSideRowModelModule, ColDef, ColumnApiModule, GridApi, GridReadyEvent, ICellRendererParams, ModuleRegistry, NumberFilterModule, PaginationModule, QuickFilterModule, TextFilterModule, TooltipModule, colorSchemeDark, themeQuartz } from 'ag-grid-community';
import { MarketApiService, MarketAssetQuote, ScannerStrategy, SelectedStock } from '../market-api.service';
import { OptionAnalysisComponent } from '../option-market/option-analysis.component';
import { SutradharInputs } from '../option-market/sutradhar.types';
import { GhostAssessment } from '../option-market/ghost-rider.types';
import { ResearchDashboardComponent } from '../research/research-dashboard.component';
import { RESEARCH_VIEWS } from '../research/research.types';

type FactorField = 'changePct' | 'volume' | 'price';
interface FactorRule { field: FactorField; min: string; max: string; importance: 'Important' | 'Optional'; }
interface SavedScreener { name: string; strategyId: string; timeframe: string; factors: FactorRule[]; sector?: string; strategyParams?: Record<string, number | boolean | string>; market?: string; }
interface SignalMetric { label: string; value: number; compareToClose: boolean; }
interface SignalBadge { label: string; passed?: boolean; tone?: 'positive' | 'negative' | 'neutral'; explanation?: string; }
interface ScreenResult { entry?: number; stopLoss?: number; tp1?: number; tp2?: number; tp3?: number; tp4?: number; tp5?: number; setupState?: string; instrumentKey: string; exchange: string; symbol: string; name: string; price: number; changePct: number | null; volume: number; status: string; signal?: string; state?: string; divergenceType?: string; source: 'database' | 'strategy'; detail?: string; signalMetrics?: SignalMetric[]; signalBadges?: SignalBadge[]; sector: string; }
interface GridColumnOption { id: string; label: string; visible: boolean; }
interface ScreenResult extends Partial<GhostAssessment> { asOf?: string; orbMinutes?: number; orbHeldBars?: number; orbGapPct?: number | null; vwapPosition?: string; signalExplanation?: string; ema20?: number | null; ema50?: number | null; sma200?: number | null; ema20Position?: string; ema50Position?: string; sma200Position?: string; }
const CONTEXT_COLUMNS = [
  ['decision', 'Entry assessment'], ['sessionDate', 'Session (IST)'], ['dayOpen', 'Day open'],
  ['fromOpenPct', 'From open %'], ['dayHighPct', 'Day high / open %'], ['dayLowPct', 'Day low / open %'],
  ['dayRangePosition', 'Day range position %'], ['nearestLevel', 'Nearest SL / target'],
  ['stopDistancePct', 'To stop %'], ['nextTarget', 'Next untouched target'], ['remainingRR', 'Remaining R/R'], ['rrTarget', 'R/R target'],
  ['strength', 'Trend strength'], ['strengthScore', 'Directional votes %'], ['orbState', 'Opening range'],
  ['orbHigh', 'OR high'], ['orbLow', 'OR low'], ['orbMinutes', 'OR minutes'], ['orbHeldBars', 'Held 5m bars'],
  ['orbGapPct', 'Beyond range %'], ['adx', 'ADX 14'], ['rsi14', 'RSI 14'], ['rsi5m', '5m RSI'],
  ['macdMain', 'MACD'], ['macdSignal', 'MACD signal'], ['macdHistogram', 'MACD histogram'],
  ['relativeVolume', 'Relative volume'], ['vwap', 'VWAP'], ['vwapPosition', 'Price vs VWAP'], ['ema9', 'EMA 9'], ['ema21', 'EMA 21'], ['atr', 'ATR 14'],
  ['ema20', 'EMA 20'], ['ema50', 'EMA 50'], ['sma200', 'SMA 200'],
  ['ema20Position', 'Price vs EMA 20'], ['ema50Position', 'Price vs EMA 50'], ['sma200Position', 'Price vs SMA 200'],
  ['pullersPct', 'Pullers %'], ['draggersPct', 'Draggers %'], ['progressR', 'Move from entry (R)'],
  ['asOf', 'Candle time (IST)'], ['decisionReason', 'Assessment reason']
] as const;
const GHOST_DEFAULT_COLUMNS = ['dayOpen', 'orbState', 'adx', 'rsi14', 'macdMain', 'vwap', 'vwapPosition', 'ema20Position', 'ema50Position', 'sma200Position'];
const GHOST_VIEW_COLUMNS = ['symbolCompany', 'status', 'price', 'dayOpen', 'changePct', 'orbState', 'adx', 'rsi14', 'macdMain', 'vwap', 'vwapPosition', 'ema20Position', 'ema50Position', 'sma200Position', 'volume', 'actions'];
const COLUMN_HELP: Record<string, string> = {
  status: 'Ghost Rider signal is the direction of the original EMA crossover setup. BUY/SELL alone does not mean a fresh entry; check Entry check and its explanation.',
  decision: 'Checks whether the setup meets the current screening conditions. WAIT means conditions are missing or not met. Hover for the reason; a candidate is not an executed order.',
  stopLoss: 'Stop-loss price belonging to the original setup. The level may already have been touched; hover for its status.',
  nextTarget: 'Next target not yet touched and still ahead of the latest candle price. The percentage is the remaining distance from that price, not from the original entry. A target is not guaranteed.',
  remainingRR: 'Remaining potential reward divided by distance to the stop, measured from the latest candle price. Uses TP2 or the next untouched target beyond TP2. 2:1 means two units of possible reward for one unit of stop risk.',
  sessionDate: 'Trading session date in India associated with the stored candle. This is not necessarily today or the time of the original signal.',
  dayOpen: 'Opening price of the trading session represented by the stored candle.',
  fromOpenPct: 'Percentage change from that session opening price to the latest candle close.',
  dayHighPct: 'Highest price reached in that session, expressed as a percentage above its opening price.',
  dayLowPct: 'Lowest price reached in that session, expressed as a percentage relative to its opening price.',
  nearestLevel: 'Closest original stop or target to the latest candle price. This is proximity only; the level may already have been touched.',
  stopDistancePct: 'Directional distance from the latest candle price to the original stop-loss. Zero or a negative value means price has reached or moved beyond the stop.',
  strength: 'Trend direction from indicator votes, with trend strength from ADX. This is not a probability of profit.',
  strengthScore: 'Percentage of directional indicators agreeing. Indicator agreement is not a win rate.',
  asOf: 'Time of the stored candle used for this result, shown in India time. It is not a live quote timestamp.',
  entry: 'Original crossover setup entry price. It is not a recommendation to enter now.',
  adx: 'ADX 14 measures trend strength, not bullish or bearish direction. Ghost Rider entry assessment requires ADX above 25.',
  rsi14: 'RSI 14 measures momentum on a 0–100 scale using the selected timeframe. This is separate from the optional 5-minute RSI.',
  macdMain: 'MACD line from the selected timeframe. The MACD signal line and histogram are separate optional columns; a positive MACD value alone does not establish a fresh crossover.',
  vwap: 'Volume-weighted average price calculated by the Ghost Rider engine for the selected candles. Compare with the latest candle price; VWAP alone is not an entry signal.',
  vwapPosition: 'Compares the latest stored candle close with its VWAP: Above VWAP is green, Below VWAP is red, and At VWAP means equal. Missing prices or VWAP are unavailable. This shows position, not a new crossover or entry signal.',
  ema20Position: 'Latest stored candle close versus EMA 20 of the selected timeframe. Above is green; below is red. At least 20 candles are required. Position alone does not establish a new crossover.',
  ema50Position: 'Latest stored candle close versus EMA 50 of the selected timeframe. This uses EMA 50, not SMA 50. Above is green; below is red. At least 50 candles are required.',
  sma200Position: 'Latest stored candle close versus SMA 200 of the selected timeframe. Above is green; below is red. At least 200 candles are required. These periods count candles, not necessarily days.',
  volume: 'Traded volume in the latest stored candle of the selected timeframe. This is the raw volume, not relative volume or institutional order flow.',
  orbState: 'Whether completed 5-minute candles held above or below the opening range for that session. BULLISH is an upward hold; BEARISH is a downward hold. Missing session history remains unavailable.',
};
const ORB_DEFAULT_COLUMNS = ['decision', 'sessionDate', 'dayOpen', 'fromOpenPct', 'dayHighPct', 'dayLowPct', 'orbState', 'orbHigh', 'orbLow', 'orbMinutes', 'orbHeldBars', 'orbGapPct', 'asOf', 'decisionReason'];
const STORAGE_KEY = 'traders-gita-saved-screeners';
ModuleRegistry.registerModules([ClientSideRowModelModule, ColumnApiModule, TextFilterModule, NumberFilterModule, QuickFilterModule, PaginationModule, CellStyleModule, TooltipModule]);

@Component({ selector: 'app-ema-scanner', standalone: true, imports: [StockChoicesComponent, CommonModule, AgGridAngular, OptionAnalysisComponent, OptionChainComponent, ResearchDashboardComponent], templateUrl: './ema-scanner.component.html', styleUrl: './ema-scanner.component.css' })
export class EmaScannerComponent implements OnInit, OnDestroy, OnChanges {
  @Input() active = true;
  ngOnChanges(): void { if (!this.active) { this.ghostStock = undefined; this.optionStock = undefined; } else if(!this.hasScanned&&!this.loading&&!this.loadingStrategies)this.scan(); }
  optionStock?: ScreenResult;
  ghostStock?: ScreenResult;
  readonly loginUrl = backendUrl('/auth/upstox');
  @Output() stockSelected = new EventEmitter<SelectedStock>();
  openStock(row: ScreenResult | undefined): void {
    if (!row?.instrumentKey) return;
    if (['ghost_rider','rsi_divergence','sutradhar','suryavanshi','golden_death_cross'].includes(this.selectedStrategy)) {
      this.sutradharInputs={p1:this.numericParam('p1',14),p2:this.numericParam('p2',7),p3:this.numericParam('p3',5),use_ema:this.strategyParams['use_ema']===true};
      this.suryavanshiInputs={length:this.numericParam('length',20),rr_ratio:this.numericParam('rr_ratio',1.1),candle_type:this.strategyParams['candle_type']==='Body'?'Body':'Wicks',sl_type:this.strategyParams['sl_type']==='High/Low'?'High/Low':'Close',show_sl:this.strategyParams['show_sl']===true};
      const goldenDefaults = defaultGoldenSettings().inputs;
      this.goldenInputs = Object.fromEntries(Object.entries(goldenDefaults).map(([key, value]) => [key, this.selectedStrategy === 'golden_death_cross' ? this.strategyParams[key] ?? value : value])) as unknown as GoldenInputs;
      this.ghostStock = row; return;
    }
    this.stockSelected.emit({ key: row.instrumentKey, symbol: row.symbol, name: row.name, exchange: row.exchange, strategy: this.activeStrategy?.name ?? 'Market Screener', timeframe: this.timeframe, status: row.status, detail: row.detail, price: row.price, metrics: row.signalMetrics, checks: row.signalBadges });
  }
  private readonly api = inject(MarketApiService);
  private scanSubscription?: Subscription;
  private strategySubscription?: Subscription;
  readonly factors: { id: FactorField; label: string; suffix: string }[] = [
    { id: 'changePct', label: 'Change %', suffix: '%' },
    { id: 'volume', label: 'Volume', suffix: 'shares' },
    { id: 'price', label: 'Last price', suffix: '₹' },
  ];
  rules: FactorRule[] = [{ field: 'changePct', min: '', max: '', importance: 'Important' }];
  strategies: ScannerStrategy[] = [];
  selectedStrategy = 'ghost_rider';
  readonly researchViews = RESEARCH_VIEWS;
  get isResearch(): boolean { return this.researchViews.some(v => v.id === this.selectedStrategy); }
  timeframe = '1d';
  strategyParams: Record<string, number | boolean | string> = {};
  numericParam(name:string,fallback:number):number{return typeof this.strategyParams[name]==='number'?this.strategyParams[name] as number:fallback;}
  goldenInputs:GoldenInputs=defaultGoldenSettings().inputs;
  suryavanshiInputs:SuryavanshiInputs=defaultSuryavanshiSettings().inputs;
  sutradharInputs:SutradharInputs={p1:14,p2:7,p3:5,use_ema:false};
  loading = false;
  loadingStrategies = true;
  error = '';
  coverageNote = '';
  results: ScreenResult[] = [];
  totalScanned = 0;
  universeCount = 0;
  hasScanned = false;
  readonly sectors = ['All sectors', 'Banking & Finance', 'IT & Software', 'Pharmaceuticals', 'Automobile', 'Energy & Oil', 'Metals & Mining', 'FMCG', 'Telecom', 'Infrastructure & Capital Goods', 'Real Estate', 'Other'];
  selectedSector = 'All sectors';
  savedScreeners: SavedScreener[] = this.readSaved();
  selectedSaved = '';
  saveName = '';
  gridPanel: 'columns' | 'filters' | '' = '';
  readonly columnHelp = COLUMN_HELP;
  private gridApi?: GridApi<ScreenResult>;
  readonly gridColumns: GridColumnOption[] = [
    ...CONTEXT_COLUMNS.map(([id, label]) => ({ id, label, visible: false })),
    { id: 'status', label: 'Status', visible: true }, { id: 'symbolCompany', label: 'Symbol / Company', visible: true },
    { id: 'changePct', label: 'Change %', visible: true }, { id: 'volume', label: 'Volume', visible: true },
    { id: 'price', label: 'Last price', visible: true }, { id: 'sector', label: 'Sector', visible: false },
    { id: 'detail', label: 'Signal details', visible: false },
    ...['setupState', 'entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5'].map(id => ({ id, label: id === 'setupState' ? 'Setup' : id === 'stopLoss' ? 'Stop loss' : id.toUpperCase(), visible: false })),
  ];
  rightFilters = { symbol: '', status: '', decision: '', sector: '', divergence: '', changeMin: '', changeMax: '', volumeMin: '', volumeMax: '', priceMin: '', priceMax: '' };
  get decisionOptions(): string[] { return [...new Set(this.results.map(r => r.decision).filter((value): value is string => !!value))].sort(); }
  private filteredRowsSource?: ScreenResult[];
  private filteredRowsSettings?: EmaScannerComponent['rightFilters'];
  private filteredRowsSector = '';
  private filteredRowsCache: ScreenResult[] = [];
  readonly gridTheme = themeQuartz.withPart(colorSchemeDark).withParams({
    backgroundColor: '#101116', foregroundColor: '#d4d6dc', headerBackgroundColor: '#191a22',
    headerTextColor: '#a0a4af', borderColor: '#2b2d37', rowHoverColor: '#1c2423',
    accentColor: '#e0bd43', fontFamily: 'Inter, Segoe UI, Arial, sans-serif', fontSize: 11, spacing: 6
  });
  readonly defaultColDef: ColDef<ScreenResult> = { sortable: true, filter: true, floatingFilter: false, resizable: true, minWidth: 100, tooltipValueGetter: p => this.columnHint(String((p.colDef as ColDef<ScreenResult> | undefined)?.field ?? ''), p.data, p.colDef?.headerName, p.valueFormatted ?? p.value) };
  readonly columnDefs: ColDef<ScreenResult>[] = [
    { headerName: 'Actions', colId: 'actions', width: 170, pinned: 'right', sortable: false, filter: false, resizable: false, cellRenderer: (p: ICellRendererParams<ScreenResult>) => {
      const actions = document.createElement('div');
      actions.style.cssText = 'display:flex;gap:6px;align-items:center;height:100%';
      for (const label of ['Chart', 'Options']) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
        button.setAttribute('aria-label', `${label} for ${p.data?.symbol ?? 'stock'}`);
        button.style.cssText = 'background:#172220;border:1px solid #35454c;border-radius:4px;color:#d4e2dc;cursor:pointer;padding:0 8px;height:26px;min-height:0;font-family:inherit;font-size:11px;line-height:1;flex:none';
        button.disabled = !p.data?.instrumentKey;
        button.addEventListener('click', event => { event.stopPropagation(); if (label === 'Chart') this.openStock(p.data); else if (p.data) this.optionStock = p.data; });
        actions.appendChild(button);
      }
      return actions;
    } },
    { headerName: '#', colId:'rowNumber', valueGetter: (p) => (p.node?.rowIndex ?? 0) + 1, width: 58, maxWidth: 65, sortable: false, filter: false, floatingFilter: false, pinned: 'left' },
    { field: 'status', headerName: 'Status', width: 110, minWidth: 90, pinned: 'left', valueFormatter: (p) => p.value === 'NEWLY_ALIGNED' ? 'NEW MATCH' : String(p.value ?? ''), cellStyle: (p) => ['BULLISH', 'BUYING PRESSURE', 'BUYING WATCH', 'BULLISH CONFIRMED', 'STRONG BULLISH', 'STRONG BULLISH ACTIVE', 'CONFIRMED BULLISH', 'CONFIRMED BULLISH ACTIVE', 'BUY', 'PREVIOUS SIGNAL'].includes(String(p.value)) ? { color: '#55c99f', backgroundColor: 'transparent', fontWeight: '700' } : ['BEARISH', 'SELLING PRESSURE', 'SELLING WATCH', 'BEARISH CONFIRMED', 'BEARISH WATCH', 'BEARISH WARNING', 'SELL', 'WEAKENED'].includes(String(p.value)) ? { color: '#ed8792', backgroundColor: '#54242e', fontWeight: '700' } : ['EARLY BULLISH', 'BULLISH WATCH', 'WATCH', 'NEWLY_ALIGNED'].includes(String(p.value)) ? { color: '#edc74f', backgroundColor: 'transparent', fontWeight: '700' } : p.value === 'PREFERRED' ? { color: '#edd36a', backgroundColor: 'transparent', fontWeight: '700' } : { color: '#a4a8b2', backgroundColor: 'transparent', fontWeight: '700' } },
    { headerName: 'Symbol / Company', colId: 'symbolCompany', valueGetter: (p) => p.data ? (p.data.name && p.data.name !== p.data.symbol ? `${p.data.symbol} · ${p.data.name}` : p.data.symbol) : '', minWidth: 180, flex: 1, filter: 'agTextColumnFilter', cellClass: 'symbol-company-cell', cellRenderer: (p: ICellRendererParams<ScreenResult>) => {
      const label = document.createElement('span'); label.textContent = String(p.value ?? ''); label.title = `${p.value ?? ''}\nUse Chart or Options to open this stock.`;
      label.style.cssText = 'display:inline-block;color:#e0bd43;white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis;vertical-align:middle;';
      return label;
    } },
    { field: 'changePct', headerName: 'Change %', width: 115, headerTooltip: 'Change in the latest stored candle close versus the previous candle close, using the selected timeframe. Daily compares trading days; 1h compares hourly candles. Formula: (Latest close − Previous close) ÷ Previous close × 100. This is separate from the strategy BUY/SELL signal.', tooltipValueGetter: p => this.changeHint(p.data), filter: 'agNumberColumnFilter', valueFormatter: (p) => p.value == null ? '—' : `${Number(p.value).toFixed(2)}%`, cellStyle: (p) => Number(p.value) > 0 ? { color: '#45c89c' } : Number(p.value) < 0 ? { color: '#e3737b' } : null },
    { field: 'volume', headerName: 'Volume', width: 115, filter: 'agNumberColumnFilter', valueFormatter: (p) => this.formatVolume(Number(p.value ?? 0)) },
    { field: 'price', headerName: 'Last', width: 140, filter: 'agNumberColumnFilter', valueFormatter: (p) => Number(p.value) ? this.formatPrice(Number(p.value)) : '—' },
    { field: 'sector', headerName: 'Sector', minWidth: 165, filter: 'agTextColumnFilter' },
    { field: 'setupState', headerName: 'Setup', width: 100 },
    ...(['entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5'] as const).map(field => ({ field, headerTooltip: COLUMN_HELP[field], headerName: field === 'stopLoss' ? 'Stop loss' : field.toUpperCase(), width: 120, filter: 'agNumberColumnFilter', cellRenderer: (p: ICellRendererParams<ScreenResult>) => { const span = document.createElement('span'); const hit = field.startsWith('tp') && (p.data as unknown as Record<string, unknown>)?.[field + 'Hit']; span.textContent = p.value == null ? '—' : this.formatPrice(Number(p.value)) + (hit ? ' ✓' : ''); span.style.color = hit ? '#40e0d0' : field === 'stopLoss' ? '#ec8c91' : '#d4d6dc'; return span; } })),
    ...CONTEXT_COLUMNS.map(([field, label]): ColDef<ScreenResult> => ({
      field, headerName: label, width: ['decision', 'strength', 'nearestLevel', 'nextTarget'].includes(field) ? 185 : field === 'asOf' ? 180 : field === 'decisionReason' ? 460 : 145,
      valueGetter: field === 'vwapPosition' ? p => this.priceVsVwap(p.data) : field === 'ema20Position' ? p => this.priceVsAverage(p.data,'ema20','EMA 20') : field === 'ema50Position' ? p => this.priceVsAverage(p.data,'ema50','EMA 50') : field === 'sma200Position' ? p => this.priceVsAverage(p.data,'sma200','SMA 200') : undefined,
      headerTooltip: COLUMN_HELP[field],
      tooltipValueGetter: p => this.columnHint(field, p.data, label, p.valueFormatted ?? p.value),
      filter: ['decision', 'strength', 'nearestLevel', 'nextTarget', 'rrTarget', 'orbState', 'sessionDate', 'asOf', 'decisionReason', 'vwapPosition','ema20Position','ema50Position','sma200Position'].includes(field) ? 'agTextColumnFilter' : 'agNumberColumnFilter',
      valueFormatter: p => {
        if (p.value === null || p.value === undefined) return '—';
        if (field === 'asOf') return new Intl.DateTimeFormat('en-IN', { timeZone:'Asia/Kolkata', day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit', hour12:false }).format(new Date(String(p.value)));
        if (field === 'nearestLevel') return `${p.value}${p.data?.nearestLevelPct == null ? '' : ' · ' + p.data.nearestLevelPct.toFixed(2) + '%'}`;
        if (field === 'nextTarget') return `${p.value}${p.data?.nextTargetPct == null ? '' : ' · ' + p.data.nextTargetPct.toFixed(2) + '%'}`;
        if (field === 'remainingRR') return `${Number(p.value).toFixed(2)}:1 (${p.data?.rrTarget ?? 'target'})`;
        return typeof p.value === 'number' ? p.value.toFixed(2) : String(p.value);
      },
      cellStyle: p => ['ema20Position','ema50Position','sma200Position'].includes(field) ? {color:String(p.value).startsWith('Above ')?'#55c99f':String(p.value).startsWith('Below ')?'#ed8792':'#a4a8b2'} : field === 'orbState' ? {color:p.value === 'BULLISH' ? '#55c99f' : p.value === 'BEARISH' ? '#ed8792' : '#a4a8b2'} : field === 'vwapPosition' ? {color:p.value === 'Above VWAP' ? '#55c99f' : p.value === 'Below VWAP' ? '#ed8792' : '#a4a8b2'} : field === 'fromOpenPct' || field === 'orbGapPct' ? Number(p.value) > 0 ? {color:'#55c99f'} : Number(p.value) < 0 ? {color:'#ed8792'} : null : field === 'decision' ? {color:String(p.value).includes('BUY') || String(p.value).includes('BULLISH') ? '#55c99f' : String(p.value).includes('SELL') || String(p.value).includes('BEARISH') ? '#ed8792' : '#edc74f'} : null
    })),
    { field: 'detail', headerName: 'Signal details', minWidth: 520, flex: 2, filter: 'agTextColumnFilter', cellRenderer: (p: ICellRendererParams<ScreenResult, string | undefined>) => this.renderSignalDetails(p.data, p.value) },
  ];

  ngOnInit(): void {
    this.api.fnoStocks().subscribe({ next: data => this.universeCount = data.total });
    this.strategySubscription = this.api.scannerStrategies().subscribe({
      next: ({ strategies }) => { this.strategies = strategies; this.loadingStrategies = false;this.selectStrategy(this.selectedStrategy, false);if(this.active&&!this.hasScanned)this.scan(); },
      error: () => { this.loadingStrategies = false;this.selectStrategy(this.selectedStrategy, false);if(this.active&&!this.hasScanned)this.scan(); }
    });
  }

  ngOnDestroy(): void { this.scanSubscription?.unsubscribe(); this.strategySubscription?.unsubscribe(); }

  get activeStrategy(): ScannerStrategy | undefined { return this.strategies.find((item) => item.id === this.selectedStrategy); }
  get isMarketScreener(): boolean { return this.selectedStrategy === 'market_screener'; }
  get statusOptions(): { value: string; label: string }[] {
    const labels: Record<string, string> = {
      PREFERRED: 'Preferred', GAINER: 'Gainer', DECLINER: 'Decliner', FLAT: 'Flat',
      ALIGNED: 'Match', NEWLY_ALIGNED: 'New match', MATCH: 'Match',
      STRONG_BULLISH: 'Strong bullish', STRONG_BULLISH_ACTIVE: 'Strong bullish · Active',
      CONFIRMED_BULLISH: 'Confirmed bullish', CONFIRMED_BULLISH_ACTIVE: 'Confirmed bullish · Active', EARLY_BULLISH: 'Early bullish',
      BULLISH_WATCH: 'Bullish watch', BEARISH_WARNING: 'Bearish warning', NEUTRAL: 'Neutral', INSUFFICIENT_HISTORY: 'Insufficient history'
    };
    return [...new Set(this.results.map((row) => row.status))]
      .sort((a, b) => a.localeCompare(b))
      .map((value) => ({ value, label: labels[value] ?? value.replaceAll('_', ' ') }));
  }
  get filteredResults(): ScreenResult[] {
    const filters = this.rightFilters;
    if (this.filteredRowsSource === this.results && this.filteredRowsSettings === filters && this.filteredRowsSector === this.selectedSector) {
      return this.filteredRowsCache;
    }
    const query = filters.symbol.trim().toLowerCase();
    this.filteredRowsCache = this.results.filter((row) =>
      (this.selectedSector === 'All sectors' || row.sector === this.selectedSector)
      && (!filters.sector || row.sector === filters.sector)
      && (!filters.status || row.status === filters.status)
      && (!filters.decision || row.decision === filters.decision)
      && (!filters.divergence || row.divergenceType === filters.divergence)
      && (!query || `${row.symbol} ${row.name}`.toLowerCase().includes(query))
      && (!filters.changeMin || (row.changePct !== null && row.changePct >= Number(filters.changeMin)))
      && (!filters.changeMax || (row.changePct !== null && row.changePct <= Number(filters.changeMax)))
      && (!filters.volumeMin || row.volume >= Number(filters.volumeMin))
      && (!filters.volumeMax || row.volume <= Number(filters.volumeMax))
      && (!filters.priceMin || row.price >= Number(filters.priceMin))
      && (!filters.priceMax || row.price <= Number(filters.priceMax))
    );
    this.filteredRowsSource = this.results;
    this.filteredRowsSettings = filters;
    this.filteredRowsSector = this.selectedSector;
    return this.filteredRowsCache;
  }
  get selectedTimeframe(): string { return this.timeframe.toUpperCase(); }
  private priceVsVwap(row: ScreenResult | undefined): string {
    return this.priceVsAverage(row, 'vwap', 'VWAP');
  }
  private priceVsAverage(row: ScreenResult | undefined, field: 'vwap'|'ema20'|'ema50'|'sma200', label: string): string {
    const average=row?.[field];
    if(!row || average==null || !Number.isFinite(average) || average<=0 || !Number.isFinite(row.price) || row.price<=0)return 'Unavailable';
    return `${row.price>average?'Above':row.price<average?'Below':'At'} ${label}`;
  }

  addFactor(): void { this.rules = [...this.rules, { field: 'volume', min: '', max: '', importance: 'Important' }]; }
  removeFactor(index: number): void { this.rules = this.rules.filter((_, i) => i !== index); }
  updateRule(index: number, key: keyof FactorRule, value: string): void {
    const rule = this.rules[index];
    if (!rule) return;
    if (key === 'field') rule.field = value as FactorField;
    else if (key === 'importance') rule.importance = value as FactorRule['importance'];
    else if (key === 'min' || key === 'max') rule[key] = value;
    this.rules = [...this.rules];
  }

  selectStrategy(value: string, autoScan = true): void {
    this.scanSubscription?.unsubscribe(); this.loading = false; this.totalScanned = 0;
    this.selectedStrategy = value; this.results = []; this.hasScanned = false; this.error = '';
    if (this.isResearch) return;
    if (value === 'market_screener') this.timeframe = '1d';
    if (value === 'institution_transaction' && !['1d','1h'].includes(this.timeframe)) this.timeframe = '1d';
    for (const column of this.gridColumns.filter(c => CONTEXT_COLUMNS.some(([id]) => id === c.id))) {
      column.visible = (value === 'ghost_rider' ? GHOST_DEFAULT_COLUMNS : value === 'opening_range_breakout' ? ORB_DEFAULT_COLUMNS : []).includes(column.id);
      this.gridApi?.setColumnsVisible([column.id], column.visible);
    }
    const detailColumn = this.gridColumns.find(c => c.id === 'detail');
    if (detailColumn) { detailColumn.visible = !['market_screener','ghost_rider', 'opening_range_breakout'].includes(value); this.gridApi?.setColumnsVisible(['detail'], detailColumn.visible); }
    if (value === 'opening_range_breakout') this.timeframe = '5m';
    this.orderContextColumns();
    for (const column of this.gridColumns.filter(c => ['setupState', 'entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5', 'volume', 'price'].includes(c.id))) { column.visible = ['volume','price'].includes(column.id) || (value==='suryavanshi'&&['setupState','entry','stopLoss','tp1'].includes(column.id)); this.gridApi?.setColumnsVisible([column.id], column.visible); }
    this.mobileGrid=undefined;
    if(this.gridApi)this.configureGrid(typeof window!=='undefined'&&window.innerWidth<760);
    if (['ghost_rider','rsi_divergence','golden_death_cross'].includes(value) && !['1d','1h','15m','5m'].includes(this.timeframe)) this.timeframe = '1d';
    if(value==='suryavanshi'&&!['1d','1h','15m','5m'].includes(this.timeframe))this.timeframe='15m';
    if(value==='sutradhar'&&!['1h','15m','5m'].includes(this.timeframe))this.timeframe='15m';
    this.strategyParams = Object.fromEntries((this.activeStrategy?.parameters ?? []).filter(item=>['number','boolean','string'].includes(typeof item.default)).map(item=>[item.name,item.default as number|boolean|string]));
    if(autoScan)this.refreshSelection();
  }
  private refreshSelection():void{if(this.active&&!this.loadingStrategies)this.scan();}
  selectTimeframe(value:string):void{if(value===this.timeframe)return;this.scanSubscription?.unsubscribe();this.timeframe=value;this.results=[];this.hasScanned=false;this.loading=false;this.error='';this.refreshSelection();}
  updateStrategyParam(key: string, value: string | boolean): void { this.strategyParams[key] = this.activeStrategy?.parameters.find(p=>p.name===key)?.type==='str'?String(value):typeof value==='boolean'?value:Number(value); }
  selectSector(value: string): void { this.selectedSector = value; }
  onGridReady(event: GridReadyEvent<ScreenResult>): void {
    this.gridApi = event.api;
    this.mobileGrid=undefined;
    for (const column of this.gridColumns) event.api.setColumnsVisible([column.id], column.visible);
    this.orderContextColumns();
    this.configureGrid(typeof window!=='undefined'&&window.innerWidth<760);
  }
  private mobileGrid?:boolean;
  gridResized(event:{clientWidth:number}):void{this.configureGrid(event.clientWidth<700);}
  private configureGrid(mobile:boolean):void{
    if(!this.gridApi||mobile===this.mobileGrid)return;this.mobileGrid=mobile;
    const ghost=this.selectedStrategy==='ghost_rider';
    this.gridApi.applyColumnState?.({state:[{colId:'rowNumber',hide:mobile||ghost,pinned:mobile?null:'left'},{colId:'status',pinned:mobile?null:'left',width:ghost?90:110},{colId:'actions',pinned:mobile?null:'right',width:ghost?140:170},{colId:'symbolCompany',pinned:mobile||ghost?'left':null,width:mobile?180:ghost?200:280,flex:mobile||ghost?null:1},
      {colId:'price',width:ghost?100:140},{colId:'changePct',width:ghost?100:115},{colId:'decision',width:ghost?150:185},{colId:'stopLoss',width:ghost?110:120},{colId:'nextTarget',width:ghost?150:185},{colId:'remainingRR',width:ghost?140:145},
      ...['dayOpen','orbState','adx','rsi14','macdMain','vwap','volume'].map(colId=>({colId,width:ghost?(colId==='orbState'?115:100):colId==='volume'?115:145}))]});
    if(mobile)this.gridApi.moveColumns(ghost?GHOST_VIEW_COLUMNS:['symbolCompany','price','status','changePct','volume','actions'],0);
  }
  private orderContextColumns(): void {
    const columns = this.selectedStrategy === 'ghost_rider' ? GHOST_DEFAULT_COLUMNS : this.selectedStrategy === 'opening_range_breakout' ? ORB_DEFAULT_COLUMNS : [];
    if (this.selectedStrategy==='ghost_rider') this.gridApi?.moveColumns(GHOST_VIEW_COLUMNS, 0);
    else if (columns.length) this.gridApi?.moveColumns(['price', ...columns], 4);
    const status = this.columnDefs.find(c => c.field === 'status');
    if (status) { status.headerName = this.selectedStrategy === 'ghost_rider' ? 'Signal' : 'Status'; status.headerTooltip = this.selectedStrategy === 'ghost_rider' ? COLUMN_HELP['status'] : undefined; }
    for (const [field, normal, simple] of [['decision','Entry assessment','Entry check'],['nextTarget','Next untouched target','Next target'],['remainingRR','Remaining R/R','Reward / risk']]) {
      const column=this.columnDefs.find(c=>c.field===field);
      if(column)column.headerName=this.selectedStrategy==='ghost_rider'?simple:normal;
      const option=this.gridColumns.find(c=>c.id===field);
      if(option)option.label=this.selectedStrategy==='ghost_rider'?simple:normal;
    }
    this.gridApi?.refreshHeader();
  }
  setGridColumnVisible(column: GridColumnOption, visible: boolean): void {
    column.visible = visible;
    this.gridApi?.setColumnsVisible([column.id], visible);
  }
  toggleGridPanel(panel: 'columns' | 'filters'): void { this.gridPanel = this.gridPanel === panel ? '' : panel; }
  clearRightFilters(): void { this.rightFilters = { symbol: '', status: '', decision: '', sector: '', divergence: '', changeMin: '', changeMax: '', volumeMin: '', volumeMax: '', priceMin: '', priceMax: '' }; }
  setRightFilter(key: keyof EmaScannerComponent['rightFilters'], value: string): void { this.rightFilters = { ...this.rightFilters, [key]: value }; }

  scan(): void {
    if (this.isResearch) return;
    if (this.loading) return;
    this.loading = true; this.error = ''; this.coverageNote = '';  this.results = []; this.clearRightFilters(); this.hasScanned = true;
    if (this.isMarketScreener) {
      this.scanSubscription = this.api.marketEmaIndicators(this.timeframe).subscribe({
        next: ({ indicators, scanned }) => {
          this.totalScanned = scanned;
          this.results = indicators.flatMap((item) => {
            const previousClose = Number(item.previousClose ?? 0);
            const asset: MarketAssetQuote = {
              key: item.instrumentKey, symbol: item.symbol, name: item.name, exchange: 'NSE',
              price: item.close, previousClose, change: item.close - previousClose,
              changePct: Number(item.changePct ?? 0), volume: Number(item.volume ?? 0)
            };
            if (!this.matchesFactors(asset)) return [];
            const signalMetrics: SignalMetric[] = [
              { label: 'EMA 9', value: item.ema9, compareToClose: true },
              { label: 'EMA 20', value: item.ema20, compareToClose: true },
              { label: 'SMA 50', value: item.sma50, compareToClose: true },
              { label: 'SMA 200', value: item.sma200, compareToClose: true },
            ].filter((metric): metric is SignalMetric => metric.value !== null && Number.isFinite(metric.value));
            const status = this.preferredFactorsMatch(asset) ? 'PREFERRED' : asset.changePct > 0 ? 'GAINER' : asset.changePct < 0 ? 'DECLINER' : 'FLAT';
            return [{
              instrumentKey: item.instrumentKey, exchange: 'NSE', symbol: item.symbol, name: item.name, price: item.close, changePct: item.changePct,
              volume: asset.volume, status, source: 'database' as const,
              detail: item.historySufficient ? '' : `Limited daily history (${item.historySufficient ? 200 : 'under 200'} candles)`,
              signalMetrics, sector: this.classifySector(item.symbol, item.name)
            }];
          });
          this.loading = false;
        }, error: (error: HttpErrorResponse) => this.fail(error)
      });
      return;
    }
    this.scanSubscription = this.api.scanStrategy(this.selectedStrategy, this.timeframe, this.strategyParams, false).subscribe({
      next: (response) => {
        this.totalScanned = response.total_scanned;
        const short = (response.coverage ?? []).filter(c => !c.sufficient);
        this.coverageNote = [...short.map(c => `${c.symbol}: ${c.candles}/${c.required} candles`), ...(response.errors ?? []).map(e => `${e.symbol}: history fetch failed`)].join(' ? ');
        this.results = response.results.map((row) => {
          const numeric = (key: string) => Number(row[key] ?? 0);
          return { instrumentKey: String(row['instrumentKey'] ?? ''), exchange: String(row['exchange'] ?? 'NSE'), symbol: String(row['symbol'] ?? row['instrumentKey'] ?? '—'), name: String(row['name'] ?? row['symbol'] ?? ''),
            price: numeric('close'), changePct: row['changePct'] == null ? null : numeric('changePct'), volume: numeric('volume'), status: this.getScannerStatus(row), signal: String(row['signal'] ?? ''), state: String(row['state'] ?? ''), divergenceType: row['divergenceType'] ? String(row['divergenceType']) : undefined,
            ...Object.fromEntries([...CONTEXT_COLUMNS.map(([id]) => id), 'nearestLevelPct', 'nextTargetPct', 'orbReason', 'stale', 'stopTouched', 'entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5', 'tp1Hit', 'tp2Hit', 'tp3Hit', 'tp4Hit', 'tp5Hit'].map(key => [key, row[key]])), setupState: ['ghost_rider','suryavanshi'].includes(String(row['strategyId'])) ? String(row['state']) : undefined, source: 'strategy', signalExplanation: this.signalContext(row), detail: this.describeStrategyResult(row), signalMetrics: this.strategySignalMetrics(row), signalBadges: this.strategySignalBadges(row), sector: this.classifySector(String(row['symbol'] ?? ''), String(row['name'] ?? '')) };
        });
        this.loading = false;
      }, error: (error: HttpErrorResponse) => this.fail(error)
    });
  }

  private changeHint(row?: ScreenResult): string {
    const period: Record<string, string> = { '1d': 'trading day', '1w': 'weekly candle', '1M': 'monthly candle', '1h': 'hourly candle', '30m': '30-minute candle', '15m': '15-minute candle', '5m': '5-minute candle', '1m': '1-minute candle' };
    return [
      `Change % compares the latest stored candle close with the previous ${period[this.timeframe] ?? this.timeframe + ' candle'} close (${this.timeframe} timeframe).`,
      'Formula: (Latest close − Previous close) ÷ Previous close × 100.',
      row ? `Latest close: ${this.formatPrice(row.price)}. Change: ${row.changePct == null ? 'unavailable' : row.changePct.toFixed(2) + '%'}.` : '',
      'This measures price movement between candles; BUY/SELL comes from separate strategy conditions.',
    ].filter(Boolean).join('\n');
  }

  private columnHint(field: string, row: ScreenResult | undefined, label: string | undefined, value: unknown): string {
    const average = ({ema20Position:'ema20',ema50Position:'ema50',sma200Position:'sma200'} as const)[field as 'ema20Position'|'ema50Position'|'sma200Position'];
    const values = average && row ? `Candle close: ${this.ghostPrice(row.price)}; ${average.toUpperCase()}: ${this.ghostPrice(row[average])}.` : '';
    const stop = field==='stopLoss' && row ? `Stop status: ${row.stopTouched ? 'already touched since the signal' : 'not marked touched in the loaded history'}.` : '';
    return [field==='status' && this.selectedStrategy!=='ghost_rider' ? '' : COLUMN_HELP[field],values,stop,this.gridHint(row,label,value)].filter(Boolean).join('\n');
  }

  private gridHint(row: ScreenResult | undefined, label: string | undefined, value: unknown): string {
    return [`${label ?? 'Value'}: ${value ?? 'unavailable'}`, row?.decisionReason, row?.signalExplanation ?? row?.detail].filter(Boolean).join('\n');
  }

  private matchesFactors(asset: MarketAssetQuote): boolean {
    return this.rules.filter((rule) => rule.importance === 'Important').every((rule) => {
      if (!rule.min && !rule.max) return true;
      const value = rule.field === 'changePct' ? asset.changePct : rule.field === 'volume' ? asset.volume : asset.price;
      return (!rule.min || value >= Number(rule.min)) && (!rule.max || value <= Number(rule.max));
    });
  }

  private preferredFactorsMatch(asset: MarketAssetQuote): boolean {
    const optional = this.rules.filter((rule) => rule.importance === 'Optional' && (rule.min || rule.max));
    return optional.length > 0 && optional.every((rule) => {
      const value = rule.field === 'changePct' ? asset.changePct : rule.field === 'volume' ? asset.volume : asset.price;
      return (!rule.min || value >= Number(rule.min)) && (!rule.max || value <= Number(rule.max));
    });
  }

  private describeStrategyResult(row: Record<string, unknown>): string {
    if(row['strategyId']==='institution_transaction')return String(row['pressureExplanation'] ?? 'Price/volume pressure; institutional disclosures not checked.');
    if(row['strategyId']==='golden_death_cross')return this.describeCross(row);
    if(row['strategyId']==='suryavanshi')return `Suryavanshi ${row['status']} - ${row['state']} - Entry ${this.ghostPrice(row['entry'])} - Stop ${this.ghostPrice(row['stopLoss'])} - Target ${this.ghostPrice(row['tp1'])}`;
    if (row['strategyId'] === 'ghost_rider') return `Ghost rider v.2 ${row['signal']} · ${row['state']} · Signal ${this.signalDate(row['signalAt'])} · Entry ${this.ghostPrice(row['entry'])} · Stop ${this.ghostPrice(row['stopLoss'])} · TP1–TP5: ${[1,2,3,4,5].map(n => this.ghostPrice(row['tp'+n])).join(', ')}`;
    if (row['divergenceType']) return `${String(row['divergenceType']).replaceAll('_', ' ')} · Price ${this.formatPrice(Number(row['pivot1Price']))} → ${this.formatPrice(Number(row['pivot2Price']))} · RSI ${Number(row['pivot1Rsi']).toFixed(2)} → ${Number(row['pivot2Rsi']).toFixed(2)} · Confirmed ${this.signalDate(row['detectedAt'])} · As of ${this.signalDate(row['asOf'])}`;
    const close = Number(row['close'] ?? 0);
    const metrics = this.strategySignalMetrics(row);
    const chain: string[] = [];
    let previous = { label: 'Close', value: close };
    for (const metric of metrics.filter((item) => item.compareToClose)) {
      chain.push(`${previous.label} \u20B9${this.formatPrice(previous.value)} ${previous.value > metric.value ? '>' : '<='} ${metric.label} \u20B9${this.formatPrice(metric.value)}`);
      previous = { label: metric.label, value: metric.value };
    }
    const extra = metrics.filter((item) => !item.compareToClose).map((item) => `${item.label} ${item.value.toFixed(2)}`);
    return [...chain, ...extra].join(' | ') || String(row['matchedSince'] ?? 'Strategy match');
  }

  private getScannerStatus(row: Record<string, unknown>): string {
    if (row['strategyId'] === 'ghost_rider') return String(row['signal']);
    if (row['divergenceType']) return String(row['status']);
    const classifications: Record<string, string> = {
      STRONG_BULLISH: 'STRONG BULLISH', STRONG_BULLISH_ACTIVE: 'STRONG BULLISH ACTIVE',
      CONFIRMED_BULLISH: 'CONFIRMED BULLISH', CONFIRMED_BULLISH_ACTIVE: 'CONFIRMED BULLISH ACTIVE',
      EARLY_BULLISH: 'EARLY BULLISH', BULLISH_WATCH: 'BULLISH WATCH',
      BEARISH_WARNING: 'BEARISH WARNING', NEUTRAL: 'NEUTRAL', INSUFFICIENT_HISTORY: 'INSUFFICIENT HISTORY'
    };
    if (row['classification']) return classifications[String(row['classification'])] ?? String(row['classification']);
    switch (row['state']) {
      case 'CONFIRMED': return String(row['signal'] ?? row['status'] ?? 'SIGNAL');
      case 'CONFIRMED_ACTIVE': return 'PREVIOUS SIGNAL';
      case 'CONFIRMED_WEAKENED': return 'WEAKENED';
      case 'WATCH': return 'WATCH';
      case 'EXPIRED': return 'EXPIRED';
      default: return String(row['status'] ?? 'NEUTRAL');
    }
  }

  private strategySignalMetrics(row: Record<string, unknown>): SignalMetric[] {
    if(row['strategyId']==='institution_transaction')return [];
    if(row['strategyId']==='golden_death_cross'&&!row['requireConfirmation'])return [{label:`SMA ${row['smaMediumPeriod']}`,value:Number(row['sma50']),compareToClose:false},{label:`SMA ${row['smaLongPeriod']}`,value:Number(row['sma200']),compareToClose:false}];
    if(row['strategyId']==='suryavanshi')return ['entry','stopLoss','tp1'].filter(k=>row[k]!=null).map(k=>({label:k,value:Number(row[k]),compareToClose:false}));
    if(row['strategyId']==='sutradhar')return ['Flow','Crest','Crown','Value','Base','Origin','Mid','O'].filter(key=>row[key]!=null&&Number.isFinite(Number(row[key]))).map(key=>({label:key,value:Number(row[key]),compareToClose:false}));
    if (row['strategyId'] === 'ghost_rider') return ['entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5'].filter(key=>row[key]!=null&&Number.isFinite(Number(row[key]))).map(key => ({ label: key === 'stopLoss' ? 'Stop loss' : key.toUpperCase(), value: Number(row[key]), compareToClose: false }));
    const fast = Number(row['emaFastPeriod'] ?? this.numericParam('ema1',9)), slow = Number(row['emaSlowPeriod'] ?? this.numericParam('ema2',20));
    const medium = Number(row['smaMediumPeriod'] ?? this.numericParam('sma1',50)), long = Number(row['smaLongPeriod'] ?? this.numericParam('sma2',200));
    const fields: { key: string; label: string; compareToClose: boolean }[] = [
      { key: 'ema9', label: `EMA ${fast}`, compareToClose: true }, { key: 'ema20', label: `EMA ${slow}`, compareToClose: true },
      { key: 'sma50', label: `SMA ${medium}`, compareToClose: true }, { key: 'sma200', label: `SMA ${long}`, compareToClose: true },
      { key: 'rsi', label: 'RSI', compareToClose: false },
    ];
    return fields.flatMap(({ key, label, compareToClose }) => {
      const value = Number(row[key]);
      return row[key] !== undefined && row[key] !== null && Number.isFinite(value) ? [{ label, value, compareToClose }] : [];
    });
  }

  private describeCross(row: Record<string, unknown>): string {
    const medium = `SMA ${row['smaMediumPeriod'] ?? 50}`, long = `SMA ${row['smaLongPeriod'] ?? 200}`;
    const direction = row['crossType'] === 'GOLDEN_CROSS' ? 'above' : 'below';
    const value = (key: string) => row[key] == null || !Number.isFinite(Number(row[key])) ? 'unavailable' : this.formatPrice(Number(row[key]));
    const age = row['barsSinceCross'];
    const timing = age === 0 ? 'New cross on the latest completed candle.' : age == null ? 'Cross age unavailable.' : `Cross occurred ${age} completed candles ago; this is not a new cross on the latest candle.`;
    const relation = row['sma50'] == null || row['sma200'] == null ? '' : ` ${medium} is currently ${Number(row['sma50']) > Number(row['sma200']) ? 'above' : Number(row['sma50']) < Number(row['sma200']) ? 'below' : 'equal to'} ${long}.`;
    return [
      `${medium} crossed ${direction} ${long}${row['crossTime'] ? ` on ${this.signalDate(row['crossTime'])} IST` : ''}.`,
      `${this.timeframe} timeframe; periods count candles. ${timing}`,
      `Latest values: ${medium} ${value('sma50')}; ${long} ${value('sma200')}.${relation}`,
      row['requireConfirmation'] ? `Six-filter confirmation required: ${Number(row['confirmationCount'] ?? 0)}/6 checks currently pass.` : 'Classic crossover: SMA crossing alone triggers the signal; additional confirmation filters are disabled.',
      `State: ${String(row['state'] ?? 'unavailable').replaceAll('_', ' ')}.${row['asOf'] ? ` Data as of ${this.signalDate(row['asOf'])} IST.` : ''}`,
    ].join('\n');
  }

  private signalContext(row: Record<string, unknown>): string {
    if(row['strategyId']==='institution_transaction')return String(row['pressureExplanation'] ?? 'Institutional disclosures not checked.');
    const strategy = String(row['strategyId'] ?? this.selectedStrategy);
    const metrics = this.strategySignalMetrics(row).map(m => `${m.label}: ${m.label === 'RSI' ? m.value.toFixed(2) : this.formatPrice(m.value)}`).join('; ');
    const fast = `EMA ${row['emaFastPeriod'] ?? this.numericParam('ema_fast',9)}`, slow = `EMA ${row['emaSlowPeriod'] ?? this.numericParam('ema_slow',20)}`;
    const classifications: Record<string, string> = {
      EARLY_BULLISH: `${fast} crossed above ${slow}, with RSI above ${this.numericParam('early_rsi',50)}. Other confirmation checks may still fail.`,
      BEARISH_WARNING: `${fast} crossed below ${slow}.`,
      BULLISH_WATCH: 'Fast EMA > slow EMA > medium SMA, while the medium SMA remains below the long SMA.',
      CONFIRMED_BULLISH: 'MA alignment, price, rising SMA slopes, RSI and volume checks all pass.',
      CONFIRMED_BULLISH_ACTIVE: 'The bullish confirmation also passed on the previous candle; it is an ongoing setup.',
      STRONG_BULLISH: 'All five bullish checks pass and close is above the prior breakout high.',
      STRONG_BULLISH_ACTIVE: 'The strong bullish setup also passed on the previous candle; it is an ongoing setup.',
      NEUTRAL: 'No defined bullish stage or bearish EMA cross was detected.',
      INSUFFICIENT_HISTORY: 'Stored history is too short to evaluate all strategy conditions.',
    };
    let meaning = '';
    if (row['classification']) meaning = classifications[String(row['classification'])] ?? String(row['classification']);
    else if (strategy === 'ema_sma_alignment') meaning = row['status'] === 'NEWLY_ALIGNED' ? 'Close moved above all configured EMAs and SMAs compared with the previous candle. This does not imply the averages crossed one another.' : 'This strategy compares close with each configured EMA and SMA. Alignment alone does not establish a new crossover.';
    else if (strategy === 'rsi_reversal') meaning = `RSI recovered from below ${this.numericParam('oversold',30)} to that threshold or above. Previous RSI: ${row['prevRsi'] ?? 'unavailable'}; current RSI: ${row['rsi'] ?? 'unavailable'}.`;
    else if (row['divergenceType']) meaning = row['direction'] === 'BULLISH' ? 'Regular bullish divergence: price formed a lower pivot low while RSI formed a higher pivot low. The pivot needs subsequent bars to confirm; the detection time is later than the pivot.' : 'Regular bearish divergence: price formed a higher pivot high while RSI formed a lower pivot high. The pivot needs subsequent bars to confirm; the detection time is later than the pivot.';
    else if (strategy === 'ghost_rider') meaning = `Pine setup ${row['signal'] ?? ''}, state ${row['state'] ?? 'unavailable'}. Entry, stop and target levels refer to that setup. Directional votes measure indicator agreement. ${row['decisionReason'] ?? ''}${row['stopTouched'] ? ' Stop has been touched; the script still retains the historical setup.' : ''}`;
    else if (strategy === 'suryavanshi') meaning = `Suryavanshi setup state: ${row['state'] ?? 'unavailable'}. Entry, stop and target are the script's calculated levels. Winning/losing counts are historical script outcomes.`;
    else if (strategy === 'sutradhar') meaning = 'Flow, Crest, Crown, Value, Base, Origin, Mid and O are reference levels derived from the daily open and previous daily ranges. They do not define an entry, stop or target.';
    else if (strategy === 'opening_range_breakout') meaning = `Opening range ${row['orbMinutes'] ?? this.numericParam('orb_minutes',15)} minutes from 09:15 IST. High: ${this.ghostPrice(row['orbHigh'])}; low: ${this.ghostPrice(row['orbLow'])}. Held ${row['orbHeldBars'] ?? 'unavailable'} completed 5m bars. ${row['orbReason'] ?? row['decisionReason'] ?? ''}`;
    const checks = Object.entries((row['confirmationChecks'] ?? {}) as Record<string, unknown>).map(([label, passed]) => `${passed ? 'Pass' : 'Fail'}: ${label}`).join('\n');
    const asOf = row['asOf'] ?? row['matchedSince'];
    return [meaning, `${this.timeframe} timeframe; moving-average periods count candles.`, metrics, checks, this.describeStrategyResult(row), asOf ? `Data as of ${this.signalDate(asOf)} IST.` : ''].filter(Boolean).join('\n');
  }

  private strategySignalBadges(row: Record<string, unknown>): SignalBadge[] {
    const context = this.signalContext(row);
    return this.buildSignalBadges(row).map(badge => ({ ...badge, explanation: badge.explanation ?? `${badge.passed == null ? '' : badge.passed ? 'Pass: ' : 'Fail: '}${badge.label}\n${context}` }));
  }

  private buildSignalBadges(row: Record<string, unknown>): SignalBadge[] {
    if(row['strategyId']==='institution_transaction') {
      const views = row['pressureViews'] as Record<string, {state:string;relativeVolume:number|null;support:number|null;resistance:number|null;structure:string;reason:string}>;
      return [...['1d','1h'].map(frame => ({label:`${frame === '1d' ? 'Daily' : '1 Hour'}: ${views?.[frame]?.state ?? 'UNAVAILABLE'}`,tone:views?.[frame]?.state === 'BUYING' ? 'positive' as const : views?.[frame]?.state === 'SELLING' ? 'negative' as const : 'neutral' as const})),
        {label:'Disclosures: Not checked',tone:'neutral' as const}];
    }
    if(row['strategyId']==='suryavanshi')return [{label:`${row['state']} - Signal ${this.signalDate(row['signalAt'])}`},{label:`Winning ${row['winningTrades']} / Losing ${row['losingTrades']}`}];
    if(row['strategyId']==='sutradhar')return [{label:`Daily-open reference levels - ${this.signalDate(row['asOf'])}`},{label:'No entry, stop, target or holding rule in source script'}];
    if (row['strategyId'] === 'ghost_rider') return [{ label: `${row['state']} · Signal ${this.signalDate(row['signalAt'])} · ${row['ageBars']} bars ago` }, { label: `As of ${this.signalDate(row['asOf'])}` }, { label: row['atrAtSignal']==null ? 'ATR warming up at signal' : `Signal ATR ${Number(row['atrAtSignal']).toFixed(2)}` },{label:`${row['bias']} · Pullers ${row['bullPct']}% · Draggers ${row['bearPct']}%`}, ...(row['stopTouched'] ? [{ label: 'Stop touched; script retains setup', tone: 'negative' as const }] : []), ...[1,2,3,4,5].filter(n => row['tp'+n+'Hit']).map(n => ({ label: `TP${n} touched`, tone: 'positive' as const }))];
    if (row['divergenceType']) {
      const bullish = row['direction'] === 'BULLISH';
      const date = (value: unknown) => this.signalDate(value);
      return [
        { label: String(row['divergenceType']).replaceAll('_', ' '), tone: bullish ? 'positive' : 'negative' },
        { label: `Price ${this.formatPrice(Number(row['pivot1Price']))} → ${this.formatPrice(Number(row['pivot2Price']))}` },
        { label: `RSI ${Number(row['pivot1Rsi']).toFixed(2)} → ${Number(row['pivot2Rsi']).toFixed(2)}` },
        { label: `Current RSI ${Number(row['rsi']).toFixed(2)}` },
        { label: `Pivots ${date(row['pivot1At'])} → ${date(row['pivot2At'])}` },
        { label: `Detected ${date(row['detectedAt'])} · ${Number(row['ageBars'])} bars old` },

        { label: `Stored data ${date(row['asOf'])}` },
        ...(row['extremeContext'] ? [{ label: bullish ? 'Oversold pivot context' : 'Overbought pivot context' }] : []),
      ];
    }
    if (row['classification']) {
      const classification = String(row['classification']);
      const tone: SignalBadge['tone'] = classification.startsWith('STRONG_BULLISH') || classification.startsWith('CONFIRMED_BULLISH') ? 'positive'
        : classification === 'BEARISH_WARNING' ? 'negative' : 'neutral';
      const badges: SignalBadge[] = [
        { label: classification.replaceAll('_', ' '), tone },
        { label: `${Number(row['confirmationCount'] ?? 0)}/${Number(row['confirmationTotal'] ?? 5)} confirmations` },
      ];
      for (const [label, passed] of Object.entries((row['confirmationChecks'] ?? {}) as Record<string, unknown>)) {
        badges.push({ label, passed: Boolean(passed) });
      }
      if (row['breakoutDescription']) badges.push({ label: String(row['breakoutDescription']), passed: Boolean(row['breakoutCheck']) });
      if (row['signalSince']) badges.push({ label: `Bullish since ${new Date(String(row['signalSince'])).toLocaleDateString()}`, tone: 'positive' });
      return badges;
    }
    if (row['crossType'] !== 'GOLDEN_CROSS' && row['crossType'] !== 'DEATH_CROSS') return [];
    const cross = row['crossType'] === 'GOLDEN_CROSS' ? 'Golden Cross · BUY' : 'Death Cross · SELL';
    const rawState = String(row['state'] ?? '');
    const state = rawState.replaceAll('_', ' ');
    const stateTone: SignalBadge['tone'] = rawState.includes('WEAKENED') ? 'negative' : rawState === 'CONFIRMED' || rawState === 'CONFIRMED_ACTIVE' ? 'positive' : 'neutral';
    const explanation = this.describeCross(row);
    const states: Record<string, string> = {
      CROSS: 'New SMA crossover on the latest completed candle.',
      CROSS_ACTIVE: 'An earlier SMA crossover remains the latest cross. This does not mean a fresh crossing on this candle.',
      WATCH: 'A recent SMA cross was detected, but all six confirmation checks have not passed together.',
      CONFIRMED: 'All six confirmation checks passed together and triggered confirmation.',
      CONFIRMED_ACTIVE: 'The crossover was confirmed earlier and all six checks still pass.',
      CONFIRMED_WEAKENED: 'The crossover was confirmed earlier, but at least one confirmation check no longer passes.',
      EXPIRED: 'The cross exceeded the configured confirmation window without confirmation.',
    };
    const badges: SignalBadge[] = [
      { label: cross, tone: row['crossType'] === 'GOLDEN_CROSS' ? 'positive' : 'negative', explanation },
      ...(row['requireConfirmation'] ? [{ label: `${Number(row['confirmationCount'] ?? 0)}/6 confirmations`, tone: Number(row['confirmationCount'] ?? 0) === 6 ? 'positive' as const : 'neutral' as const, explanation: `${explanation}\n${Object.entries((row['confirmationChecks'] ?? {}) as Record<string, unknown>).map(([label, passed]) => `${passed ? 'Pass' : 'Fail'}: ${label}`).join('\n')}` }] : [{label:'Classic crossover',tone:'neutral' as const, explanation}]),
      { label: state, tone: stateTone, explanation: `${states[rawState] ?? state}\n${explanation}` },
    ];
    for (const [label, passed] of Object.entries((row['confirmationChecks'] ?? {}) as Record<string, unknown>)) {
      badges.push({ label, passed: Boolean(passed), explanation: `${passed ? 'Pass' : 'Fail'} on the latest completed ${this.timeframe} candle: ${label}.\n${explanation}` });
    }
    if (row['crossTime']) badges.push({ label: `Cross: ${new Date(String(row['crossTime'])).toLocaleDateString()}`, tone: 'neutral' });
    if (row['confirmationTime']) badges.push({ label: `Confirmed: ${new Date(String(row['confirmationTime'])).toLocaleDateString()}`, tone: 'positive' });
    return badges;
  }

  private renderSignalDetails(row?: ScreenResult, cellValue?: unknown): HTMLElement | string {
    if (!row) return String(cellValue ?? 'No signal data');
    if (!row.signalMetrics?.length && !row.signalBadges?.length) {
      const hint = document.createElement('span');
      hint.style.cssText = 'display:inline-flex;align-items:center;padding:4px 7px;border:1px solid #4b4226;border-radius:4px;background:#282316;color:#e6c45b;font-size:10px;';
      hint.textContent = String(row.detail || cellValue || 'EMA/SMA data unavailable');
      hint.title=hint.textContent;hint.style.maxWidth='100%';hint.style.overflow='hidden';hint.style.whiteSpace='nowrap';
      return hint;
    }
    const container = document.createElement('div');
    container.style.cssText = 'display:flex;flex-wrap:nowrap;align-items:center;gap:5px;height:100%;overflow:hidden;white-space:nowrap;';
    const orderedSignals = (row.signalMetrics ?? []).filter((signal) => signal.compareToClose);
    let previous = { label: 'Close', value: row.price };
    for (const signal of orderedSignals) {
      const isAbove = previous.value > signal.value;
      const borderColor = isAbove ? '#235b46' : '#684044';
      const backgroundColor = isAbove ? '#123326' : '#321c20';
      const textColor = isAbove ? '#66d2a6' : '#ec8c91';
      const tag = document.createElement('span');
      tag.style.cssText = `display:inline-flex;align-items:center;padding:3px 6px;border:1px solid ${borderColor};border-radius:4px;background:${backgroundColor};color:${textColor};font-size:10px;line-height:1.4;font-variant-numeric:tabular-nums;`;
      tag.textContent = `${previous.label} \u20B9${this.formatPrice(previous.value)} ${isAbove ? '>' : '<='} ${signal.label} \u20B9${this.formatPrice(signal.value)}`;
      tag.title = `${previous.label} is ${previous.value > signal.value ? 'above' : previous.value < signal.value ? 'below' : 'equal to'} ${signal.label}. This compares current values; it does not establish a fresh crossover.\n${row.signalExplanation ?? row.detail ?? ''}`;
      tag.style.cursor = 'help';
      tag.tabIndex = 0; tag.setAttribute('aria-label', tag.title);
      container.append(tag);
      previous = { label: signal.label, value: signal.value };
    }
    for (const metric of (row.signalMetrics ?? []).filter(metric => !metric.compareToClose)) {
      const tag = document.createElement('span');
      tag.textContent = `${metric.label}: ${metric.label === 'RSI' ? metric.value.toFixed(2) : this.formatPrice(metric.value)}`;
      tag.style.cssText = 'display:inline-flex;align-items:center;padding:3px 6px;border:1px solid #35454c;border-radius:4px;color:#d4d6dc;font-size:10px;line-height:1.4;cursor:help;';
      tag.title = `${tag.textContent}\n${row.signalExplanation ?? row.detail ?? ''}`;
      tag.tabIndex = 0; tag.setAttribute('aria-label', tag.title);
      container.append(tag);
    }
    if (row.detail && row.source === 'database') {
      const note = document.createElement('span');
      note.style.cssText = 'display:inline-flex;align-items:center;padding:3px 6px;border:1px solid #4b4226;border-radius:4px;background:#282316;color:#e6c45b;font-size:10px;line-height:1.4;';
      note.textContent = row.detail;
      container.append(note);
    }
    for (const badge of row.signalBadges ?? []) {
      const positive = badge.passed === true || badge.tone === 'positive';
      const negative = badge.passed === false || badge.tone === 'negative';
      const border = positive ? '#235b46' : negative ? '#684044' : '#4b4226';
      const background = positive ? '#123326' : negative ? '#321c20' : '#282316';
      const color = positive ? '#66d2a6' : negative ? '#ec8c91' : '#e6c45b';
      const tag = document.createElement('span');
      tag.style.cssText = `display:inline-flex;align-items:center;padding:3px 6px;border:1px solid ${border};border-radius:4px;background:${background};color:${color};font-size:10px;line-height:1.4;white-space:normal;`;
      tag.textContent = `${badge.passed === true ? '✓ ' : badge.passed === false ? '✕ ' : ''}${badge.label}`;
      tag.title = badge.explanation ?? `${badge.label}${row.detail ? '\n' + row.detail : ''}`;
      tag.tabIndex = 0;
      tag.setAttribute('aria-label', tag.title);
      tag.style.cursor = 'help';
      container.append(tag);
    }
    container.title = [row.detail, ...(row.signalMetrics ?? []).map(metric => `${metric.label}: ${metric.label === 'RSI' ? metric.value.toFixed(2) : this.formatPrice(metric.value)}`), ...Array.from(container.children).map(tag => tag.textContent)].filter(Boolean).join('\n');
    for(const tag of Array.from(container.children)) (tag as HTMLElement).style.flexShrink='0';
    return container.childElementCount ? container : String(cellValue || row.detail || 'Signal details unavailable');
  }

  private classifySector(symbol: string, name: string): string {
    const key = symbol.toUpperCase().replace(/[^A-Z0-9]/g, ''); const company = name.toUpperCase();
    const groups: Record<string, string[]> = {
      'Banking & Finance': ['HDFCBANK','ICICIBANK','SBIN','KOTAKBANK','AXISBANK','BANKBARODA','PNB','CANBK','INDUSINDBK','IDFCFIRSTB','FEDERALBNK','BAJFINANCE','BAJAJFINSV','SHRIRAMFIN','CHOLAFIN','MUTHOOTFIN','JIOFIN','HDFCLIFE','SBILIFE','ICICIPRULI','LICI'],
      'IT & Software': ['TCS','INFY','WIPRO','HCLTECH','TECHM','LTIM','LTTS','PERSISTENT','COFORGE','MPHASIS','OFSS','KPITTECH','TATAELXSI'],
      Pharmaceuticals: ['SUNPHARMA','DRREDDY','CIPLA','DIVISLAB','TORNTPHARM','LUPIN','AUROPHARMA','ZYDUSLIFE','BIOCON','ALKEM','MANKIND','GLENMARK'],
      Automobile: ['TATAMOTORS','MM','MARUTI','BAJAJAUTO','EICHERMOT','HEROMOTOCO','TVSMOTOR','ASHOKLEY','BHARATFORG'],
      'Energy & Oil': ['RELIANCE','ONGC','IOC','BPCL','HINDPETRO','GAIL','OIL','PETRONET','NTPC','POWERGRID','ADANIGREEN','TATAPOWER'],
      'Metals & Mining': ['TATASTEEL','HINDALCO','JSWSTEEL','VEDL','COALINDIA','NMDC','SAIL','HINDZINC','NATIONALUM'],
      FMCG: ['ITC','HINDUNILVR','NESTLEIND','BRITANNIA','DABUR','GODREJCP','MARICO','TATACONSUM','COLPAL','UNITDSPR','VBL'],
      Telecom: ['BHARTIARTL','IDEA','HFCL','INDUSTOWER','TATACOMM'],
      'Infrastructure & Capital Goods': ['LT','SIEMENS','ABB','BEL','HAL','BHEL','RVNL','IRFC','ADANIPORTS','CUMMINSIND','POLYCAB'],
      'Real Estate': ['DLF','GODREJPROP','PRESTIGE','OBEROIRLTY','PHOENIXLTD','LODHA','BRIGADE','SOBHA'],
    };
    for (const [sector, tickers] of Object.entries(groups)) if (tickers.includes(key)) return sector;
    if (/BANK|FINANC|INSUR/.test(company)) return 'Banking & Finance';
    if (/SOFTWARE|TECHNOLOG/.test(company)) return 'IT & Software';
    if (/PHARMA|DRUG|THERAPEUT/.test(company)) return 'Pharmaceuticals';
    if (/MOTOR|AUTOMOB|TRACTOR|TYRE/.test(company)) return 'Automobile';
    if (/OIL|PETRO|ENERGY|POWER|GAS/.test(company)) return 'Energy & Oil';
    if (/STEEL|METAL|MINING|ALUMIN|ZINC|COPPER/.test(company)) return 'Metals & Mining';
    if (/FOOD|BEVERAGE|CONSUMER|TOBACCO/.test(company)) return 'FMCG';
    if (/TELECOM|TELECOMMUNICATION|WIRELESS/.test(company)) return 'Telecom';
    if (/INFRA|ENGINEER|CONSTRUCTION|INDUSTRIAL/.test(company)) return 'Infrastructure & Capital Goods';
    if (/REALTY|REAL ESTATE|PROPERT|HOUSING/.test(company)) return 'Real Estate';
    return 'Other';
  }

  private fail(error: HttpErrorResponse): void {
    this.loading = false;
    this.error = typeof error.error?.detail === 'string' ? error.error.detail : error.message || 'The market scan could not be completed.';
  }

  saveScreener(): void {
    const name = this.saveName.trim();
    if (!name) return;
    const item = { name, strategyId: this.selectedStrategy, timeframe: this.timeframe, factors: this.rules.map((rule) => ({ ...rule })), sector: this.selectedSector, strategyParams: { ...this.strategyParams } };
    this.savedScreeners = [...this.savedScreeners.filter((saved) => saved.name !== name), item];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(this.savedScreeners));
    this.saveName = '';
    this.selectedSaved = name;
  }

  loadScreener(name: string): void {
    const item = this.savedScreeners.find((saved) => saved.name === name);
    if (!item) return;
    this.scanSubscription?.unsubscribe(); this.loading = false; this.clearRightFilters();
    this.selectedSaved = name; this.selectStrategy(item.strategyId, false); this.timeframe = ['ghost_rider','rsi_divergence','golden_death_cross'].includes(item.strategyId) && !['1d','1h','15m','5m'].includes(item.timeframe) ? '1d' : item.timeframe;
    if(item.strategyId==='market_screener')this.timeframe='1d';
    if(item.strategyId==='institution_transaction'&&!['1d','1h'].includes(this.timeframe))this.timeframe='1d';
    if(item.strategyId==='suryavanshi'&&!['1d','1h','15m','5m'].includes(this.timeframe))this.timeframe='15m';
    if(item.strategyId==='sutradhar'&&!['1h','15m','5m'].includes(this.timeframe))this.timeframe='15m';
    if(item.strategyId==='opening_range_breakout')this.timeframe='5m';
    if(item.strategyId==='opening_range_breakout')this.timeframe='5m';
    this.strategyParams = Object.fromEntries((this.activeStrategy?.parameters ?? []).filter(p=>['number','boolean','string'].includes(typeof p.default)).map(p=>{
      const saved=item.strategyParams?.[p.name];
      if(p.type==='str')return [p.name,typeof saved==='string'&&p.options?.includes(saved)?saved:p.default as string];
      if(p.type==='bool')return [p.name,typeof saved==='boolean'?saved:p.default as boolean];
      return [p.name,typeof saved==='number' && Number.isFinite(saved) && (p.min_value==null || saved>=p.min_value) && (p.max_value==null || saved<=p.max_value) ? saved : p.default as number];
    }));
    this.rules = item.factors.map((rule) => ({ ...rule })); this.selectedSector = item.sector ?? 'All sectors'; this.results = []; this.hasScanned = false;
    this.refreshSelection();
  }

  deleteScreener(): void {
    this.savedScreeners = this.savedScreeners.filter((item) => item.name !== this.selectedSaved);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(this.savedScreeners)); this.selectedSaved = '';
  }

  formatPrice(value: number): string { return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value); }
  private ghostPrice(value: unknown): string { return value==null ? '—' : this.formatPrice(Number(value)); }
  private signalDate(value: unknown): string { return new Date(String(value)).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', year: 'numeric', ...(['5m','15m','1h'].includes(this.timeframe)?{hour:'2-digit' as const,minute:'2-digit' as const}:{}) }); }
  formatVolume(value: number): string { return new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 }).format(value); }
  private readSaved(): SavedScreener[] { try { return (JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as SavedScreener[]).filter(item => !item.market || item.market === 'equities'); } catch { return []; } }
}
