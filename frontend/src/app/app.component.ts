import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Subscription, timer } from 'rxjs';
import { AlertNotificationsService } from './alert-notifications.service';
import { WatchlistComponent } from './watchlist/watchlist.component';
import { TradeJournalComponent } from './trade-journal/trade-journal.component';
import { StockDetailsComponent } from './stock-details/stock-details.component';
import { EmaScannerComponent } from './scanner/ema-scanner.component';
import { FocusedComponent } from './focused/focused.component';
import { MarketApiService, MarketAssetQuote, SelectedStock } from './market-api.service';

interface DashboardAsset extends MarketAssetQuote {
  icon: string;
  priceLabel: string;
  changeLabel: string;
  color: 'up' | 'down' | 'flat';
  w: number;
  h: number;
  sector: string;
}

interface Opportunity {
  title: string;
  detail: string;
  tag: string;
}

@Component({ selector: 'app-root', standalone: true, imports: [CommonModule, EmaScannerComponent, FocusedComponent, StockDetailsComponent, WatchlistComponent, TradeJournalComponent], templateUrl: './app.component.html', styleUrl: './app.component.css' })
export class AppComponent implements OnInit, OnDestroy {
  private readonly api = inject(MarketApiService);
  readonly notifications = inject(AlertNotificationsService);
  notificationMenu = false;
  private statusSubscription?: Subscription;
  private clockSubscription?: Subscription;
  private marketSubscription?: Subscription;
  private indexSubscription?: Subscription;
  private trendKey = '';
  private readonly numberFormat = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });

  connected = false;
  clock = '';
  page = 'Overview';
  selectedStock: SelectedStock | null = null;
  openStock(stock: SelectedStock): void { this.selectedStock = stock; this.page = 'Stock Details'; }
  market: 'equities' | 'commodities' = 'equities';
  marketName = 'NSE equities';
  receivedAt = 0;
  loadingMarket = true;
  marketError = '';
  trendLoading = false;
  trendError = '';
  chartSymbol = 'NIFTY 50';
  chartPath = '';
  chartAreaPath = '';
  chartLabels: string[] = [];
  leaders: DashboardAsset[] = [];
  heatTiles: DashboardAsset[] = [];
  allHeatAssets: DashboardAsset[] = [];
  heatPage = 0;
  readonly heatPageSize = 24;
  readonly sectors = ['All sectors', 'Nifty 50', 'Bank Nifty', 'Nifty Midcap 100', 'Sensex', 'Banking & Finance', 'IT & Software', 'Pharmaceuticals', 'Automobile', 'Energy & Oil', 'Metals & Mining', 'FMCG', 'Telecom', 'Infrastructure & Capital Goods', 'Real Estate', 'Other'];
  selectedSector = 'All sectors';
  readonly indexOptions = [{ id: 'all', label: 'All stocks' }, { id: 'nifty50', label: 'Nifty 50' }, { id: 'banknifty', label: 'Bank Nifty' }, { id: 'midcap100', label: 'Nifty Midcap 100' }, { id: 'sensex', label: 'Sensex' }];
  selectedIndex = 'all';
  indexLoading = false;
  indexError = '';
  private indexIsins = new Set<string>();
  heatSearch = '';
  heatGainMax = 0;
  heatLossMax = 0;
  opportunities: Opportunity[] = [];
  pages = ['Overview', 'Market Scanner', 'Focused', 'Stock Details', 'Watchlist', 'Trade Journal'];

  ngOnInit(): void {
    this.statusSubscription = timer(0, 15000).subscribe(() => {
      if (this.page === 'Overview') this.api.status().subscribe({ next: (status) => this.connected = status.connected });
    });
    this.clockSubscription = timer(0, 1000).subscribe(() => this.clock = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date()) + ' IST');
    this.marketSubscription = timer(0, 300000).subscribe(() => {
      if (this.page === 'Overview') this.refreshMarket();
    });
  }

  ngOnDestroy(): void {
    this.statusSubscription?.unsubscribe();
    this.clockSubscription?.unsubscribe();
    this.marketSubscription?.unsubscribe();
    this.indexSubscription?.unsubscribe();
  }

  selectPage(page: string): void {
    this.page = page;
    if (page === 'Overview') {
      this.api.status().subscribe({ next: (status) => this.connected = status.connected });
      if (!this.receivedAt || Date.now() - this.receivedAt >= 300000) this.refreshMarket();
    }
  }

  selectMarket(market: 'equities' | 'commodities'): void {
    if (this.market === market) return;
    this.market = market;
    this.selectedSector = 'All sectors';
    this.indexSubscription?.unsubscribe(); this.selectedIndex = 'all'; this.indexLoading = false; this.indexError = ''; this.indexIsins.clear();
    this.heatSearch = '';
    this.heatPage = 0;
    this.allHeatAssets = [];
    this.heatTiles = [];
    this.trendKey = '';
    this.chartPath = '';
    this.chartAreaPath = '';
    this.chartLabels = [];
    this.refreshMarket();
  }

  refreshMarket(): void { // Poll live quotes for the selected Indian market.
    this.api.marketSnapshot(this.market).subscribe({
      next: (snapshot) => {
        if (snapshot.market !== this.market) return;
        this.connected = true;
        this.marketName = snapshot.name;
        this.receivedAt = snapshot.receivedAt;
        this.marketError = '';
        this.loadingMarket = false;
        const assets = snapshot.assets.map((asset, index) => this.toDashboardAsset(asset, index));
        this.leaders = [...assets]
          .sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct))
          .slice(0, 6);
        this.allHeatAssets = [...assets]
          .sort((a, b) => b.volume - a.volume);
        this.heatPage = Math.min(this.heatPage, this.heatPageCount - 1);
        this.showHeatPage();
        this.buildOpportunities(assets);
        this.chartSymbol = snapshot.chartSymbol;
        if (snapshot.chartKey && snapshot.chartKey !== this.trendKey) this.loadTrend(snapshot.chartKey);
      },
      error: (error: HttpErrorResponse) => {
        this.loadingMarket = false;
        this.marketError = typeof error.error?.detail === 'string'
          ? error.error.detail
          : 'Could not load live market quotes. Check the Upstox connection and try again.';
      }
    });
  }

  get filteredHeatAssets(): DashboardAsset[] {
    const query = this.heatSearch.trim().toLowerCase();
    return this.allHeatAssets.filter(asset =>
      (this.selectedIndex !== 'all' || this.selectedSector === 'All sectors' || asset.sector === this.selectedSector)
      && (this.selectedIndex === 'all' || this.indexIsins.has(asset.key.split('|')[1] ?? ''))
      && (!query || asset.symbol.toLowerCase().includes(query) || asset.name.toLowerCase().includes(query)));
  }
  get heatGroups(): { id: string; label: string; assets: DashboardAsset[]; count: number }[] {
    const all = this.filteredHeatAssets;
    const groups = [
      { id: 'up', label: 'Gainers', assets: all.filter(a => a.changePct > 0).sort((a, b) => b.changePct - a.changePct || a.symbol.localeCompare(b.symbol)) },
      { id: 'down', label: 'Losers', assets: all.filter(a => a.changePct < 0).sort((a, b) => a.changePct - b.changePct || a.symbol.localeCompare(b.symbol)) },
      { id: 'flat', label: 'Unchanged', assets: all.filter(a => a.changePct === 0).sort((a, b) => a.symbol.localeCompare(b.symbol)) }
    ];
    return groups.map(g => ({ ...g, count: g.assets.length }));
  }
  get visibleHeatGroups(): { id: string; label: string; assets: DashboardAsset[]; count: number }[] {
    return this.heatGroups.map(g => ({ ...g, assets: g.assets.slice(this.heatPage * this.heatPageSize, (this.heatPage + 1) * this.heatPageSize) }));
  }
  get heatPageCount(): number { return Math.max(1, ...this.heatGroups.map(g => Math.ceil(g.count / this.heatPageSize))); }
  get heatPageStart(): number { return this.filteredHeatAssets.length ? this.heatPage * this.heatPageSize + 1 : 0; }
  get heatPageEnd(): number { return Math.min((this.heatPage + 1) * this.heatPageSize, this.filteredHeatAssets.length); }
  get hasMultipleHeatPages(): boolean { return this.heatPageCount > 1; }

  selectSector(sector: string): void {
    this.selectedSector = sector;
    const index = this.indexOptions.find(option => option.label === sector);
    this.selectIndex(index?.id ?? 'all');
  }
  selectIndex(id: string): void {
    this.indexSubscription?.unsubscribe();
    this.selectedIndex = id; this.indexError = ''; this.indexIsins.clear(); this.heatPage = 0;
    this.indexLoading = id !== 'all'; this.showHeatPage();
    if (id === 'all') return;
    this.indexSubscription = this.api.indexConstituents(id).subscribe({ next: data => {
      this.indexIsins = new Set(data.members.map(member => member.isin));
      this.indexLoading = false; this.showHeatPage();
    }, error: (error: HttpErrorResponse) => {
      this.indexLoading = false; this.indexError = error.error?.detail || 'Index constituents are unavailable. Please retry.'; this.showHeatPage();
    } });
  }
  searchHeatmap(query: string): void { this.heatSearch = query; this.heatPage = 0; this.showHeatPage(); }

  prevHeatPage(): void {
    if (this.heatPage > 0) { this.heatPage--; this.showHeatPage(); }
  }

  nextHeatPage(): void {
    if (this.heatPage + 1 < this.heatPageCount) { this.heatPage++; this.showHeatPage(); }
  }

  private showHeatPage(): void {
    const assets = this.filteredHeatAssets;
    this.heatGainMax = assets.reduce((max, asset) => Number.isFinite(asset.changePct) ? Math.max(max, asset.changePct) : max, 0);
    this.heatLossMax = assets.reduce((max, asset) => Number.isFinite(asset.changePct) ? Math.max(max, -asset.changePct) : max, 0);
    this.heatPage = Math.min(this.heatPage, this.heatPageCount - 1);
    this.heatTiles = this.visibleHeatGroups.flatMap(group => group.assets);
  }

  heatColor(changePct: number): string {
    if (!Number.isFinite(changePct) || changePct === 0) return '#343b3b';
    const maximum = changePct > 0 ? this.heatGainMax : this.heatLossMax;
    const strength = Math.min(Math.abs(changePct) / (maximum || Math.abs(changePct)), 1);
    return changePct > 0 ? `hsl(153 60% ${38 - strength * 26}%)` : `hsl(354 65% ${44 - strength * 25}%)`;
  }

  private toDashboardAsset(asset: MarketAssetQuote, index: number): DashboardAsset {
    const color = asset.changePct > 0 ? 'up' : asset.changePct < 0 ? 'down' : 'flat';
    const sign = asset.changePct > 0 ? '+' : '';
    return {
      ...asset,
      icon: asset.symbol.slice(0, 2),
      priceLabel: this.numberFormat.format(asset.price),
      changeLabel: `${sign}${asset.changePct.toFixed(2)}%`,
      color,
      sector: this.market === 'commodities' ? 'Commodities' : this.classifySector(asset.symbol, asset.name),
      w: index < 3 ? 2 : 1,
      h: index < 3 ? 2 : 1,
    };
  }

  private classifySector(symbol: string, name: string): string {
    const ticker = symbol.toUpperCase().replace(/[^A-Z0-9]/g, '');
    const company = name.toUpperCase();
    const groups: Record<string, string[]> = {
      'Banking & Finance': ['HDFCBANK','ICICIBANK','SBIN','KOTAKBANK','AXISBANK','BANKBARODA','PNB','CANBK','INDUSINDBK','IDFCFIRSTB','FEDERALBNK','AUBANK','UNIONBANK','BAJFINANCE','BAJAJFINSV','SHRIRAMFIN','CHOLAFIN','MUTHOOTFIN','JIOFIN','HDFCLIFE','SBILIFE','ICICIPRULI','LICI','PAYTM','BSE','CDSL'],
      'IT & Software': ['TCS','INFY','WIPRO','HCLTECH','TECHM','LTIM','LTTS','PERSISTENT','COFORGE','MPHASIS','OFSS','KPITTECH','TATAELXSI'],
      'Pharmaceuticals': ['SUNPHARMA','DRREDDY','CIPLA','DIVISLAB','TORNTPHARM','LUPIN','AUROPHARMA','ZYDUSLIFE','BIOCON','ALKEM','MANKIND','GLENMARK'],
      'Automobile': ['TATAMOTORS','MM','MARUTI','BAJAJAUTO','EICHERMOT','HEROMOTOCO','TVSMOTOR','ASHOKLEY','BHARATFORG','BOSCHLTD'],
      'Energy & Oil': ['RELIANCE','ONGC','IOC','BPCL','HINDPETRO','GAIL','OIL','PETRONET','IGL','MGL','NTPC','POWERGRID','ADANIGREEN','TATAPOWER','JSWENERGY'],
      'Metals & Mining': ['TATASTEEL','HINDALCO','JSWSTEEL','VEDL','COALINDIA','NMDC','SAIL','HINDZINC','NATIONALUM','JINDALSTEL'],
      'FMCG': ['ITC','HINDUNILVR','NESTLEIND','BRITANNIA','DABUR','GODREJCP','MARICO','TATACONSUM','COLPAL','UNITDSPR','VBL'],
      'Telecom': ['BHARTIARTL','IDEA','HFCL','INDUSTOWER','TATACOMM'],
      'Infrastructure & Capital Goods': ['LT','SIEMENS','ABB','BEL','HAL','BHEL','RVNL','IRFC','ADANIPORTS','CUMMINSIND','POLYCAB','KEI','CGPOWER'],
      'Real Estate': ['DLF','GODREJPROP','PRESTIGE','OBEROIRLTY','PHOENIXLTD','LODHA','BRIGADE','SOBHA'],
    };
    for (const [sector, symbols] of Object.entries(groups)) if (symbols.includes(ticker)) return sector;
    if (/BANK|FINANC|INSUR|CAPITAL|BROKING|EXCHANGE/.test(company)) return 'Banking & Finance';
    if (/SOFTWARE|TECHNOLOG|INFORMATION TECHNOLOGY/.test(company)) return 'IT & Software';
    if (/PHARMA|DRUG|THERAPEUT|LIFE SCIENCE/.test(company)) return 'Pharmaceuticals';
    if (/MOTOR|AUTOMOB|AUTO PART|TRACTOR|TYRE/.test(company)) return 'Automobile';
    if (/OIL|PETRO|ENERGY|POWER|GAS|ELECTRIC/.test(company)) return 'Energy & Oil';
    if (/STEEL|METAL|MINING|ALUMINIUM|ALUMINUM|ZINC|COPPER/.test(company)) return 'Metals & Mining';
    if (/FOOD|BEVERAGE|CONSUMER|TOBACCO|PERSONAL CARE/.test(company)) return 'FMCG';
    if (/TELECOM|TELECOMMUNICATION|WIRELESS/.test(company)) return 'Telecom';
    if (/INFRA|ENGINEER|CONSTRUCTION|CAPITAL GOODS|INDUSTRIAL/.test(company)) return 'Infrastructure & Capital Goods';
    if (/REALTY|REAL ESTATE|PROPERT|HOUSING/.test(company)) return 'Real Estate';
    return 'Other';
  }

  private buildOpportunities(assets: DashboardAsset[]): void {
    const gainers = [...assets].filter((item) => item.changePct > 0).sort((a, b) => b.changePct - a.changePct);
    const decliners = [...assets].filter((item) => item.changePct < 0).sort((a, b) => a.changePct - b.changePct);
    const active = [...assets].sort((a, b) => b.volume - a.volume);
    this.opportunities = [
      ...(gainers[0] ? [{ title: `${gainers[0].symbol} leading gains`, detail: `${gainers[0].name} · ${gainers[0].changeLabel} today`, tag: 'Gainer' }] : []),
      ...(decliners[0] ? [{ title: `${decliners[0].symbol} under pressure`, detail: `${decliners[0].name} · ${decliners[0].changeLabel} today`, tag: 'Decliner' }] : []),
      ...(active[0] ? [{ title: `${active[0].symbol} most active`, detail: `${active[0].name} · ${this.numberFormat.format(active[0].volume)} traded`, tag: 'Volume' }] : []),
    ];
  }

  private loadTrend(instrumentKey: string): void {
    this.trendKey = instrumentKey;
    this.trendLoading = true;
    this.trendError = '';
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - 365);
    const from = this.isoDate(start);
    const to = this.isoDate(end);
    this.api.historical(instrumentKey, 'days', 1, from, to).subscribe({
      next: ({ candles }) => {
        const points = candles
          .filter((candle) => Number.isFinite(candle.close))
          .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
        this.trendLoading = false;
        if (!points.length) {
          this.trendError = 'No historical chart data is available for this instrument.';
          return;
        }
        const values = points.map((point) => point.close);
        const min = Math.min(...values);
        const max = Math.max(...values);
        const span = max - min || 1;
        const coords = values.map((value, index) => ({
          x: index * 520 / Math.max(values.length - 1, 1),
          y: 132 - (value - min) / span * 116,
        }));
        this.chartPath = coords.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
        this.chartAreaPath = `${this.chartPath} L520 150 L0 150 Z`;
        const label = (index: number) => new Intl.DateTimeFormat('en-IN', { month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' }).format(new Date(points[index].timestamp));
        this.chartLabels = [label(0), label(Math.floor((points.length - 1) / 2)), label(points.length - 1)];
      },
      error: () => {
        this.trendLoading = false;
        this.trendError = 'Chart history is temporarily unavailable.';
      }
    });
  }

  private isoDate(value: Date): string {
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  }

  formatPrice(value: number): string {
    return `₹${this.numberFormat.format(value)}`;
  }

  disconnect(): void {
    this.api.logout().subscribe({ next: () => this.connected = false, error: () => this.connected = false });
  }
}
