import { HistoricalCandle } from './market-api.service';

export type TraderGitaPatternGroup = 'single' | 'two' | 'three' | 'continuation';
export type TraderGitaPatternDirection = 'bullish' | 'bearish' | 'neutral';
export interface TraderGitaPatternMatch {
  index: number;
  name: string;
  shortName: string;
  group: TraderGitaPatternGroup;
  direction: TraderGitaPatternDirection;
}

export interface TraderGitaPatternOptions {
  dojiPct: number;
  smallBodyPct: number;
  longBodyMult: number;
  wickBodyMult: number;
  tinyWickPct: number;
  avgBodyLen: number;
  trendLen: number;
  tweezerTicks: number;
  tickSize: number;
  showTrendNames: boolean;
  confirmedOnly: boolean;
  groups: Record<TraderGitaPatternGroup, boolean>;
}

/** Rule-based mirror of the Traders Gita Pine indicator, for chart annotations. */
export function detectTraderGitaPatterns(candles: HistoricalCandle[], options: TraderGitaPatternOptions): TraderGitaPatternMatch[] {
  const matches: TraderGitaPatternMatch[] = [];
  const bodies = candles.map(candle => Math.abs(candle.close - candle.open));
  const averages = bodies.map((_, index) => {
    const start = index - options.avgBodyLen + 1;
    if (start < 0) return undefined;
    return bodies.slice(start, index + 1).reduce((sum, value) => sum + value, 0) / options.avgBodyLen;
  });
  const body = (i: number) => bodies[i] ?? 0;
  const range = (i: number) => Math.max((candles[i]?.high ?? 0) - (candles[i]?.low ?? 0), options.tickSize);
  const upper = (i: number) => candles[i].high - Math.max(candles[i].open, candles[i].close);
  const lower = (i: number) => Math.min(candles[i].open, candles[i].close) - candles[i].low;
  const bull = (i: number) => candles[i].close > candles[i].open;
  const bear = (i: number) => candles[i].close < candles[i].open;
  const small = (i: number) => body(i) / range(i) <= options.smallBodyPct;
  const doji = (i: number) => body(i) / range(i) <= options.dojiPct;
  const long = (i: number) => averages[i] !== undefined && body(i) >= averages[i]! * options.longBodyMult;
  const bodyHigh = (i: number) => Math.max(candles[i].open, candles[i].close);
  const bodyLow = (i: number) => Math.min(candles[i].open, candles[i].close);
  const upTrend = (i: number) => i >= options.trendLen && candles[i].close > candles[i - options.trendLen].close;
  const downTrend = (i: number) => i >= options.trendLen && candles[i].close < candles[i - options.trendLen].close;
  const add = (i: number, name: string, shortName: string, group: TraderGitaPatternGroup, direction: TraderGitaPatternDirection) => {
    if (options.groups[group]) matches.push({ index: i, name, shortName, group, direction });
  };
  const finalIndex = options.confirmedOnly ? candles.length - 2 : candles.length - 1;
  const tweezerTolerance = options.tweezerTicks * options.tickSize;

  for (let i = 0; i <= finalIndex; i++) {
    const b = body(i), r = range(i), up = upper(i), down = lower(i);
    if (doji(i)) add(i, 'Doji', 'Doji', 'single', 'neutral');
    if (doji(i) && up >= r * .3 && down >= r * .3) add(i, 'Long-Legged Doji', 'Long Doji', 'single', 'neutral');
    if (doji(i) && Math.abs(up - down) <= r * .15) add(i, 'Cross Doji', 'Cross Doji', 'single', 'neutral');
    if (doji(i) && down >= r * .6 && up <= r * .1) add(i, 'Dragonfly Doji', 'Dragonfly', 'single', 'neutral');
    if (doji(i) && up >= r * .6 && down <= r * .1) add(i, 'Gravestone Doji', 'Gravestone', 'single', 'neutral');

    const hammerShape = b > 0 && down >= b * options.wickBodyMult && up <= b * .5;
    const invertedShape = b > 0 && up >= b * options.wickBodyMult && down <= b * .5;
    if (hammerShape && (!options.showTrendNames || downTrend(i))) add(i, 'Hammer', 'Hammer', 'single', 'bullish');
    else if (hammerShape && upTrend(i)) add(i, 'Hanging Man', 'Hanging Man', 'single', 'bearish');
    if (invertedShape && (!options.showTrendNames || downTrend(i))) add(i, 'Inverted Hammer', 'Inverted Hammer', 'single', 'bullish');
    else if (invertedShape && upTrend(i)) add(i, 'Shooting Star', 'Shooting Star', 'single', 'bearish');

    const bullMaru = bull(i) && up <= r * options.tinyWickPct && down <= r * options.tinyWickPct;
    const bearMaru = bear(i) && up <= r * options.tinyWickPct && down <= r * options.tinyWickPct;
    if (bullMaru) add(i, 'Bullish Marubozu', 'Bull Maru', 'single', 'bullish');
    if (bearMaru) add(i, 'Bearish Marubozu', 'Bear Maru', 'single', 'bearish');
    if (bull(i) && down <= r * options.tinyWickPct && up > r * options.tinyWickPct) add(i, 'Bullish Opening Marubozu', 'Bull Open', 'single', 'bullish');
    if (bull(i) && up <= r * options.tinyWickPct && down > r * options.tinyWickPct) add(i, 'Bullish Closing Marubozu', 'Bull Close', 'single', 'bullish');
    if (bear(i) && up <= r * options.tinyWickPct && down > r * options.tinyWickPct) add(i, 'Bearish Opening Marubozu', 'Bear Open', 'single', 'bearish');
    if (bear(i) && down <= r * options.tinyWickPct && up > r * options.tinyWickPct) add(i, 'Bearish Closing Marubozu', 'Bear Close', 'single', 'bearish');
    if (small(i) && up > b && down > b) add(i, 'Spinning Top', 'Spin Top', 'single', 'neutral');

    if (i >= 1) {
      const p = i - 1, midpoint = (candles[p].open + candles[p].close) / 2;
      if (bear(p) && bull(i) && candles[i].open <= candles[p].close && candles[i].close >= candles[p].open && b > body(p)) add(i, 'Bullish Engulfing', 'Bull Engulf', 'two', 'bullish');
      if (bull(p) && bear(i) && candles[i].open >= candles[p].close && candles[i].close <= candles[p].open && b > body(p)) add(i, 'Bearish Engulfing', 'Bear Engulf', 'two', 'bearish');
      if (bear(p) && long(p) && bull(i) && candles[i].open < candles[p].close && candles[i].close > midpoint && candles[i].close < candles[p].open) add(i, 'Piercing Pattern', 'Piercing', 'two', 'bullish');
      if (bull(p) && long(p) && bear(i) && candles[i].open > candles[p].close && candles[i].close < midpoint && candles[i].close > candles[p].open) add(i, 'Dark Cloud Cover', 'Dark Cloud', 'two', 'bearish');
      const inside = bodyHigh(i) < bodyHigh(p) && bodyLow(i) > bodyLow(p);
      if (bear(p) && long(p) && bull(i) && b < body(p) && inside) add(i, 'Bullish Harami', 'Bull Harami', 'two', 'bullish');
      if (bull(p) && long(p) && bear(i) && b < body(p) && inside) add(i, 'Bearish Harami', 'Bear Harami', 'two', 'bearish');
      if (bear(p) && long(p) && doji(i) && candles[i].high < bodyHigh(p) && candles[i].low > bodyLow(p)) add(i, 'Bullish Harami Cross', 'Bull H Cross', 'two', 'bullish');
      if (bull(p) && long(p) && doji(i) && candles[i].high < bodyHigh(p) && candles[i].low > bodyLow(p)) add(i, 'Bearish Harami Cross', 'Bear H Cross', 'two', 'bearish');
      if (bear(p) && bull(i) && Math.abs(candles[i].low - candles[p].low) <= tweezerTolerance) add(i, 'Tweezer Bottom', 'Tweezer Bot', 'two', 'bullish');
      if (bull(p) && bear(i) && Math.abs(candles[i].high - candles[p].high) <= tweezerTolerance) add(i, 'Tweezer Top', 'Tweezer Top', 'two', 'bearish');
    }

    if (i >= 2) {
      const a = i - 2, m = i - 1, midpoint = (candles[a].open + candles[a].close) / 2;
      if (bear(a) && long(a) && small(m) && bull(i) && candles[i].close > midpoint) add(i, 'Morning Star', 'Morning Star', 'three', 'bullish');
      if (bull(a) && long(a) && small(m) && bear(i) && candles[i].close < midpoint) add(i, 'Evening Star', 'Evening Star', 'three', 'bearish');
      if (bear(a) && long(a) && doji(m) && candles[m].high < candles[a].low && bull(i) && candles[i].low > candles[m].high && candles[i].close > midpoint) add(i, 'Bullish Abandoned Baby', 'Bull Ab Baby', 'three', 'bullish');
      if (bull(a) && long(a) && doji(m) && candles[m].low > candles[a].high && bear(i) && candles[i].high < candles[m].low && candles[i].close < midpoint) add(i, 'Bearish Abandoned Baby', 'Bear Ab Baby', 'three', 'bearish');
      if (bull(a) && bull(m) && bull(i) && candles[i].close > candles[m].close && candles[m].close > candles[a].close && candles[i].open > bodyLow(m) && candles[i].open < candles[m].close && candles[m].open > bodyLow(a) && candles[m].open < candles[a].close && upper(i) <= body(i) * .5 && upper(m) <= body(m) * .5 && upper(a) <= body(a) * .5) add(i, 'Three White Soldiers', '3 Soldiers', 'three', 'bullish');
      if (bear(a) && bear(m) && bear(i) && candles[i].close < candles[m].close && candles[m].close < candles[a].close && candles[i].open < bodyHigh(m) && candles[i].open > candles[m].close && candles[m].open < bodyHigh(a) && candles[m].open > candles[a].close && lower(i) <= body(i) * .5 && lower(m) <= body(m) * .5 && lower(a) <= body(a) * .5) add(i, 'Three Black Crows', '3 Crows', 'three', 'bearish');
      if (i >= 3) {
        const priorBullHarami = bear(i - 2) && long(i - 2) && bull(i - 1) && body(i - 1) < body(i - 2) && bodyHigh(i - 1) < bodyHigh(i - 2) && bodyLow(i - 1) > bodyLow(i - 2);
        const priorBearHarami = bull(i - 2) && long(i - 2) && bear(i - 1) && body(i - 1) < body(i - 2) && bodyHigh(i - 1) < bodyHigh(i - 2) && bodyLow(i - 1) > bodyLow(i - 2);
        if (priorBullHarami && bull(i) && candles[i].close > candles[i - 1].high) add(i, 'Three Inside Up', '3 Inside Up', 'three', 'bullish');
        if (priorBearHarami && bear(i) && candles[i].close < candles[i - 1].low) add(i, 'Three Inside Down', '3 Inside Down', 'three', 'bearish');
      }
    }

    if (i >= 4) {
      const a = i - 4;
      const contained = [i - 3, i - 2, i - 1].every(j => candles[j].high < candles[a].high && candles[j].low > candles[a].low);
      if (bull(a) && long(a) && [i - 3, i - 2, i - 1].every(j => bear(j)) && contained && bull(i) && candles[i].close > candles[a].close && body(i) >= (averages[i] ?? 0) * .8) add(i, 'Rising Three Methods', 'Rising 3', 'continuation', 'bullish');
      if (bear(a) && long(a) && [i - 3, i - 2, i - 1].every(j => bull(j)) && contained && bear(i) && candles[i].close < candles[a].close && body(i) >= (averages[i] ?? 0) * .8) add(i, 'Falling Three Methods', 'Falling 3', 'continuation', 'bearish');
    }
  }
  return matches;
}
