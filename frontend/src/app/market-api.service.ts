import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface Instrument {
  key: string;
  symbol: string;
  name: string;
  exchange: string;
  segment?: string;
  isin?: string;
  lot_size?: number;
  tick_size?: number;
  instrument_type?: string;
}

export interface LtpQuote {
  last_price: number;
  instrument_token: string;
  volume?: number;
  cp?: number;
}

export interface MarketAssetQuote {
  key: string;
  symbol: string;
  name: string;
  exchange: 'NSE';
  expiry?: string;
  price: number;
  previousClose: number;
  change: number;
  changePct: number;
  volume: number;
}

export interface MarketSnapshot {
  market: 'equities';
  name: string;
  chartKey: string;
  chartSymbol: string;
  assets: MarketAssetQuote[];
  receivedAt: number;
}
export interface IndexConstituents { id: string; name: string; members: { symbol: string; isin: string }[]; source: string; fetchedAt: string; }

export interface ApiStatus {
  connected: boolean;
  configured: boolean;
}

export interface HistoricalCandle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ScannerStrategyParameter { name: string; display_name: string; type: 'int' | 'float' | 'bool' | 'str'; default: number | string | boolean; min_value?: number | null; max_value?: number | null; description?: string; }
export interface ScannerStrategy { id: string; name: string; category: string; description: string; default_timeframe: string; min_candles: number; parameters: ScannerStrategyParameter[]; }
export interface StrategyScanResponse { coverage?: { symbol: string; candles: number; required: number; sufficient: boolean }[]; errors?: { symbol: string; error: string }[]; strategy_id: string; strategy_name: string; timeframe: string; total_scanned: number; total_matched: number; scanned_at: string; results: Record<string, unknown>[]; cached: boolean; }
export interface FocusedEvidence { strategyId: string; strategy: string; direction: string; weight: number; family: string; reason: string; state: string; }
export interface FocusedStock {
  instrumentKey: string; symbol: string; name: string; exchange: string; direction: string; tier: string;
  score: number; maxScore: number; strategyCount: number; strongStrategyCount: number; independentFamilies: number;
  reasons: FocusedEvidence[]; conflicts: FocusedEvidence[]; asOf: string; close: number; changePct: number | null;
  averageTurnover: number; candlesAnalyzed: number; marketCap: number | null; marketCapAsOf: string | null;
  plan: { entry: number; stopLoss: number; target1: number; target2: number; riskPct: number; atr14: number; rewardRisk: number[]; basis: string; };
}
export interface FocusedResponse {
  bullish: FocusedStock[]; bearish: FocusedStock[]; totalBullish: number; totalBearish: number;
  asOf: string | null; totalScanned: number; scannedAt: string; cached: boolean;
  strategies: { id: string; name: string; rows: number; window: number; }[];
  excluded: Record<string, number>; methodology: string; filters: string; planNote: string;
  marketCapAsOf: string | null; marketCapSource: string | null;
}
export interface FocusedJob { id: string; status: 'running' | 'complete' | 'failed'; stage: string; result: FocusedResponse | null; error: string; }
export interface MarketEmaIndicator { instrumentKey: string; symbol: string; name: string; ema9: number | null; ema20: number | null; sma50: number | null; sma200: number | null; close: number; previousClose: number | null; changePct: number | null; volume: number; status: string; historySufficient: boolean; }

export interface CorporateAction {
  name: string;
  expiry_date?: string;
  amount?: number | null;
  ratio?: string | null;
  event_details?: { name: string; value: string }[];
}

export interface CompanyProfile {
  company_profile?: string;
  sector?: string;
  sector_market_cap_inr?: { formatted?: string };
}

export interface SelectedStock { key: string; symbol: string; name: string; exchange: string; strategy?: string; timeframe?: string; status?: string; detail?: string; price?: number; metrics?: { label: string; value: number; compareToClose: boolean }[]; checks?: { label: string; passed?: boolean }[]; }
export interface StockHistory { total: number; page: number; pageSize: number; earliest: string | null; latest: string | null; high: number | null; low: number | null; totalVolume: number; candles: HistoricalCandle[]; chart: HistoricalCandle[]; source: string; }
export interface StockNews { items: { title: string; url: string; publishedAt: string; source: string }[]; fetchedAt: string; source: string; }
export interface WatchEntry { key: string; symbol: string; name: string; exchange: string; section: string; flag: '' | 'red' | 'green' | 'yellow' | 'blue'; }
export interface Watchlist { id: number; name: string; sections: string[]; entries: WatchEntry[]; }
export interface WatchQuote { price: number; previousClose: number | null; change: number | null; changePct: number | null; volume: number; }
export interface PriceAlert { id: number; key: string; symbol: string; name: string; exchange: string; condition: 'above' | 'below' | 'cross_up' | 'cross_down'; target: number; active: boolean; lastPrice: number | null; triggeredAt: string | null; }
export interface AlertNotification { id: number; key: string; symbol: string; name: string; exchange: string; message: string; price: number; createdAt: string; read: boolean; }
export interface NotificationInbox { notifications: AlertNotification[]; unread: number; monitor: { running: boolean; lastCheck: string | null; error: string; }; }

export interface OptionLeg {
  ltp: number | null; oi: number | null; volume: number | null;
  bid_price: number | null; ask_price: number | null; iv: number | null;
  delta: number | null; gamma: number | null; theta: number | null; vega: number | null;
}
export interface OptionChain {
  rows: { strike: number; call: OptionLeg; put: OptionLeg }[];
  spot: number | null; atmStrike: number | null; expiry: string; receivedAt: string;
}

@Injectable({ providedIn: 'root' })
export class MarketApiService {
  private readonly http = inject(HttpClient);
  optionExpiries(key: string): Observable<{ expiries: string[] }> {
    return this.http.get<{ expiries: string[] }>('/api/stocks/option-expiries', { params: { instrument_key: key } });
  }
  optionChain(key: string, expiry: string): Observable<OptionChain> {
    return this.http.get<OptionChain>('/api/stocks/option-chain', { params: { instrument_key: key, expiry } });
  }
  fnoStocks(): Observable<{ stocks: SelectedStock[]; total: number }> {
    return this.http.get<{ stocks: SelectedStock[]; total: number }>('/api/market/fno-stocks');
  }
  startFocused(): Observable<{ id: string }> { return this.http.post<{ id: string }>('/api/focused/jobs', {}); }
  focusedJob(id: string): Observable<FocusedJob> { return this.http.get<FocusedJob>(`/api/focused/jobs/${encodeURIComponent(id)}`); }
  watchlists(): Observable<{ lists: Watchlist[] }> { return this.http.get<{ lists: Watchlist[] }>('/api/watchlists'); }
  createWatchlist(list: Omit<Watchlist, 'id'>): Observable<Watchlist> { return this.http.post<Watchlist>('/api/watchlists', list); }
  saveWatchlist(list: Watchlist): Observable<Watchlist> { return this.http.put<Watchlist>(`/api/watchlists/${list.id}`, list); }
  deleteWatchlist(id: number): Observable<unknown> { return this.http.delete(`/api/watchlists/${id}`); }
  watchQuotes(keys: string[]): Observable<{ quotes: Record<string, WatchQuote>; receivedAt: string }> { return this.http.get<{ quotes: Record<string, WatchQuote>; receivedAt: string }>('/api/watchlists/quotes', { params: { keys: keys.join(',') } }); }
  priceAlerts(): Observable<{ alerts: PriceAlert[] }> { return this.http.get<{ alerts: PriceAlert[] }>('/api/watchlists/alerts'); }
  createPriceAlert(alert: Pick<PriceAlert, 'key' | 'symbol' | 'name' | 'exchange' | 'condition' | 'target'>): Observable<PriceAlert> { return this.http.post<PriceAlert>('/api/watchlists/alerts', alert); }
  cancelPriceAlert(id: number): Observable<unknown> { return this.http.delete(`/api/watchlists/alerts/${id}`); }
  notificationInbox(): Observable<NotificationInbox> { return this.http.get<NotificationInbox>('/api/watchlists/notifications'); }
  readNotifications(): Observable<unknown> { return this.http.post('/api/watchlists/notifications/read', {}); }
  readNotification(id: number): Observable<unknown> { return this.http.post(`/api/watchlists/notifications/${id}/read`, {}); }
  indexConstituents(id: string): Observable<IndexConstituents> { return this.http.get<IndexConstituents>(`/api/market/index-constituents/${encodeURIComponent(id)}`); }
  stockHistory(key: string, page = 1): Observable<StockHistory> { return this.http.get<StockHistory>('/api/stocks/history', { params: { instrument_key: key, page } }); }
  stockNews(symbol: string, name: string): Observable<StockNews> { return this.http.get<StockNews>('/api/stocks/news', { params: { symbol, name } }); }

  status(): Observable<ApiStatus> {
    // return this.http.get<ApiStatus>('/api/status');
    return this.http.get<ApiStatus>('https://traders-gita-api.onrender.com/api/status');
  }

  quotes(keys: string[]): Observable<{ data: Record<string, LtpQuote> }> {
    return this.http.get<{ data: Record<string, LtpQuote> }>('/api/quotes', {
      params: { keys: keys.join(',') }
    });
  }

  marketSnapshot(market: 'equities'): Observable<MarketSnapshot> {
    return this.http.get<MarketSnapshot>('/api/market/snapshot', { params: { market } });
  }

  marketEmaIndicators(timeframe = '1d'): Observable<{ timeframe: string; scanned: number; indicators: MarketEmaIndicator[] }> {
    return this.http.get<{ timeframe: string; scanned: number; indicators: MarketEmaIndicator[] }>('/api/market/ema-indicators', { params: { timeframe } });
  }

  search(query: string): Observable<{ instruments: Instrument[] }> {
    return this.http.get<{ instruments: Instrument[] }>('/api/instruments', { params: { q: query } });
  }

  logout(): Observable<{ connected: boolean }> {
    return this.http.post<{ connected: boolean }>('/api/logout', {});
  }

  historical(instrumentKey: string, unit: string, interval: number, from: string, to: string): Observable<{ candles: HistoricalCandle[] }> {
    return this.http.get<{ candles: HistoricalCandle[] }>('/api/historical', {
      params: { instrument_key: instrumentKey, unit, interval, from, to }
    });
  }

  scannerStrategies(): Observable<{ strategies: ScannerStrategy[] }> {
    return this.http.get<{ strategies: ScannerStrategy[] }>('/api/strategies');
  }

  scanStrategy(strategyId: string, timeframe: string, params: Record<string, number | string | boolean> = {}, bypassCache = false, market: 'equities' = 'equities'): Observable<StrategyScanResponse> {
    return this.http.post<StrategyScanResponse>('/api/strategies/scan', { strategy_id: strategyId, timeframe, params, bypass_cache: bypassCache, market });
  }

  corporateActions(isin: string): Observable<{ actions: CorporateAction[] }> {
    return this.http.get<{ actions: CorporateAction[] }>(`/api/fundamentals/${encodeURIComponent(isin)}/corporate-actions`);
  }

  companyProfile(isin: string): Observable<CompanyProfile> {
    return this.http.get<CompanyProfile>(`/api/fundamentals/${encodeURIComponent(isin)}/profile`);
  }
}
