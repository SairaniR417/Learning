import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject } from '@angular/core';
import { DrishtiEmaAlignment, Instrument, MarketApiService } from '../market-api.service';

type DrishtiInstrument = { symbol: string; name: string; exchange: string; key?: string; sample?: boolean };
type DrishtiChatMessage = { role: 'assistant' | 'user'; text: string; result?: DrishtiEmaAlignment };

@Component({
  selector: 'app-drishti-dashboard', standalone: true, imports: [CommonModule],
  templateUrl: './drishti-dashboard.component.html', styleUrl: './drishti-dashboard.component.css'
})
export class DrishtiDashboardComponent {
  private readonly api = inject(MarketApiService);
  readonly samples: DrishtiInstrument[] = [
    { symbol: 'RELIANCE', name: 'Reliance Industries sample', exchange: 'NSE_EQ', sample: true },
    { symbol: 'ADANIPORTS', name: 'Adani Ports sample', exchange: 'NSE_EQ', sample: true }
  ];
  readonly timeframes = [
    { label: '1 day', unit: 'days', interval: 1 }, { label: '1 week', unit: 'weeks', interval: 1 },
    { label: '1 month', unit: 'months', interval: 1 }, { label: '1 minute', unit: 'minutes', interval: 1 },
    { label: '5 minutes', unit: 'minutes', interval: 5 }, { label: '15 minutes', unit: 'minutes', interval: 15 },
    { label: '30 minutes', unit: 'minutes', interval: 30 }, { label: '1 hour', unit: 'hours', interval: 1 }
  ];
  selectedSample = 'RELIANCE';
  searchText = '';
  results: Instrument[] = [];
  selectedInstrument?: DrishtiInstrument = this.samples[0];
  timeframe = 'days:1';
  from = this.dateOffset(-3650);
  to = this.dateOffset(0);
  loading = false;
  searching = false;
  error = '';
  result?: DrishtiEmaAlignment;
  composer = '';
  readonly quickPrompts = ['Analyze this instrument', 'How is bullish alignment calculated?', 'What does the current status mean?'];
  messages: DrishtiChatMessage[] = [{
    role: 'assistant',
    text: 'Hello, I’m DRISHTI. Choose an instrument and timeframe, then ask me to analyze it. I’ll explain the result using deterministic EMA calculations.'
  }];

  private dateOffset(days: number): string {
    const date = new Date(); date.setDate(date.getDate() + days); return date.toISOString().slice(0, 10);
  }
  get selectedTimeframe(): { unit: string; interval: number } {
    const [unit, interval] = this.timeframe.split(':'); return { unit, interval: Number(interval) };
  }
  selectSample(symbol: string): void {
    this.selectedSample = symbol;
    this.selectedInstrument = this.samples.find((item) => item.symbol === symbol);
    this.result = undefined; this.error = '';
  }
  search(): void {
    const query = this.searchText.trim();
    if (query.length < 2) { this.results = []; return; }
    this.searching = true;
    this.api.search(query).subscribe({
      next: ({ instruments }) => { this.results = instruments; this.searching = false; },
      error: (error: HttpErrorResponse) => { this.error = this.errorMessage(error); this.searching = false; }
    });
  }
  chooseInstrument(instrument: Instrument): void {
    this.selectedInstrument = { symbol: instrument.symbol, name: instrument.name, exchange: instrument.exchange, key: instrument.key };
    this.selectedSample = '';
    this.searchText = `${instrument.symbol} · ${instrument.exchange}`; this.results = []; this.result = undefined; this.error = '';
  }
  analyze(): void {
    if (!this.selectedInstrument) { this.error = 'Choose an instrument first.'; return; }
    const period = this.selectedTimeframe;
    this.loading = true; this.error = ''; this.result = undefined;
    this.api.drishtiEmaAlignment({ symbol: this.selectedInstrument.symbol, instrumentKey: this.selectedInstrument.key,
      exchange: this.selectedInstrument.exchange, unit: period.unit, interval: period.interval, from: this.from, to: this.to
    }).subscribe({
      next: (result) => { this.result = result; this.loading = false; },
      error: (error: HttpErrorResponse) => { this.error = this.errorMessage(error); this.loading = false; }
    });
  }
  sendMessage(text = this.composer): void {
    const prompt = text.trim();
    if (!prompt || this.loading) return;
    this.messages = [...this.messages, { role: 'user', text: prompt }];
    this.composer = '';
    const normalized = prompt.toLowerCase();
    const symbol = this.samples.find((item) => normalized.includes(item.symbol.toLowerCase()));
    if (symbol) this.selectSample(symbol.symbol);

    if (/how|calculate|calculation|rule|formula|alignment/.test(normalized) && !/analy[sz]|check|scan|status/.test(normalized)) {
      this.messages = [...this.messages, { role: 'assistant', text: 'Bullish alignment requires the close to be above EMA 9, 20, 50, and 200, while EMA 9 > EMA 20 > EMA 50 > EMA 200. Each EMA is seeded with the simple average of its first N closes, then updated with alpha = 2 / (N + 1). The seven conditions can become true on different candles; they do not need to cross together.' }];
      return;
    }
    if (/what does|meaning|status/.test(normalized) && this.result && !/analy[sz]|check|scan/.test(normalized)) {
      this.messages = [...this.messages, { role: 'assistant', text: this.statusExplanation(this.result.status), result: this.result }];
      return;
    }
    this.runAnalysis(prompt);
  }

  private runAnalysis(prompt: string): void {
    if (!this.selectedInstrument) {
      this.messages = [...this.messages, { role: 'assistant', text: 'Select an instrument above first, then ask me to analyze it.' }];
      return;
    }
    const period = this.selectedTimeframe;
    this.loading = true;
    this.error = '';
    this.api.drishtiEmaAlignment({ symbol: this.selectedInstrument.symbol, instrumentKey: this.selectedInstrument.key,
      exchange: this.selectedInstrument.exchange, unit: period.unit, interval: period.interval, from: this.from, to: this.to
    }).subscribe({
      next: (result) => {
        this.result = result;
        this.messages = [...this.messages, { role: 'assistant', text: this.analysisSummary(result, prompt), result }];
        this.loading = false;
      },
      error: (error: HttpErrorResponse) => {
        const message = this.errorMessage(error);
        this.error = message;
        this.messages = [...this.messages, { role: 'assistant', text: message }];
        this.loading = false;
      }
    });
  }

  private statusExplanation(status: DrishtiEmaAlignment['status']): string {
    const explanations: Record<DrishtiEmaAlignment['status'], string> = {
      ALIGNED: 'The complete bullish EMA alignment is true on the latest candle and was already true on the prior valid candle.',
      NEWLY_ALIGNED: 'The complete bullish EMA alignment became true on the latest candle after being false on the previous valid candle.',
      NOT_ALIGNED: 'The candle history is long enough, but at least one of the seven bullish alignment conditions is currently false.',
      INSUFFICIENT_HISTORY: 'At least 200 ordered candles are needed before all four EMAs can be evaluated.'
    };
    return explanations[status];
  }

  private analysisSummary(result: DrishtiEmaAlignment, prompt: string): string {
    let summary = `${result.symbol} is ${result.status.replace('_', ' ')} on the ${result.timeframe} timeframe. ${this.statusExplanation(result.status)}`;
    if (result.status === 'NEWLY_ALIGNED') summary += ` New bullish EMA alignment detected at ${this.formatTimestamp(result.transitionTimestamp)}.`;
    else if (result.status === 'ALIGNED' && !result.transitionTimestamp) summary += ' The first valid EMA 200 candle does not count as a confirmed new transition.';
    if (/hold|buy|sell|should i|target|stop.?loss|recommend/.test(prompt.toLowerCase())) {
      summary += ' This Phase 1 rule reports EMA alignment only; it does not determine whether to buy, sell, hold, or set a stop-loss.';
    }
    return summary;
  }
  private errorMessage(error: HttpErrorResponse): string {
    return typeof error.error?.detail === 'string' ? error.error.detail : error.message || 'DRISHTI could not load the requested candles.';
  }
  formatPrice(value: number | null): string {
    return value === null ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value);
  }
  formatTimestamp(value: string | null): string {
    if (!value) return 'Unavailable';
    const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
  }
  get conditions(): { key: keyof DrishtiEmaAlignment['conditions']; label: string }[] {
    return [
      { key: 'priceAboveEma9', label: 'Price > EMA 9' }, { key: 'priceAboveEma20', label: 'Price > EMA 20' },
      { key: 'priceAboveEma50', label: 'Price > EMA 50' }, { key: 'priceAboveEma200', label: 'Price > EMA 200' },
      { key: 'ema9AboveEma20', label: 'EMA 9 > EMA 20' }, { key: 'ema20AboveEma50', label: 'EMA 20 > EMA 50' },
      { key: 'ema50AboveEma200', label: 'EMA 50 > EMA 200' }
    ];
  }
}
