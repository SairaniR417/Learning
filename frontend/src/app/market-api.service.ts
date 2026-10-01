import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface Instrument {
  key: string;
  symbol: string;
  name: string;
  exchange: string;
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

export interface KiteInstrument {
  key: string;
  instrument_token: number;
  symbol: string;
  name: string;
  exchange: string;
}

export interface HistoricalCandle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface KiteStatus {
  connected: boolean;
  configured: boolean;
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

  search(query: string): Observable<{ instruments: Instrument[] }> {
    return this.http.get<{ instruments: Instrument[] }>('/api/instruments', { params: { q: query } });
  }

  logout(): Observable<{ connected: boolean }> {
    return this.http.post<{ connected: boolean }>('/api/logout', {});
  }

  kiteStatus(): Observable<KiteStatus> {
    return this.http.get<KiteStatus>('/api/kite/status');
  }

  searchKite(query: string): Observable<{ instruments: KiteInstrument[] }> {
    return this.http.get<{ instruments: KiteInstrument[] }>('/api/kite/instruments', { params: { q: query } });
  }

  historical(instrumentToken: number, interval: string, from: string, to: string): Observable<{ candles: HistoricalCandle[] }> {
    return this.http.get<{ candles: HistoricalCandle[] }>('/api/kite/historical', {
      params: { instrument_token: instrumentToken, interval, from, to }
    });
  }

  kiteLogout(): Observable<{ connected: boolean }> {
    return this.http.post<{ connected: boolean }>('/api/kite/logout', {});
  }
}