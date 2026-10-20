import { CommonModule } from '@angular/common';
import { Component, ElementRef, EventEmitter, HostListener, OnDestroy, OnInit, Output, ViewChild, inject } from '@angular/core';
import { EMPTY, Subscription, catchError, exhaustMap, map, timer } from 'rxjs';
import { AlertNotificationsService } from '../alert-notifications.service';
import { Instrument, MarketApiService, PriceAlert, SelectedStock, StockNews, WatchEntry, Watchlist, WatchQuote } from '../market-api.service';

@Component({ selector: 'app-watchlist', standalone: true, imports: [CommonModule], templateUrl: './watchlist.component.html', styleUrl: './watchlist.component.css' })
export class WatchlistComponent implements OnInit, OnDestroy {
  @Output() stockSelected = new EventEmitter<SelectedStock>();
  private api = inject(MarketApiService);
  readonly notifications = inject(AlertNotificationsService);
  private subscriptions = new Subscription();
  private quoteSubscription?: Subscription;
  private searchSubscription?: Subscription;
  private newsSubscription?: Subscription;
  private searchTimer?: ReturnType<typeof setTimeout>;
  private focusBeforeDialog?: HTMLElement;
  @ViewChild('modalElement') modalElement?: ElementRef<HTMLElement>;
  @ViewChild('dialogInput') set dialogInput(ref: ElementRef<HTMLInputElement> | undefined) {
    if (ref) { this.focusBeforeDialog = document.activeElement as HTMLElement; requestAnimationFrame(() => ref.nativeElement.focus()); }
  }
  @HostListener('document:keydown', ['$event']) dialogKeys(event: KeyboardEvent): void {
    if (event.key === 'Escape') { this.menuOpen = false; if (this.dialog) this.closeDialog(); }
    if (event.key !== 'Tab' || !this.dialog || !this.modalElement) return;
    const elements = Array.from(this.modalElement.nativeElement.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled)'));
    const first = elements[0], last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
  lists: Watchlist[] = []; currentId = 0; selected: WatchEntry | null = null;
  quotes: Record<string, WatchQuote> = {}; updatedAt = ''; quotesError = ''; error = ''; loading = true; saving = false;
  alerts: PriceAlert[] = []; alertsError = ''; news?: StockNews; newsLoading = false; newsError = '';
  menuOpen = false; dialog: '' | 'add' | 'alert' | 'name' | 'confirm' = '';
  nameAction: 'new' | 'rename' | 'copy' | 'section' = 'new'; confirmAction: 'clear' | 'delete' = 'clear'; nameInput = '';
  query = ''; searchResults: Instrument[] = []; searchLoading = false; searchError = ''; searched = false;
  addSection = 'Stocks';
  condition: PriceAlert['condition'] = 'above'; target = ''; alertEntry: WatchEntry | null = null;
  filter = ''; sort: '' | 'symbol' | 'price' | 'change' | 'changePct' = ''; descending = false;
  collapsed = new Set<string>();
  readonly conditions = [{ id: 'above', label: 'At or above' }, { id: 'below', label: 'At or below' }, { id: 'cross_up', label: 'Crossing above' }, { id: 'cross_down', label: 'Crossing below' }];
  get current(): Watchlist | undefined { return this.lists.find(list => list.id === this.currentId); }
  get selectedQuote(): WatchQuote | undefined { return this.selected ? this.quotes[this.selected.key] : undefined; }
  get activeAlerts(): PriceAlert[] { return this.alerts.filter(a => a.active); }
  get symbolAlerts(): PriceAlert[] { return this.alerts.filter(a => a.key === this.selected?.key); }
  get canCreateAlert(): boolean { return !!this.alertEntry && Number.isFinite(Number(this.target)) && Number(this.target) > 0 && !this.saving; }
  get matchingCount(): number { return (this.current?.sections ?? []).reduce((total, section) => total + this.entriesIn(section).length, 0); }
  hasAlert(key: string): boolean { return this.alerts.some(alert => alert.key === key && alert.active); }
  ngOnInit(): void {
    this.loadLists(); this.loadAlerts();
    this.subscriptions.add(timer(0, 15000).pipe(exhaustMap(() => {
      const keys = this.current?.entries.map(entry => entry.key) ?? [];
      const listId = this.currentId;
      if (!keys.length) return EMPTY;
      return this.api.watchQuotes(keys).pipe(map(data => ({ ...data, listId })), catchError(error => { if (listId === this.currentId) this.quotesError = error.error?.detail || 'Live quotes unavailable. Check your Upstox connection.'; return EMPTY; }));
    })).subscribe(data => { if (data.listId !== this.currentId) return; this.quotes = data.quotes; this.updatedAt = data.receivedAt; this.quotesError = ''; this.loadAlerts(); }));
  }
  ngOnDestroy(): void { this.subscriptions.unsubscribe(); this.quoteSubscription?.unsubscribe(); this.searchSubscription?.unsubscribe(); this.newsSubscription?.unsubscribe(); clearTimeout(this.searchTimer); }
  loadLists(): void {
    this.loading = true; this.error = '';
    this.subscriptions.add(this.api.watchlists().subscribe({ next: data => {
      this.lists = data.lists; this.loading = false;
      if (!this.lists.length) { this.createList('Watchlist', ['Stocks'], []); return; }
      let remembered = 0; try { remembered = Number(localStorage.getItem('traders-gita-watchlist-id')); } catch {}
      this.selectList(this.lists.some(l => l.id === remembered) ? remembered : this.lists[0].id);
    }, error: error => { this.loading = false; this.error = error.error?.detail || 'Could not load watchlists. Restart the API and retry.'; } }));
  }
  selectList(id: number): void {
    this.currentId = id; this.menuOpen = false; this.filter = ''; this.collapsed.clear(); this.sort = '';
    this.quotes = {}; this.updatedAt = ''; this.quotesError = '';
    try { localStorage.setItem('traders-gita-watchlist-id', String(id)); } catch {}
    this.selectEntry(this.current?.entries[0] ?? null); this.refreshQuotes();
  }
  refreshQuotes(): void {
    this.quoteSubscription?.unsubscribe();
    const keys = this.current?.entries.map(entry => entry.key) ?? [];
    if (!keys.length) { this.quotes = {}; return; }
    this.quoteSubscription = this.api.watchQuotes(keys).subscribe({ next: data => { this.quotes = data.quotes; this.updatedAt = data.receivedAt; this.quotesError = ''; }, error: error => this.quotesError = error.error?.detail || 'Live quotes unavailable. Check your Upstox connection.' });
  }
  private saveList(list: Watchlist): void {
    if (this.saving) return;
    this.saving = true; this.error = '';
    this.subscriptions.add(this.api.saveWatchlist(list).subscribe({ next: saved => {
      this.lists = this.lists.map(item => item.id === saved.id ? saved : item); this.saving = false;
      if (!saved.entries.some(entry => entry.key === this.selected?.key)) this.selectEntry(saved.entries[0] ?? null);
      this.refreshQuotes();
    }, error: error => { this.error = this.errorText(error, 'Could not save this watchlist.'); this.saving = false; } }));
  }
  private errorText(error: any, fallback: string): string { return typeof error.error?.detail === 'string' ? error.error.detail : fallback; }
  private createList(name: string, sections: string[], entries: WatchEntry[]): void {
    this.saving = true; this.error = '';
    this.subscriptions.add(this.api.createWatchlist({ name, sections, entries }).subscribe({ next: list => {
      this.lists = [...this.lists, list]; this.saving = false; this.dialog = ''; this.selectList(list.id);
    }, error: error => { this.error = this.errorText(error, 'Could not create the watchlist.'); this.saving = false; } }));
  }
  entriesIn(section: string): WatchEntry[] {
    const query = this.filter.toLowerCase().trim();
    const entries = (this.current?.entries ?? []).filter(entry => entry.section === section && (!query || `${entry.symbol} ${entry.name}`.toLowerCase().includes(query)));
    if (!this.sort) return entries;
    const field = this.sort, sign = this.descending ? -1 : 1;
    return [...entries].sort((a, b) => {
      if (field === 'symbol') return sign * a.symbol.localeCompare(b.symbol);
      const av = this.quotes[a.key]?.[field], bv = this.quotes[b.key]?.[field];
      if (av == null) return bv == null ? 0 : 1; if (bv == null) return -1;
      return sign * (av - bv);
    });
  }
  sortBy(field: typeof this.sort): void { this.descending = this.sort === field ? !this.descending : field !== 'symbol'; this.sort = field; }
  toggleSection(section: string): void { if (this.collapsed.has(section)) this.collapsed.delete(section); else this.collapsed.add(section); }
  selectEntry(entry: WatchEntry | null): void {
    this.selected = entry; this.news = undefined; this.newsError = ''; this.newsSubscription?.unsubscribe(); this.newsLoading = !!entry;
    if (!entry) return;
    this.newsSubscription = this.api.stockNews(entry.symbol, entry.name).subscribe({ next: data => { this.news = data; this.newsLoading = false; }, error: () => { this.newsError = 'News temporarily unavailable.'; this.newsLoading = false; } });
  }
  openDetails(): void { if (this.selected) this.stockSelected.emit(this.selected); }
  showAdd(): void { this.error = ''; this.menuOpen = false; this.dialog = 'add'; this.search(''); this.addSection = this.current?.sections[0] ?? 'Stocks'; }
  search(query: string): void {
    clearTimeout(this.searchTimer); this.searchSubscription?.unsubscribe();
    this.query = query; this.searchResults = []; this.searchError = ''; this.searched = false; this.searchLoading = query.trim().length >= 2;
    if (!this.searchLoading) return;
    this.searchTimer = setTimeout(() => { this.searchSubscription = this.api.search(query.trim()).subscribe({ next: data => {
      this.searchResults = data.instruments.filter(item => !!item.key); this.searched = true; this.searchLoading = false;
    }, error: error => { this.searchError = this.errorText(error, 'Stock search unavailable.'); this.searchLoading = false; } }); }, 300);
  }
  isAdded(key: string): boolean { return !!this.current?.entries.some(entry => entry.key === key); }
  add(instrument: Instrument): void {
    const list = this.current; if (!list || this.saving || this.isAdded(instrument.key)) return;
    this.saveList({ ...list, entries: [...list.entries, { key: instrument.key, symbol: instrument.symbol, name: instrument.name, exchange: instrument.exchange, section: this.addSection, flag: '' }] });
  }
  remove(entry: WatchEntry): void { const list = this.current; if (list) this.saveList({ ...list, entries: list.entries.filter(e => e.key !== entry.key) }); }
  flag(entry: WatchEntry): void {
    const colors: WatchEntry['flag'][] = ['', 'red', 'green', 'yellow', 'blue'];
    const list = this.current; if (list) this.saveList({ ...list, entries: list.entries.map(e => e.key === entry.key ? { ...e, flag: colors[(colors.indexOf(e.flag) + 1) % colors.length] } : e) });
  }
  move(entry: WatchEntry, direction: number): void {
    const list = this.current; if (!list || this.saving) return;
    const entries = [...list.entries], index = entries.findIndex(e => e.key === entry.key), other = index + direction;
    if (other < 0 || other >= entries.length || entries[other].section !== entry.section) return;
    [entries[index], entries[other]] = [entries[other], entries[index]]; this.sort = ''; this.saveList({ ...list, entries });
  }
  nameDialog(action: typeof this.nameAction): void { this.error = ''; this.nameAction = action; this.nameInput = action === 'rename' ? this.current?.name ?? '' : action === 'copy' ? `${this.current?.name} copy` : ''; this.dialog = 'name'; this.menuOpen = false; }
  saveName(): void {
    const name = this.nameInput.trim(), list = this.current;
    if (!name || this.saving) return;
    if (this.nameAction === 'new') this.createList(name, ['Stocks'], []);
    else if (this.nameAction === 'copy' && list) this.createList(name, [...list.sections], list.entries.map(e => ({ ...e })));
    else if (list) {
      if (this.nameAction === 'section' && list.sections.includes(name)) { this.error = 'This section already exists.'; return; }
      this.saveList(this.nameAction === 'rename' ? { ...list, name } : { ...list, sections: [...list.sections, name] }); this.dialog = '';
    }
  }
  confirm(action: typeof this.confirmAction): void { this.confirmAction = action; this.dialog = 'confirm'; this.menuOpen = false; }
  confirmListAction(): void {
    const list = this.current; if (!list || this.saving) return;
    if (this.confirmAction === 'clear') { this.saveList({ ...list, entries: [] }); this.dialog = ''; return; }
    this.saving = true;
    this.subscriptions.add(this.api.deleteWatchlist(list.id).subscribe({ next: () => { this.saving = false; this.dialog = ''; this.loadLists(); }, error: error => { this.error = this.errorText(error, 'Could not delete this list.'); this.saving = false; } }));
  }
  exportList(): void {
    const list = this.current; if (!list) return;
    const { id, ...content } = list;
    const url = URL.createObjectURL(new Blob([JSON.stringify(content, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `${list.name.replace(/[^a-z0-9_-]/gi, '_')}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); this.menuOpen = false;
  }
  async importList(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement, file = input.files?.[0]; this.menuOpen = false;
    if (!file) return;
    try {
      if (file.size > 200000) throw new Error('Watchlist file is too large.');
      const data = JSON.parse(await file.text());
      if (typeof data.name !== 'string' || !Array.isArray(data.sections) || !Array.isArray(data.entries)) throw new Error('Choose an exported watchlist JSON file.');
      this.createList(data.name, data.sections, data.entries);
    } catch (error) { this.error = error instanceof Error ? error.message : 'Could not import watchlist.'; }
    input.value = '';
  }
  showAlert(entry: WatchEntry | null = this.selected): void {
    this.error = ''; this.menuOpen = false; if (!entry) { this.error = 'Add and select a symbol before creating an alert.'; return; }
    this.alertEntry = entry; this.condition = 'above'; this.target = String(this.quotes[entry.key]?.price ?? ''); this.dialog = 'alert';
  }
  createAlert(): void {
    if (!this.canCreateAlert || !this.alertEntry) return;
    this.saving = true; this.error = '';
    this.subscriptions.add(this.api.createPriceAlert({ ...this.alertEntry, condition: this.condition, target: Number(this.target) }).subscribe({ next: () => {
      this.saving = false; this.dialog = ''; this.loadAlerts(); this.notifications.refresh();
    }, error: error => { this.error = this.errorText(error, 'Could not create alert.'); this.saving = false; } }));
  }
  loadAlerts(): void { this.subscriptions.add(this.api.priceAlerts().subscribe({ next: data => { this.alerts = data.alerts; this.alertsError = ''; }, error: () => this.alertsError = 'Could not load saved alerts.' })); }
  cancelAlert(id: number): void { this.subscriptions.add(this.api.cancelPriceAlert(id).subscribe({ next: () => this.loadAlerts(), error: () => this.error = 'Could not cancel alert.' })); }
  conditionLabel(condition: string): string { return this.conditions.find(c => c.id === condition)?.label ?? condition; }
  closeDialog(): void { if (!this.saving) { this.dialog = ''; this.searchSubscription?.unsubscribe(); clearTimeout(this.searchTimer); this.focusBeforeDialog?.focus(); } }
}
