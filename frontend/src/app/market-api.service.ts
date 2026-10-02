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

  sampleHistory(symbol = 'RELIANCE'): Observable<{ candles: HistoricalCandle[]; instrument_key: string; symbol: string; name: string; unit: string; interval: number }> {
    return this.http.get<{ candles: HistoricalCandle[]; instrument_key: string; symbol: string; name: string; unit: string; interval: number }>('/api/sample-history', { params: { symbol } });
  }

  historical(instrumentKey: string, unit: string, interval: number, from: string, to: string): Observable<{ candles: HistoricalCandle[] }> {
    return this.http.get<{ candles: HistoricalCandle[] }>('/api/historical', {
      params: { instrument_key: instrumentKey, unit, interval, from, to }
    });
  }

  corporateActions(isin: string): Observable<{ actions: CorporateAction[] }> {
    return this.http.get<{ actions: CorporateAction[] }>(`/api/fundamentals/${encodeURIComponent(isin)}/corporate-actions`);
  }

  companyProfile(isin: string): Observable<CompanyProfile> {
    return this.http.get<CompanyProfile>(`/api/fundamentals/${encodeURIComponent(isin)}/profile`);
  }
}