import { HistoricalCandle } from './market-api.service';

/** A chart annotation for a rule-based candlestick candidate, not a forecast. */
export interface CandlestickPatternMatch {
  index: number;
  name: string;
  marker: string;
  direction: 'bullish' | 'bearish' | 'neutral';
}

/**
 * Simple, explicit geometry rules. Ratios are scale-independent; trend-sensitive
 * reversal names also require a short preceding move. Gap rules are intentionally
 * not used because gaps are uncommon in many markets and candle intervals.
 */
export function detectCandlestickPatterns(candles: HistoricalCandle[]): CandlestickPatternMatch[] {
  const matches: CandlestickPatternMatch[] = [];
  const at = (i: number) => candles[i];
  const body = (i: number) => Math.abs(at(i).close - at(i).open);
  const range = (i: number) => Math.max(at(i).high - at(i).low, Number.EPSILON);
  const upper = (i: number) => at(i).high - Math.max(at(i).open, at(i).close);
  const lower = (i: number) => Math.min(at(i).open, at(i).close) - at(i).low;
  const bullish = (i: number) => at(i).close > at(i).open;
  const bearish = (i: number) => at(i).close < at(i).open;
  const add = (i: number, name: string, marker: string, direction: CandlestickPatternMatch['direction']) =>
    matches.push({ index: i, name, marker, direction });
  // Net movement over the three completed candles immediately before i.
  const priorTrend = (i: number) => i >= 3 ? at(i - 1).close - at(i - 3).close : 0;
  const midpoint = (i: number) => (at(i).open + at(i).close) / 2;

  for (let i = 0; i < candles.length; i++) {
    const b = body(i), r = range(i), up = upper(i), down = lower(i);
    const tinyBody = b / r <= 0.10;
    if (tinyBody) add(i, 'Doji', 'D', 'neutral');

    // One-candle shapes. Hammer and shooting star names depend on prior direction.
    if (b / r <= 0.35 && down >= Math.max(2 * b, 0.55 * r) && up <= 0.25 * r) {
      if (priorTrend(i) < 0) add(i, 'Hammer', 'H', 'bullish');
      else if (priorTrend(i) > 0) add(i, 'Hanging man', 'HM', 'bearish');
    }
    if (b / r <= 0.35 && up >= Math.max(2 * b, 0.55 * r) && down <= 0.25 * r) {
      if (priorTrend(i) < 0) add(i, 'Inverted hammer', 'IH', 'bullish');
      else if (priorTrend(i) > 0) add(i, 'Shooting star', 'SS', 'bearish');
    }

    if (i >= 1) {
      const p = i - 1;
      const engulf = at(i).open <= at(p).close && at(i).close >= at(p).open;
      if (bearish(p) && bullish(i) && engulf && body(i) > body(p) && priorTrend(p) < 0)
        add(i, 'Bullish engulfing', 'BE', 'bullish');
      if (bullish(p) && bearish(i) && at(i).open >= at(p).close && at(i).close <= at(p).open && body(i) > body(p) && priorTrend(p) > 0)
        add(i, 'Bearish engulfing', 'SE', 'bearish');

      const pMid = midpoint(p);
      if (bearish(p) && bullish(i) && at(i).open < at(p).low && at(i).close > pMid && at(i).close < at(p).open && priorTrend(p) < 0)
        add(i, 'Piercing line', 'PL', 'bullish');
      if (bullish(p) && bearish(i) && at(i).open > at(p).high && at(i).close < pMid && at(i).close > at(p).open && priorTrend(p) > 0)
        add(i, 'Dark cloud cover', 'DC', 'bearish');

      const inside = Math.max(at(i).open, at(i).close) <= Math.max(at(p).open, at(p).close)
        && Math.min(at(i).open, at(i).close) >= Math.min(at(p).open, at(p).close);
      if (inside && priorTrend(p) < 0 && bullish(p)) add(i, 'Bullish harami', 'BH', 'bullish');
      if (inside && priorTrend(p) > 0 && bearish(p)) add(i, 'Bearish harami', 'SH', 'bearish');
    }

    if (i >= 2) {
      const a = i - 2, m = i - 1;
      const smallMiddle = body(m) / range(m) <= 0.35;
      if (bearish(a) && bullish(i) && smallMiddle && priorTrend(a) < 0 && at(i).close > midpoint(a))
        add(i, 'Morning star', 'MS', 'bullish');
      if (bullish(a) && bearish(i) && smallMiddle && priorTrend(a) > 0 && at(i).close < midpoint(a))
        add(i, 'Evening star', 'ES', 'bearish');
      if (bullish(a) && bullish(m) && bullish(i)
        && body(a) / range(a) >= 0.55 && body(m) / range(m) >= 0.55 && body(i) / range(i) >= 0.55
        && at(m).close > at(a).close && at(i).close > at(m).close)
        add(i, 'Three white soldiers', '3WS', 'bullish');
      if (bearish(a) && bearish(m) && bearish(i)
        && body(a) / range(a) >= 0.55 && body(m) / range(m) >= 0.55 && body(i) / range(i) >= 0.55
        && at(m).close < at(a).close && at(i).close < at(m).close)
        add(i, 'Three black crows', '3BC', 'bearish');
    }
  }
  return matches;
}
