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

export interface HistoricalCandle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
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

  historical(instrumentKey: string, unit: string, interval: number, from: string, to: string): Observable<{ candles: HistoricalCandle[] }> {
    return this.http.get<{ candles: HistoricalCandle[] }>('/api/historical', {
      params: { instrument_key: instrumentKey, unit, interval, from, to }
    });
  }
}