export const DEFAULT_PAGES = ['Overview', 'Market Scanner', 'Focused', 'F&O Stocks', 'Stock Details', 'Option Chains', 'Watchlist', 'Trade Journal'];
export const NAVIGATION_ORDER_KEY = 'traders-gita-navigation-order';

/** Keep saved tabs once, ignore removed tabs and append newly introduced tabs. */
export function normalizePageOrder(saved: unknown): string[] {
  const valid = Array.isArray(saved) ? saved.filter((item): item is string => typeof item === 'string' && DEFAULT_PAGES.includes(item)) : [];
  return [...new Set([...valid, ...DEFAULT_PAGES])];
}

export function loadPageOrder(): string[] {
  try { return normalizePageOrder(JSON.parse(localStorage.getItem(NAVIGATION_ORDER_KEY) ?? 'null')); }
  catch { return [...DEFAULT_PAGES]; }
}

export function savePageOrder(pages: string[]): boolean {
  try { localStorage.setItem(NAVIGATION_ORDER_KEY, JSON.stringify(pages)); return true; }
  catch { return false; }
}
