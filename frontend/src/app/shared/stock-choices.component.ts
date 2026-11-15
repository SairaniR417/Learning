import { CommonModule } from '@angular/common';
import { AfterViewChecked, Component, ElementRef, EventEmitter, Injectable, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges, ViewChild, inject } from '@angular/core';
import { Observable, Subscription, defer, map, shareReplay, take } from 'rxjs';
import { MarketApiService } from '../market-api.service';
import { OptionChainComponent } from '../stock-details/option-chain.component';

interface StockChoice { symbol: string; name?: string; key?: string; }
type Market = 'Stocks' | 'Indices' | 'Commodities';

@Injectable({ providedIn: 'root' })
export class StockChoicesService {
  private api = inject(MarketApiService);
  // All stock search controls share one saved-universe request, without quotes
  // or broker search calls. A failed request can be retried on subscription.
  readonly stocks$ = defer(() => this.api.fnoStocks()).pipe(map(data => data.stocks), shareReplay({ bufferSize: 1, refCount: false }));
  readonly indices$ = defer(() => this.api.optionUnderlyings()).pipe(map(data => data.underlyings.filter(s => s.group === 'Indices')), shareReplay({ bufferSize: 1, refCount: false }));
  readonly commodities$ = defer(() => this.api.optionUnderlyings(true)).pipe(map(data => data.underlyings.filter(s => s.group === 'Commodities')), shareReplay({ bufferSize: 1, refCount: false }));
}

@Component({ selector: 'app-stock-choices', standalone: true, imports: [CommonModule, OptionChainComponent],
  templateUrl: './stock-choices.component.html',
  styleUrl: './stock-choices.component.css'
})
export class StockChoicesComponent implements OnInit, OnChanges, OnDestroy, AfterViewChecked {
  @Input() stocks?: readonly StockChoice[];
  @Input() query = '';
  @Input() filterQuery = true;
  @Input() selectedSymbol = '';
  @Input() disabled = false;
  @Input() label = 'Choose a stock';
  @Output() chosen = new EventEmitter<string>();
  @ViewChild('picker') picker?: ElementRef<HTMLSelectElement>;
  @ViewChild('chainDialog') chainDialog?: ElementRef<HTMLDialogElement>;
  private source = inject(StockChoicesService);
  private request?: Subscription;
  private saved: StockChoice[] = [];
  private assets: StockChoice[] = [];
  private lookup?: Subscription;
  market: Market = 'Stocks'; assetQuery = ''; assetKey = ''; chainKey = ''; chainLabel = ''; chainOpen = false; chainError = ''; chainLoading = false;
  loading = false; error = false;
  get choices(): StockChoice[] {
    const query = (this.market === 'Stocks' ? this.filterQuery ? this.query : '' : this.assetQuery).trim().toLowerCase();
    const unique = new Map((this.market === 'Stocks' ? this.stocks ?? this.saved : this.assets).filter(s => s.symbol?.trim()).map(s => [this.market === 'Stocks' ? s.symbol : s.key,s]));
    return [...unique.values()].filter(s => !query || `${s.symbol} ${s.name ?? ''}`.toLowerCase().includes(query)).sort((a,b) => a.symbol.localeCompare(b.symbol));
  }
  get selected(): StockChoice | undefined { return this.market === 'Stocks' ? (this.stocks ?? this.saved).find(s => s.symbol.toLowerCase() === (this.query || this.selectedSymbol).trim().toLowerCase()) : this.assets.find(s => s.key === this.assetKey); }
  get selection(): string { return (this.market === 'Stocks' ? this.choices.find(s => s.symbol === this.selected?.symbol)?.symbol : this.assetKey) || '__choose_stock__'; }
  ngOnInit(): void { if (this.stocks === undefined) this.load(); }
  ngOnChanges(changes: SimpleChanges = {}): void { if (changes['query'] || changes['selectedSymbol']) { this.lookup?.unsubscribe(); this.chainLoading = false; } if (this.market === 'Stocks' && this.stocks !== undefined) { this.request?.unsubscribe(); this.loading = false; this.error = false; } }
  changeMarket(market: Market): void { this.request?.unsubscribe(); this.lookup?.unsubscribe(); this.closeChain(); this.market = market; this.assets = []; this.assetKey = ''; this.assetQuery = ''; this.chainError = ''; this.chainLoading = false; this.error = false; this.loading = false; if (market !== 'Stocks' || this.stocks === undefined) this.load(); }
  load(): void { this.request?.unsubscribe(); this.loading = true; this.error = false; const source: Observable<StockChoice[]> = this.market === 'Stocks' ? this.source.stocks$ : this.market === 'Indices' ? this.source.indices$ : this.source.commodities$; this.request = source.subscribe({ next: stocks => { if (this.market === 'Stocks') this.saved = stocks; else this.assets = stocks; this.loading = false; }, error: () => { this.loading = false; this.error = true; } }); }
  choose(value: string): void { this.lookup?.unsubscribe(); this.chainLoading = false; this.chainError = ''; if (this.market === 'Stocks') this.chosen.emit(value); else { this.assetKey = value; if (value) this.openChain(); } }
  openChain(): void {
    const selected = this.selected; if (!selected || this.disabled) return;
    this.chainError = ''; this.lookup?.unsubscribe();
    if (selected.key) { this.showChain(selected); return; }
    this.chainLoading = true;
    this.lookup = this.source.stocks$.pipe(take(1)).subscribe({ next: stocks => { this.chainLoading = false; const item = stocks.find(s => s.symbol === selected.symbol); if (item?.key) this.showChain(item); else this.chainError = 'No supported option underlying was found for this symbol.'; }, error: () => { this.chainLoading = false; this.chainError = 'Could not load option underlyings. Retry Options.'; } });
  }
  private showChain(item: StockChoice): void { this.chainKey = item.key!; this.chainLabel = item.name || item.symbol; this.chainOpen = true; if (!this.chainDialog?.nativeElement.open) this.chainDialog?.nativeElement.showModal(); }
  closeChain(): void { this.chainOpen = false; this.chainDialog?.nativeElement.close(); }
  ngAfterViewChecked(): void { if (this.picker && this.picker.nativeElement.value !== this.selection) this.picker.nativeElement.value = this.selection; }
  ngOnDestroy(): void { this.request?.unsubscribe(); this.lookup?.unsubscribe(); this.closeChain(); }
}
