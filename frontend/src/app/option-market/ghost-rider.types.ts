export interface GhostPoint {
  timestamp: string; ema9: number; ema21: number; vwap: number | null;
  vwapColor: string; ribbonColor: string; barColor: string | null;
}
export interface GhostLevel {
  label: string; price: number; color: string; labelColor?: string; width: number; dashed: boolean; hit?: boolean; icon: string;
}
export interface GhostRiderOverlay {
  assessment?: GhostAssessment | null;
  candles?: import('../market-api.service').HistoricalCandle[];
  developingBar?: boolean;
  points: GhostPoint[];
  signals: { timestamp: string; label: string; side: 'BUY' | 'SELL' }[];
  levels: GhostLevel[];
  dashboard: { title: string; value: string; color: string; background: string | null }[];
  setup: { signal: string; signalAt: string; index: number; entry: number; stopLoss: number | null; risk: number | null; targets: { number: number; price: number | null; hit: boolean }[] } | null;
  fiveMinuteAsOf: string | null;
  multiplier?: number;
}
export interface GhostSettings {
  dashboardSize: string; tradeSize: string; ribbonOpacity: number; labelOffset: number; atrMultiplier: number;
  ema9: boolean; ema21: boolean; barColor: boolean; buyShapes: boolean; sellShapes: boolean; vwap: boolean;
  paneLabels: boolean; lines: boolean; tables: boolean; scaleLabels: boolean; statusValues: boolean; statusInputs: boolean;
  precision: number; ema9Color: string; ema21Color: string; vwapBullColor: string; vwapBearColor: string;
  ema9Width: number; ema21Width: number; vwapWidth: number;
  minutes: boolean; minuteMin: number; minuteMax: number;
  timeframes: Record<string, { enabled: boolean; min: number; max: number }>;
}
export interface GhostAssessment {
  sessionDate: string | null; dayOpen: number | null; fromOpenPct: number | null;
  dayHighPct: number | null; dayLowPct: number | null; dayRangePosition: number | null;
  assessmentAsOf: string; assessmentPrice: number; strength: string; strengthScore: number;
  pullersPct: number; draggersPct: number; rsi14: number | null; adx: number | null;
  macdMain: number | null; macdSignal: number | null; macdHistogram: number | null;
  relativeVolume: number | null; volumeStatus: string; vwap: number | null;
  ema9: number | null; ema21: number | null; rsi5m: number | null; atr: number | null;
  decision: string; decisionReason: string; nearestLevel: string | null; nearestLevelPct: number | null;
  stopDistancePct: number | null; nextTarget: string | null; nextTargetPct: number | null;
  remainingRR: number | null; rrTarget: string | null; progressR: number | null; stopTouched: boolean;
  stale: boolean; developing: boolean; orbState: string; orbReason: string;
  orbHigh: number | null; orbLow: number | null;
}
export const defaultGhostSettings = (): GhostSettings => ({
  dashboardSize: 'small', tradeSize: 'small', ribbonOpacity: 75, labelOffset: 12, atrMultiplier: 1.5,
  ema9: true, ema21: true, barColor: true, buyShapes: true, sellShapes: true, vwap: true,
  paneLabels: true, lines: true, tables: true, scaleLabels: true, statusValues: true, statusInputs: true,
  precision: -1, ema9Color: '#4caf50', ema21Color: '#f23645', vwapBullColor: '#4caf50', vwapBearColor: '#f23645',
  ema9Width: 1, ema21Width: 1, vwapWidth: 2, minutes: true, minuteMin: 1, minuteMax: 59,
  timeframes: Object.fromEntries([['Ticks',1],['Seconds',59],['Hours',24],['Days',366],['Weeks',52],['Months',12],['Ranges',1]].map(([name,max]) => [name,{enabled:true,min:1,max:Number(max)}]))
});
export const ghostFontSize = (size: string, label = false): number =>
  (label ? { tiny: 7, small: 10, normal: 12, large: 18, huge: 24 } : { tiny: 8, small: 10, normal: 14, large: 20, huge: 36 })[size] ?? 10;
