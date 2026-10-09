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

export type DrishtiAlignmentStatus = 'ALIGNED' | 'NEWLY_ALIGNED' | 'NOT_ALIGNED' | 'INSUFFICIENT_HISTORY';

export interface DrishtiEmaAlignment {
  symbol: string; exchange: string; timeframe: string; asOf: string | null; close: number | null;
  ema: { ema9: number | null; ema20: number | null; ema50: number | null; ema200: number | null };
  conditions: { priceAboveEma9: boolean; priceAboveEma20: boolean; priceAboveEma50: boolean; priceAboveEma200: boolean; ema9AboveEma20: boolean; ema20AboveEma50: boolean; ema50AboveEma200: boolean };
  bullishAlignment: boolean; status: DrishtiAlignmentStatus; alignedSince: string | null;
  transitionIndex: number | null; transitionTimestamp: string | null; candlesAnalyzed: number;
  minimumHistory: number; recommendedHistory: number; historyStatus: 'SUFFICIENT' | 'MINIMUM_ONLY' | 'INSUFFICIENT';
}

export interface DrishtiChatSource { title: string; url: string; }
export interface DrishtiChatMessage { role: 'user' | 'assistant'; content: string; }
export interface DrishtiChatResponse { answer: string; sources: DrishtiChatSource[]; }

export interface EmaScannerResult {
  symbol: string; instrumentKey: string; exchange: string; timeframe: string;
  close: number; ema9: number; ema20: number; sma50: number; sma200: number;
  status: 'ALIGNED' | 'NEWLY_ALIGNED'; matches: boolean; matchedSince: string;
  candlesAnalyzed: number;
}

export interface EmaScannerResponse {
  strategy: string; timeframe: string; scanned: number; matched: number;
  results: EmaScannerResult[]; errors: { symbol: string; error: string }[];
}

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

@Injectable({ providedIn: 'root' })
export class MarketApiService {
  private readonly http = inject(HttpClient);

  status(): Observable<ApiStatus> {
    return this.http.get<ApiStatus>('/api/status');
  }

  quotes(keys: string[]): Observable<{ data: Record<string, LtpQuote> }> {
    return this.http.get<{ data: Record<string, LtpQuote> }>('/api/quotes', {
      params: { keys: keys.join(',') }
    });
  }

  search(query: string, market: 'cash' | 'commodities' = 'cash'): Observable<{ instruments: Instrument[] }> {
    return this.http.get<{ instruments: Instrument[] }>('/api/instruments', { params: { q: query, market } });
  }

  logout(): Observable<{ connected: boolean }> {
    return this.http.post<{ connected: boolean }>('/api/logout', {});
  }

  historical(instrumentKey: string, unit: string, interval: number, from: string, to: string): Observable<{ candles: HistoricalCandle[] }> {
    return this.http.get<{ candles: HistoricalCandle[] }>('/api/historical', {
      params: { instrument_key: instrumentKey, unit, interval, from, to }
    });
  }

  drishtiEmaAlignment(params: { symbol: string; instrumentKey?: string; exchange?: string; unit: string; interval: number; from: string; to: string }): Observable<DrishtiEmaAlignment> {
    const query: Record<string, string | number> = { symbol: params.symbol, unit: params.unit, interval: params.interval, from: params.from, to: params.to };
    if (params.instrumentKey) query['instrument_key'] = params.instrumentKey;
    if (params.exchange) query['exchange'] = params.exchange;
    return this.http.get<DrishtiEmaAlignment>('/api/drishti/ema-alignment', { params: query });
  }

  scanEmaUniverse(unit: string, interval: number, from: string, to: string): Observable<EmaScannerResponse> {
    return this.http.get<EmaScannerResponse>('/api/scanner/ema', {
      params: { unit, interval, from, to }
    });
  }

  nseEquityUniverse(): Observable<{ count: number; stocks: Instrument[] }> {
    return this.http.get<{ count: number; stocks: Instrument[] }>('/api/scanner/universe');
  }

  drishtiChat(messages: DrishtiChatMessage[]): Observable<DrishtiChatResponse> {
    return this.http.post<DrishtiChatResponse>('/api/drishti/chat', { messages });
  }

  corporateActions(isin: string): Observable<{ actions: CorporateAction[] }> {
    return this.http.get<{ actions: CorporateAction[] }>(`/api/fundamentals/${encodeURIComponent(isin)}/corporate-actions`);
  }

  companyProfile(isin: string): Observable<CompanyProfile> {
    return this.http.get<CompanyProfile>(`/api/fundamentals/${encodeURIComponent(isin)}/profile`);
  }
}
