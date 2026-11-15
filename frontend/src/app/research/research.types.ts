export const RESEARCH_VIEWS = [
  { id: 'research_radar', name: 'Market radar' },
  { id: 'research_cpr', name: 'CPR & Sutradhar' },
  { id: 'research_camarilla', name: 'Camarilla levels' },
  { id: 'research_wall', name: 'Chart wall' },
  { id: 'research_stock', name: 'Stock intelligence' },
  { id: 'research_index', name: 'Index intelligence' },
  { id: 'research_trends', name: 'Trendline scanner' },
  { id: 'research_scenarios', name: 'Trade scenarios' },
] as const;
export type Frame = 'hourly' | 'daily' | 'weekly' | 'monthly';
export interface Bar { timestamp: string; open: number; high: number; low: number; close: number; volume: number; }
export interface TrendLine { side: string; touches: number; value: number; note: string; points: { timestamp: string; value: number }[]; }
export interface Levels { pivot: number; bc: number; tc: number; widthPct: number; narrow: boolean; position: string; r3: number; r4: number; s3: number; s4: number; camPosition: string; sourceAt: string; }
export interface Pressure { state: string; asOf: string | null; relativeVolume: number | null; volumePressure: number | null; support: number | null; resistance: number | null; vwap: number | null; structure: string; reason: string; volumeBasis: string; oldData: boolean; }
export interface ResearchStock {
  key: string; symbol: string; name: string; sector: string; industry: string; price: number | null;
  changePct: number | null; asOf: string | null; oldData: boolean; bias: string; relativeVolume: number | null;
  regimes: Record<string, { bias: string; bars: number; ema20: number | null; asOf: string | null }>;
  levels: Record<string, Levels | null>; sutradhar: Record<string, number | string | null>; sutradharPosition: string;
  pressure: Record<string, Pressure>; charts: Record<Frame, Bar[]>; trendlines: Record<string, TrendLine[]>;
}
export interface ResearchSnapshot {
  stocks: ResearchStock[]; fetchedAt: string; source: string; methodology: string; availability: Record<string, string>;
  sectors: { name: string; count: number; bullish: number; bearish: number; coverage: number; changePct: number | null; method: string }[];
}
