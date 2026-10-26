import { Component } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';
import type { SignalRow } from './focused.component';

interface ActionParams extends ICellRendererParams<SignalRow> {
  onDetails: (row: SignalRow) => void;
  onChart: (row: SignalRow) => void;
  onOptions: (row: SignalRow) => void;
  isChecking: (row: SignalRow) => boolean;
}

@Component({
  selector: 'app-focused-actions', standalone: true,
  template: `
    <div class="actions" role="group" [attr.aria-label]="'Actions for ' + (params?.data?.symbol ?? 'stock')">
      <button type="button" class="details" [disabled]="!params?.data" (click)="details($event)" [attr.aria-label]="'Details for ' + params?.data?.symbol" title="View entry levels and strategy evidence">Details</button>
      <button type="button" class="chart" [disabled]="!params?.data" (click)="chart($event)" [attr.aria-label]="'Chart for ' + params?.data?.symbol" title="Open the supporting strategy chart">Chart</button>
      <button type="button" class="options" [class.put]="params?.data?.signal==='SELL'" [disabled]="optionsDisabled" (click)="options($event)" [attr.aria-label]="optionLabel + ' for ' + params?.data?.symbol" [title]="params?.data?.signal==='CONFLICT'?'Wait for a clear direction before checking a contract':'Verify the actual option contract, premium and liquidity'">{{checking?'Checking…':optionLabel}}</button>
    </div>`,
  styles: [`
    :host{display:flex;align-items:center;height:100%;width:100%}
    .actions{display:flex;align-items:center;gap:6px;width:100%;height:100%;white-space:nowrap}
    button{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;height:28px;box-sizing:border-box;margin:0;padding:0 10px;border:1px solid;border-radius:6px;font:600 11px/1 'Manrope','Segoe UI',sans-serif;cursor:pointer;transition:background-color .15s,border-color .15s}
    .details{background:#1b2735;border-color:#415c7a;color:#c9e2ff}.details:hover:not(:disabled){background:#2b4059;border-color:#7aabdf}
    .chart{background:#302a18;border-color:#756435;color:#f5dda0}.chart:hover:not(:disabled){background:#483b1d;border-color:#c4a659}
    .options{min-width:82px;background:#153c2e;border-color:#397d61;color:#a4f0cb}.options:hover:not(:disabled){background:#20583f;border-color:#71c69a}
    .options.put{background:#48232e;border-color:#995166;color:#ffd0dc}.options.put:hover:not(:disabled){background:#693044;border-color:#db849d}
    button:focus-visible{outline:2px solid #e6f1ff;outline-offset:2px}button:disabled{opacity:.45;cursor:not-allowed}
  `]
})
export class FocusedActionsComponent implements ICellRendererAngularComp {
  params?: ActionParams;
  agInit(params: ActionParams): void { this.params=params; }
  refresh(params: ActionParams): boolean { this.params=params;return true; }
  get checking(): boolean { return !!this.params?.data && this.params.isChecking(this.params.data); }
  get optionsDisabled(): boolean { return !this.params?.data || this.params.data.signal==='CONFLICT' || this.checking; }
  get optionLabel(): string { return this.params?.data?.signal==='BUY'?'Check CE':this.params?.data?.signal==='SELL'?'Check PE':'Options'; }
  details(event: Event): void { event.stopPropagation();if(this.params?.data)this.params.onDetails(this.params.data); }
  chart(event: Event): void { event.stopPropagation();if(this.params?.data)this.params.onChart(this.params.data); }
  options(event: Event): void { event.stopPropagation();if(!this.optionsDisabled&&this.params?.data)this.params.onOptions(this.params.data); }
}
