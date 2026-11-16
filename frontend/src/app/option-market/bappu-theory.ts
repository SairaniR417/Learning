import { ChartQuote } from '../market-api.service';

export interface BapuLevels {
  direction: 'BUY' | 'SELL';
  difference: number;
  targets: { multiple: number; price: number }[];
}

export function bappuLevels(quote?: ChartQuote): BapuLevels | null {
  const atp = quote?.atp, price = quote?.price;
  if (typeof atp !== 'number' || !Number.isFinite(atp) || atp <= 0 ||
      typeof price !== 'number' || !Number.isFinite(price) || price <= 0 || price === atp) return null;
  const direction = price > atp ? 'BUY' : 'SELL';
  const anchor = direction === 'BUY' ? quote?.dayLow : quote?.dayHigh;
  if (typeof anchor !== 'number' || !Number.isFinite(anchor) || anchor <= 0) return null;
  const difference = direction === 'BUY' ? atp - anchor : anchor - atp;
  if (difference < 0) return null;
  return { direction, difference, targets: Array.from({ length: 5 }, (_, index) => ({
    multiple: index + 1, price: atp + (direction === 'BUY' ? 1 : -1) * (index + 1) * difference
  })) };
}

// Compare to the levels that were visible before this quote arrived. Moving ATP
// alone must not generate a price-crossing alert.
export function crossedBapuLevels(previous: ChartQuote | undefined, current: ChartQuote): BapuLevels['targets'] {
  const levels = bappuLevels(previous);
  if (!previous || !levels || !Number.isFinite(current.price) || current.price <= 0 ||
      bappuLevels(current)?.direction !== levels.direction || levels.difference === 0) return [];
  return levels.targets.filter(target => target.price > 0 && (levels.direction === 'BUY'
    ? previous.price < target.price && current.price >= target.price
    : previous.price > target.price && current.price <= target.price));
}
