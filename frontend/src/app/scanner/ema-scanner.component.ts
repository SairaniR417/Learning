import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, EventEmitter, Output, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { AgGridAngular } from 'ag-grid-angular';
import { CellStyleModule, ClientSideRowModelModule, ColDef, ColumnApiModule, GridApi, GridReadyEvent, ICellRendererParams, ModuleRegistry, NumberFilterModule, PaginationModule, QuickFilterModule, TextFilterModule, colorSchemeDark, themeQuartz } from 'ag-grid-community';
import { MarketApiService, MarketAssetQuote, ScannerStrategy, SelectedStock } from '../market-api.service';

type FactorField = 'changePct' | 'volume' | 'price';
interface FactorRule { field: FactorField; min: string; max: string; importance: 'Important' | 'Optional'; }
interface SavedScreener { name: string; strategyId: string; timeframe: string; factors: FactorRule[]; sector?: string; strategyParams?: Record<string, number>; market?: string; }
interface SignalMetric { label: string; value: number; compareToClose: boolean; }
interface SignalBadge { label: string; passed?: boolean; tone?: 'positive' | 'negative' | 'neutral'; }
interface ScreenResult { entry?: number; stopLoss?: number; tp1?: number; tp2?: number; tp3?: number; tp4?: number; tp5?: number; setupState?: string; instrumentKey: string; exchange: string; symbol: string; name: string; price: number; changePct: number | null; volume: number; status: string; signal?: string; state?: string; divergenceType?: string; source: 'database' | 'strategy'; detail?: string; signalMetrics?: SignalMetric[]; signalBadges?: SignalBadge[]; sector: string; }
interface GridColumnOption { id: string; label: string; visible: boolean; }
const STORAGE_KEY = 'traders-gita-saved-screeners';
ModuleRegistry.registerModules([ClientSideRowModelModule, ColumnApiModule, TextFilterModule, NumberFilterModule, QuickFilterModule, PaginationModule, CellStyleModule]);

@Component({ selector: 'app-ema-scanner', standalone: true, imports: [CommonModule, AgGridAngular], templateUrl: './ema-scanner.component.html', styleUrl: './ema-scanner.component.css' })
export class EmaScannerComponent implements OnInit, OnDestroy {
  @Output() stockSelected = new EventEmitter<SelectedStock>();
  openStock(row: ScreenResult | undefined): void {
    if (!row?.instrumentKey) return;
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
  selectedStrategy = 'market_screener';
  timeframe = '1d';
  strategyParams: Record<string, number> = {};
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
  private gridApi?: GridApi<ScreenResult>;
  readonly gridColumns: GridColumnOption[] = [
    { id: 'status', label: 'Status', visible: true }, { id: 'symbolCompany', label: 'Symbol / Company', visible: true },
    { id: 'changePct', label: 'Change %', visible: false }, { id: 'volume', label: 'Volume', visible: false },
    { id: 'price', label: 'Last price', visible: true }, { id: 'sector', label: 'Sector', visible: false },
    { id: 'detail', label: 'Signal details', visible: true },
    ...['setupState', 'entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5'].map(id => ({ id, label: id === 'setupState' ? 'Setup' : id === 'stopLoss' ? 'Stop loss' : id.toUpperCase(), visible: false })),
  ];
  rightFilters = { symbol: '', status: '', sector: '', divergence: '', changeMin: '', changeMax: '', volumeMin: '', volumeMax: '', priceMin: '', priceMax: '' };
  private filteredRowsSource?: ScreenResult[];
  private filteredRowsSettings?: EmaScannerComponent['rightFilters'];
  private filteredRowsSector = '';
  private filteredRowsCache: ScreenResult[] = [];
  readonly gridTheme = themeQuartz.withPart(colorSchemeDark).withParams({
    backgroundColor: '#101116', foregroundColor: '#d4d6dc', headerBackgroundColor: '#191a22',
    headerTextColor: '#a0a4af', borderColor: '#2b2d37', rowHoverColor: '#1c2423',
    accentColor: '#e0bd43', fontFamily: 'Inter, Segoe UI, Arial, sans-serif', fontSize: 11, spacing: 6
  });
  readonly defaultColDef: ColDef<ScreenResult> = { sortable: true, filter: true, floatingFilter: false, resizable: true, minWidth: 100 };
  readonly columnDefs: ColDef<ScreenResult>[] = [
    { headerName: '#', valueGetter: (p) => (p.node?.rowIndex ?? 0) + 1, width: 58, maxWidth: 65, sortable: false, filter: false, floatingFilter: false, pinned: 'left' },
    { field: 'status', headerName: 'Status', width: 195, pinned: 'left', valueFormatter: (p) => p.value === 'NEWLY_ALIGNED' ? 'NEW MATCH' : String(p.value ?? ''), cellStyle: (p) => ['BULLISH CONFIRMED', 'STRONG BULLISH', 'STRONG BULLISH ACTIVE', 'CONFIRMED BULLISH', 'CONFIRMED BULLISH ACTIVE', 'BUY', 'PREVIOUS SIGNAL'].includes(String(p.value)) ? { color: '#55c99f', fontWeight: '700' } : ['BEARISH CONFIRMED', 'BEARISH WATCH', 'BEARISH WARNING', 'SELL', 'WEAKENED'].includes(String(p.value)) ? { color: '#ec8c91', fontWeight: '700' } : ['EARLY BULLISH', 'BULLISH WATCH', 'WATCH', 'NEWLY_ALIGNED'].includes(String(p.value)) ? { color: '#edc74f', fontWeight: '700' } : p.value === 'PREFERRED' ? { color: '#edd36a', fontWeight: '700' } : { color: '#a4a8b2', fontWeight: '700' } },
    { headerName: 'Symbol / Company', colId: 'symbolCompany', valueGetter: (p) => p.data ? (p.data.name && p.data.name !== p.data.symbol ? `${p.data.symbol} · ${p.data.name}` : p.data.symbol) : '', minWidth: 220, flex: 1, filter: 'agTextColumnFilter', cellClass: 'symbol-company-cell', cellRenderer: (p: ICellRendererParams<ScreenResult>) => {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = String(p.value ?? ''); button.title = 'Open stock details';
      button.style.cssText = 'background:none;border:0;color:#e0bd43;cursor:pointer;text-align:left;padding:0;font:inherit;';
      button.addEventListener('click', event => { event.stopPropagation(); this.openStock(p.data); }); return button;
    } },
    { field: 'changePct', headerName: 'Change %', width: 115, filter: 'agNumberColumnFilter', valueFormatter: (p) => p.value == null ? '—' : `${Number(p.value).toFixed(2)}%`, cellStyle: (p) => Number(p.value) > 0 ? { color: '#45c89c' } : Number(p.value) < 0 ? { color: '#e3737b' } : null },
    { field: 'volume', headerName: 'Volume', width: 115, filter: 'agNumberColumnFilter', valueFormatter: (p) => this.formatVolume(Number(p.value ?? 0)) },
    { field: 'price', headerName: 'Last', width: 140, filter: 'agNumberColumnFilter', valueFormatter: (p) => Number(p.value) ? this.formatPrice(Number(p.value)) : '—' },
    { field: 'sector', headerName: 'Sector', minWidth: 165, filter: 'agTextColumnFilter' },
    { field: 'setupState', headerName: 'Setup', width: 100 },
    ...(['entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5'] as const).map(field => ({ field, headerName: field === 'stopLoss' ? 'Stop loss' : field.toUpperCase(), width: 120, filter: 'agNumberColumnFilter', cellRenderer: (p: ICellRendererParams<ScreenResult>) => { const span = document.createElement('span'); const hit = field.startsWith('tp') && (p.data as unknown as Record<string, unknown>)?.[field + 'Hit']; span.textContent = p.value == null ? '?' : this.formatPrice(Number(p.value)) + (hit ? ' ?' : ''); span.style.color = hit ? '#40e0d0' : field === 'stopLoss' ? '#ec8c91' : '#d4d6dc'; return span; } })),
    { field: 'detail', headerName: 'Signal details', minWidth: 520, flex: 2, autoHeight: true, wrapText: true, filter: 'agTextColumnFilter', cellRenderer: (p: ICellRendererParams<ScreenResult, string | undefined>) => this.renderSignalDetails(p.data, p.value) },
  ];

  ngOnInit(): void {
    this.api.fnoStocks().subscribe({ next: data => this.universeCount = data.total });
    this.strategySubscription = this.api.scannerStrategies().subscribe({
      next: ({ strategies }) => { this.strategies = strategies; this.loadingStrategies = false; },
      error: () => { this.loadingStrategies = false; }
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

  selectStrategy(value: string): void {
    this.scanSubscription?.unsubscribe(); this.loading = false; this.totalScanned = 0;
    this.selectedStrategy = value; this.results = []; this.hasScanned = false; this.error = '';
    for (const column of this.gridColumns.filter(c => ['setupState', 'entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5'].includes(c.id))) { column.visible = value === 'ghost_rider'; this.gridApi?.setColumnsVisible([column.id], column.visible); }
    if ((value === 'rsi_divergence' || value === 'ghost_rider')) this.timeframe = '1d';
    this.strategyParams = Object.fromEntries((this.activeStrategy?.parameters ?? []).filter((item) => typeof item.default === 'number').map((item) => [item.name, item.default as number]));
  }
  updateStrategyParam(key: string, value: string): void { this.strategyParams[key] = Number(value); }
  selectSector(value: string): void { this.selectedSector = value; }
  onGridReady(event: GridReadyEvent<ScreenResult>): void {
    this.gridApi = event.api;
    for (const column of this.gridColumns) event.api.setColumnsVisible([column.id], column.visible);
  }
  setGridColumnVisible(column: GridColumnOption, visible: boolean): void {
    column.visible = visible;
    this.gridApi?.setColumnsVisible([column.id], visible);
  }
  toggleGridPanel(panel: 'columns' | 'filters'): void { this.gridPanel = this.gridPanel === panel ? '' : panel; }
  clearRightFilters(): void { this.rightFilters = { symbol: '', status: '', sector: '', divergence: '', changeMin: '', changeMax: '', volumeMin: '', volumeMax: '', priceMin: '', priceMax: '' }; }
  setRightFilter(key: keyof EmaScannerComponent['rightFilters'], value: string): void { this.rightFilters = { ...this.rightFilters, [key]: value }; }

  scan(): void {
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
            ...Object.fromEntries(['entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5', 'tp1Hit', 'tp2Hit', 'tp3Hit', 'tp4Hit', 'tp5Hit'].map(key => [key, row[key]])), setupState: row['strategyId'] === 'ghost_rider' ? String(row['state']) : undefined, source: 'strategy', detail: this.describeStrategyResult(row), signalMetrics: this.strategySignalMetrics(row), signalBadges: this.strategySignalBadges(row), sector: this.classifySector(String(row['symbol'] ?? ''), String(row['name'] ?? '')) };
        });
        this.loading = false;
      }, error: (error: HttpErrorResponse) => this.fail(error)
    });
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
    if (row['strategyId'] === 'ghost_rider') return `Ghost Rider ${row['signal']} ? ${row['state']} ? Signal ${this.signalDate(row['signalAt'])} ? Entry ${this.formatPrice(Number(row['entry']))} ? Stop ${this.formatPrice(Number(row['stopLoss']))} ? TP1?TP5: ${[1,2,3,4,5].map(n => this.formatPrice(Number(row['tp'+n]))).join(', ')}`;
    if (row['divergenceType']) return `${String(row['divergenceType']).replaceAll('_', ' ')} · ${String(row['status'])} · Price ${this.formatPrice(Number(row['pivot1Price']))} → ${this.formatPrice(Number(row['pivot2Price']))} · RSI ${Number(row['pivot1Rsi']).toFixed(2)} → ${Number(row['pivot2Rsi']).toFixed(2)} · Trigger ${this.formatPrice(Number(row['triggerPrice']))} · Invalid below/above ${this.formatPrice(Number(row['invalidationPrice']))} · Detected ${this.signalDate(row['detectedAt'])} · As of ${this.signalDate(row['asOf'])}`;
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
    if (row['strategyId'] === 'ghost_rider') return ['entry', 'stopLoss', 'tp1', 'tp2', 'tp3', 'tp4', 'tp5'].map(key => ({ label: key === 'stopLoss' ? 'Stop loss' : key.toUpperCase(), value: Number(row[key]), compareToClose: false }));
    const fast = Number(row['emaFastPeriod'] ?? 9), slow = Number(row['emaSlowPeriod'] ?? 20);
    const medium = Number(row['smaMediumPeriod'] ?? 50), long = Number(row['smaLongPeriod'] ?? 200);
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

  private strategySignalBadges(row: Record<string, unknown>): SignalBadge[] {
    if (row['strategyId'] === 'ghost_rider') return [{ label: `${row['state']} ? Signal ${this.signalDate(row['signalAt'])} ? ${row['ageBars']} bars ago` }, { label: `As of ${this.signalDate(row['asOf'])}` }, { label: `Signal ATR ${Number(row['atrAtSignal']).toFixed(2)}` }, ...(row['stopTouched'] ? [{ label: 'Stop touched; script retains setup', tone: 'negative' as const }] : []), ...[1,2,3,4,5].filter(n => row['tp'+n+'Hit']).map(n => ({ label: `TP${n} touched`, tone: 'positive' as const }))];
    if (row['divergenceType']) {
      const bullish = row['direction'] === 'BULLISH';
      const date = (value: unknown) => this.signalDate(value);
      return [
        { label: String(row['divergenceType']).replaceAll('_', ' '), tone: bullish ? 'positive' : 'negative' },
        { label: `Price ${this.formatPrice(Number(row['pivot1Price']))} → ${this.formatPrice(Number(row['pivot2Price']))}` },
        { label: `RSI ${Number(row['pivot1Rsi']).toFixed(2)} → ${Number(row['pivot2Rsi']).toFixed(2)}` },
        { label: `Current RSI ${Number(row['rsi']).toFixed(2)}` },
        { label: `Pivots ${date(row['pivot1At'])} → ${date(row['pivot2At'])}` },
        { label: `${row['state'] === 'CONFIRMED' ? 'Breakout confirmed' : 'Await close'} ${bullish ? 'above' : 'below'} ${this.formatPrice(Number(row['triggerPrice']))}`, tone: row['state'] === 'CONFIRMED' ? (bullish ? 'positive' : 'negative') : 'neutral' },
        { label: `Invalid ${bullish ? 'below' : 'above'} ${this.formatPrice(Number(row['invalidationPrice']))}` },
        { label: `Detected ${date(row['detectedAt'])} · ${Number(row['ageBars'])} bars old` },
        ...(row['confirmedAt'] ? [{ label: `Confirmed ${date(row['confirmedAt'])}` }] : []),
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
    const badges: SignalBadge[] = [
      { label: cross, tone: row['crossType'] === 'GOLDEN_CROSS' ? 'positive' : 'negative' },
      { label: `${Number(row['confirmationCount'] ?? 0)}/6 confirmations`, tone: Number(row['confirmationCount'] ?? 0) === 6 ? 'positive' : 'neutral' },
      { label: state, tone: stateTone },
    ];
    for (const [label, passed] of Object.entries((row['confirmationChecks'] ?? {}) as Record<string, unknown>)) {
      badges.push({ label, passed: Boolean(passed) });
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
      return hint;
    }
    const container = document.createElement('div');
    container.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px;padding:6px 0;white-space:normal;';
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
      container.append(tag);
      previous = { label: signal.label, value: signal.value };
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
      container.append(tag);
    }
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
    this.selectedSaved = name; this.selectStrategy(item.strategyId); this.timeframe = ['rsi_divergence', 'ghost_rider'].includes(item.strategyId) ? '1d' : item.timeframe;
    this.strategyParams = item.strategyParams ?? Object.fromEntries((this.activeStrategy?.parameters ?? []).filter((parameter) => typeof parameter.default === 'number').map((parameter) => [parameter.name, parameter.default as number]));
    this.rules = item.factors.map((rule) => ({ ...rule })); this.selectedSector = item.sector ?? 'All sectors'; this.results = []; this.hasScanned = false;
  }

  deleteScreener(): void {
    this.savedScreeners = this.savedScreeners.filter((item) => item.name !== this.selectedSaved);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(this.savedScreeners)); this.selectedSaved = '';
  }

  formatPrice(value: number): string { return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value); }
  private signalDate(value: unknown): string { return new Date(String(value)).toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', year: 'numeric' }); }
  formatVolume(value: number): string { return new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 }).format(value); }
  private readSaved(): SavedScreener[] { try { return (JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as SavedScreener[]).filter(item => !item.market || item.market === 'equities'); } catch { return []; } }
}
