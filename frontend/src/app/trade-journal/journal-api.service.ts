import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';

export interface JournalTrade {
  id?: number; account: string; symbol: string; segment: string; instrumentType: string; timeframe: string;
  direction: 'LONG' | 'SHORT'; entryAt: string; exitAt: string | null; entryPrice: number; exitPrice: number | null;
  quantity: number; lotSize: number; charges: number; capital: number | null; riskPercent: number | null;
  stopPrice: number | null; targetPrice: number | null; recordedRisk: number | null;
  setup: string; marketTrend: string; reason: string; evidence: string; fibLevel: string; rsi: number | null;
  divergence: string; supportResistance: string; trendline: string; volumeConfirmation: string;
  emotionBefore: string; emotionDuring: string; emotionAfter: string; confidence: number | null; rating: number | null;
  entryFollowed: boolean | null; stopFollowed: boolean | null; exitFollowed: boolean | null; wouldTakeAgain: boolean | null;
  mistake: string; didWell: string; learned: string; exitReason: string; chartLink: string; notes: string;
  netPnl?: number | null; grossPnl?: number | null; points?: number | null; plannedRisk?: number | null;
  plannedRR?: number | null; recommendedLots?: number | null; rMultiple?: number | null; durationMinutes?: number | null;
  result?: string; imported?: boolean; updatedAt?: string;
}
export interface WorkbookReference { files: string[]; summary: string; warnings: string[]; trades: JournalTrade[]; }

@Injectable({ providedIn: 'root' })
export class JournalApiService {
  private readonly http = inject(HttpClient);
  list() { return this.http.get<{ trades: JournalTrade[] }>('/api/journal/trades'); }
  save(trade: JournalTrade) {
    const fields = ['account','symbol','segment','instrumentType','timeframe','direction','entryAt','exitAt','entryPrice','exitPrice','quantity','lotSize','charges','capital','riskPercent','stopPrice','targetPrice','recordedRisk','setup','marketTrend','reason','evidence','fibLevel','rsi','divergence','supportResistance','trendline','volumeConfirmation','emotionBefore','emotionDuring','emotionAfter','confidence','rating','entryFollowed','stopFollowed','exitFollowed','wouldTakeAgain','mistake','didWell','learned','exitReason','chartLink','notes'];
    const body = Object.fromEntries(fields.map(key => [key, trade[key as keyof JournalTrade]]));
    return trade.id ? this.http.put<JournalTrade>(`/api/journal/trades/${trade.id}`, body) : this.http.post<JournalTrade>('/api/journal/trades', body);
  }
  remove(id: number) { return this.http.delete(`/api/journal/trades/${id}`); }
  reference() { return this.http.get<WorkbookReference>('/api/journal/provided-workbooks'); }
  importProvided() { return this.http.post<{ added: number; duplicates: number; warnings: string[] }>('/api/journal/import-provided', {}); }
}
