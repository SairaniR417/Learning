import { CommonModule } from '@angular/common';
import { Component, ElementRef, HostListener, OnDestroy, OnInit, ViewChild, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { MarketApiService, OptionUnderlying } from '../market-api.service';
import { OptionChainComponent } from '../stock-details/option-chain.component';
import { OptionAnalysisComponent } from './option-analysis.component';

@Component({
  selector: 'app-option-market', standalone: true, imports: [CommonModule, OptionChainComponent, OptionAnalysisComponent],
  template: `
    <section class="page-shell option-market">
      <header class="market-toolbar">
      <div class="market-title"><h1>Scanner</h1><small title="Updates every minute while this view is visible">Auto-refresh &middot; 1 min</small></div>
      <div class="selectors">
        <label>Market <select [value]="group" (change)="selectGroup($any($event.target).value)">
          <option>Indices</option><option>F&amp;O stocks</option><option>Commodities</option>
        </select></label>
        <div class="underlying-picker" #picker (keydown.escape)="closePicker(trigger)" (keydown)="navigateOptions($event, picker)" (focusout)="leavePicker($event, picker)">
          <span id="underlying-label">Underlying</span>
          <button #trigger type="button" class="picker-trigger" aria-labelledby="underlying-label underlying-value" aria-haspopup="dialog" [attr.aria-expanded]="pickerOpen" [disabled]="loading" (click)="togglePicker()"><span id="underlying-value">{{ selectedLabel }}</span><span aria-hidden="true">▾</span></button>
          <div *ngIf="pickerOpen" class="picker-menu" role="dialog" aria-label="Choose underlying">
            <input #underlyingSearch type="search" [value]="search" (input)="search = $any($event.target).value" aria-label="Search underlyings" placeholder="Search symbol or name" />
            <div class="picker-options">
              <button class="picker-option" type="button" *ngFor="let option of pickerOptions; trackBy: trackOption" (click)="chooseUnderlying(option.value); trigger.focus()" [attr.aria-pressed]="option.value === (group === 'Commodities' ? commodity : key)">{{ option.label }}</button>
              <p *ngIf="!pickerOptions.length" role="status">No matching underlyings.</p>
            </div>
          </div>
        </div>
      </div>
      <div class="view-switch" *ngIf="group === 'F&O stocks'" role="group" aria-label="Stock or options view">
        <button type="button" (click)="view = 'stock'" [attr.aria-pressed]="view === 'stock'">Stock chart</button>
        <button type="button" (click)="view = 'options'" [attr.aria-pressed]="view === 'options'">Options</button>
      </div>
      </header>
      <div *ngIf="group === 'Commodities' && commodity" class="futures">
        <h2>{{ commodity }} futures</h2>
        <p>Select a current futures contract to load its option chain.</p>
        <div class="contract-list"><button type="button" *ngFor="let item of futures" (click)="key = item.key" [class.selected]="key === item.key" [attr.aria-pressed]="key === item.key">{{ item.name }}</button></div>
      </div>
      <p *ngIf="loading" role="status">Loading available contracts…</p>
      <p *ngIf="error" role="alert">{{ error }} <button (click)="selectGroup(group)">Retry</button></p>
      <p *ngIf="!loading && !error && !visible.length">No current option underlyings available.</p>
      <p class="selection-hint" *ngIf="!key && !loading && !error && visible.length">{{ group === 'F&O stocks' ? 'Choose a stock above to view its chart, strategies or options.' : 'Choose an underlying above to load its option chain.' }}</p>
      <app-option-analysis *ngIf="key && showStockChart" [stockMode]="true" [stockWorkspace]="true" [underlyingKey]="key" />
      <app-option-chain *ngIf="key && !showStockChart" [stockKey]="key" />
    </section>`,
  styleUrl: './option-market.component.css'
})
export class OptionMarketComponent implements OnInit, OnDestroy {
  private api = inject(MarketApiService);
  private request?: Subscription;
  group = 'F&O stocks'; key = ''; loading = false; error = '';
  view: 'stock' | 'options' = 'stock';
  get showStockChart(): boolean { return this.group === 'F&O stocks' && this.view === 'stock'; }
  search = ''; commodity = '';
  pickerOpen = false;
  private host = inject(ElementRef);
  @ViewChild('underlyingSearch') set searchInput(input: ElementRef<HTMLInputElement> | undefined) { input?.nativeElement.focus(); }
  get selectedLabel(): string {
    return this.group === 'Commodities' ? this.commodity || 'Select a commodity' :
      this.visible.find(item => item.key === this.key)?.name || 'Select an underlying';
  }
  get pickerOptions(): { value: string; label: string }[] {
    return this.group === 'Commodities' ? this.commoditySymbols.map(symbol => ({ value: symbol, label: symbol })) :
      this.filtered.map(item => ({ value: item.key, label: `${item.name} (${item.symbol})` }));
  }
  togglePicker(): void { this.pickerOpen = !this.pickerOpen; this.search = ''; }
  trackOption(_index: number, option: {value:string}): string { return option.value; }
  closePicker(trigger: HTMLElement): void { this.pickerOpen = false; trigger.focus(); }
  chooseUnderlying(value: string): void {
    if (this.group === 'Commodities') this.selectCommodity(value); else this.key = value;
    this.pickerOpen = false; this.search = '';
  }
  leavePicker(event: FocusEvent, picker: HTMLElement): void {
    if (event.relatedTarget && !picker.contains(event.relatedTarget as Node)) this.pickerOpen = false;
  }
  @HostListener('document:click', ['$event']) outsideClick(event: MouseEvent): void {
    if (!this.host.nativeElement.querySelector('.underlying-picker')?.contains(event.target)) this.pickerOpen = false;
  }
  navigateOptions(event: KeyboardEvent, picker: HTMLElement): void {
    if (!this.pickerOpen || !['ArrowDown', 'ArrowUp'].includes(event.key)) return;
    const options = Array.from(picker.querySelectorAll<HTMLButtonElement>('.picker-option'));
    if (!options.length) return;
    event.preventDefault();
    const current = options.indexOf(document.activeElement as HTMLButtonElement);
    const next = current < 0 ? (event.key === 'ArrowDown' ? 0 : options.length - 1) :
      (current + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
    options[next].focus();
  }
  items: OptionUnderlying[] = [];
  get visible(): OptionUnderlying[] { return this.items.filter(item => item.group === this.group); }
  get filtered(): OptionUnderlying[] {
    const query = this.search.trim().toLowerCase();
    return this.visible.filter(item => `${item.symbol} ${item.name}`.toLowerCase().includes(query));
  }
  get commoditySymbols(): string[] { return [...new Set(this.filtered.map(item => item.symbol))].sort(); }
  get futures(): OptionUnderlying[] { return this.visible.filter(item => item.symbol === this.commodity); }
  selectCommodity(symbol: string): void { this.commodity = symbol; this.key = ''; }
  ngOnInit(): void { this.selectGroup(this.group); }
  selectGroup(group: string): void {
    this.request?.unsubscribe(); this.group = group; this.key = ''; this.commodity = ''; this.search = ''; this.pickerOpen = false; this.error = ''; this.items = []; this.loading = true;
    this.request = this.api.optionUnderlyings(group === 'Commodities').subscribe({
      next: data => { this.items = data.underlyings; this.loading = false; },
      error: error => { this.error = error.error?.detail || 'Underlyings unavailable. Please retry.'; this.loading = false; }
    });
  }
  ngOnDestroy(): void { this.request?.unsubscribe(); }
}
