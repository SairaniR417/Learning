import { ChartQuote } from '../market-api.service';

export function bappuLevels(quote?: ChartQuote): { difference: number; targets: { multiple: number; price: number }[] } | null {
  const atp = quote?.atp, low = quote?.dayLow;
  if (typeof atp !== 'number' || typeof low !== 'number' || !Number.isFinite(atp) || !Number.isFinite(low) || atp <= 0 || low <= 0 || atp < low) return null;
  const difference = atp - low;
  return { difference, targets: Array.from({ length: 5 }, (_, index) => ({ multiple: index + 1, price: atp + (index + 1) * difference })) };
}
