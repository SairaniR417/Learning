import { CommonModule } from '@angular/common';
import { Component, ElementRef, EventEmitter, HostListener, Input, OnChanges, Output, ViewChild } from '@angular/core';
import { GhostSettings, defaultGhostSettings } from './ghost-rider.types';

@Component({
  selector: 'app-ghost-settings', standalone: true, imports: [CommonModule],
  template: `
  <div class="settings-backdrop" (click)="cancel.emit()">
    <section class="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="ghost-settings-title" (click)="$event.stopPropagation()" (keydown.tab)="trapFocus($event)">
      <header><h2 id="ghost-settings-title">Ghost rider v.2</h2><button #closeButton type="button" aria-label="Close settings" (click)="cancel.emit()">✕</button></header>
      <nav aria-label="Ghost Rider settings tabs"><button type="button" *ngFor="let name of tabs" [class.active]="tab === name" (click)="tab = name">{{ name }}</button></nav>
      <div class="settings-content">
        <ng-container *ngIf="tab === 'Inputs'">
          <h3>Visuals &amp; UI</h3>
          <label>Dashboard Font Size <select [value]="draft.dashboardSize" (change)="set('dashboardSize',$any($event.target).value)"><option *ngFor="let size of sizes">{{ size }}</option></select></label>
          <label>Trade Label Size <select [value]="draft.tradeSize" (change)="set('tradeSize',$any($event.target).value)"><option *ngFor="let size of sizes">{{ size }}</option></select></label>
          <label>EMA Ribbon Opacity <input type="number" min="0" max="100" [value]="draft.ribbonOpacity" (input)="number('ribbonOpacity',$any($event.target).value)"></label>
          <label>Label Right Offset (Bars) <input type="number" min="1" step="1" [value]="draft.labelOffset" (input)="number('labelOffset',$any($event.target).value)"></label>
          <h3>Risk Management</h3>
          <label>SL ATR Multiplier <input type="number" min="0.1" step="0.1" [value]="draft.atrMultiplier" (input)="number('atrMultiplier',$any($event.target).value)"></label>
        </ng-container>
        <ng-container *ngIf="tab === 'Style'">
          <label *ngFor="let item of styles"><span><input type="checkbox" [checked]="enabled(item.key)" (change)="set(item.key,$any($event.target).checked)"> {{ item.label }}</span>
            <span class="line-style" *ngIf="item.color"><input type="color" [value]="value(item.color)" (input)="set(item.color,$any($event.target).value)" [attr.aria-label]="item.label+' color'"><input type="number" min="1" max="4" [value]="value(item.width!)" (input)="number(item.width!,$any($event.target).value)" [attr.aria-label]="item.label+' line width'"></span>
          </label>
          <h3>Graphic objects</h3>
          <label *ngFor="let item of objects"><span><input type="checkbox" [checked]="enabled(item.key)" (change)="set(item.key,$any($event.target).checked)"> {{ item.label }}</span></label>
          <h3>Output values</h3>
          <label>Precision <select [value]="draft.precision" (change)="number('precision',$any($event.target).value)"><option value="-1">Default</option><option *ngFor="let precision of precisions" [value]="precision">{{ precision }}</option></select></label>
          <label><span><input type="checkbox" [checked]="draft.scaleLabels" (change)="set('scaleLabels',$any($event.target).checked)"> Labels on price scale</span></label>
          <label><span><input type="checkbox" [checked]="draft.statusValues" (change)="set('statusValues',$any($event.target).checked)"> Values in status line</span></label>
          <label><span><input type="checkbox" [checked]="draft.statusInputs" (change)="set('statusInputs',$any($event.target).checked)"> Inputs in status line</span></label>
        </ng-container>
        <ng-container *ngIf="tab === 'Visibility'">
          <label *ngFor="let frame of otherFrames"><span><input type="checkbox" [checked]="draft.timeframes[frame].enabled" (change)="draft.timeframes[frame].enabled = $any($event.target).checked"> {{ frame }}</span><span class="range" *ngIf="frame !== 'Ticks' && frame !== 'Ranges'"><input type="number" min="1" [value]="draft.timeframes[frame].min" (input)="draft.timeframes[frame].min = +$any($event.target).value" [attr.aria-label]="frame+' minimum'"><span>to</span><input type="number" min="1" [value]="draft.timeframes[frame].max" (input)="draft.timeframes[frame].max = +$any($event.target).value" [attr.aria-label]="frame+' maximum'"></span></label>
          <label><span><input type="checkbox" [checked]="draft.minutes" (change)="set('minutes',$any($event.target).checked)"> Minutes</span><span class="range"><input type="number" min="1" max="59" [value]="draft.minuteMin" (input)="number('minuteMin',$any($event.target).value)" aria-label="Minutes minimum"><span>to</span><input type="number" min="1" max="59" [value]="draft.minuteMax" (input)="number('minuteMax',$any($event.target).value)" aria-label="Minutes maximum"></span></label>
          <p class="hint">{{ stockMode ? 'The stock chart offers stored daily, 1h, 15m and 5m candles.' : 'The option chart offers 5m, 15m, 1h, 1d and 1w candles.' }} Visibility controls show or hide the overlay; they do not change the chart timeframe.</p>
        </ng-container>
        <p *ngIf="error" role="alert" class="error">{{ error }}</p>
      </div>
      <footer><button type="button" (click)="draft = defaults()">Defaults</button><span></span><button type="button" (click)="cancel.emit()">Cancel</button><button type="button" class="ok" (click)="save()">Ok</button></footer>
    </section>
  </div>`,
  styles: [`.settings-backdrop{position:fixed;inset:0;background:#0006;z-index:2000;display:flex;align-items:center;justify-content:center;padding:16px}.settings-dialog{width:460px;max-width:100%;max-height:90vh;display:flex;flex-direction:column;background:#fff;color:#131722;border-radius:12px;box-shadow:0 10px 50px #0005;font-size:14px}.settings-dialog header{display:flex;align-items:center;justify-content:space-between;padding:18px 24px}.settings-dialog h2{font-size:24px;margin:0}button,input,select{font:inherit}button{cursor:pointer;color:inherit;background:#fff;border:1px solid #d8dadd;border-radius:7px;padding:9px 14px}header button{border:0;font-size:22px}nav{display:flex;gap:16px;margin:0 24px;border-bottom:3px solid #eee}nav button{border:0;border-radius:0;padding:12px 0}nav button.active{font-weight:700;box-shadow:0 3px #131722}.settings-content{overflow:auto;padding:12px 24px;flex:1}h3{font-size:11px;color:#787b86;text-transform:uppercase;font-weight:400;margin:26px 0}label{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:18px 0}label>span:first-child{display:flex;align-items:center;gap:8px}input[type=number],select{width:120px;box-sizing:border-box;border:1px solid #d8dadd;border-radius:7px;padding:10px;background:#fff;color:#131722}input[type=checkbox]{accent-color:#131722;width:18px;height:18px}input[type=color]{width:42px;height:32px;padding:2px;border:1px solid #d8dadd;background:#fff}.line-style,.range{display:flex;align-items:center;gap:8px}.line-style input[type=number]{width:54px}.range input{width:64px}footer{display:flex;gap:10px;padding:16px 24px;border-top:1px solid #eee}footer span{flex:1}.ok{background:#131722;color:#fff}.hint{font-size:12px;color:#787b86;line-height:1.5}.error{color:#c62828}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #2962ff;outline-offset:2px}`]
})
export class GhostSettingsComponent implements OnChanges {
  @Input() stockMode = false;
  @ViewChild('closeButton') set closeButton(element: ElementRef<HTMLButtonElement> | undefined) { element?.nativeElement.focus(); }
  @Input({ required: true }) settings = defaultGhostSettings();
  @Output() apply = new EventEmitter<GhostSettings>();
  @Output() cancel = new EventEmitter<void>();
  draft = defaultGhostSettings();
  defaults = defaultGhostSettings;
  tab = 'Inputs'; tabs = ['Inputs','Style','Visibility']; sizes = ['tiny','small','normal','large','huge'];
  precisions = [0,1,2,3,4,5,6,7,8]; otherFrames = ['Ticks','Seconds','Hours','Days','Weeks','Months','Ranges'];
  error = '';
  styles: { key: keyof GhostSettings; label: string; color?: keyof GhostSettings; width?: keyof GhostSettings }[] = [
    {key:'ema9',label:'EMA 9',color:'ema9Color',width:'ema9Width'}, {key:'ema21',label:'EMA 21',color:'ema21Color',width:'ema21Width'},
    {key:'barColor',label:'Bar Color'}, {key:'buyShapes',label:'BUY shapes (below bar)'}, {key:'sellShapes',label:'SELL shapes (above bar)'},
    {key:'vwap',label:'VWAP',color:'vwapBullColor',width:'vwapWidth'}];
  objects: { key: keyof GhostSettings; label: string }[] = [{key:'paneLabels',label:'Pane labels'},{key:'lines',label:'Lines'},{key:'tables',label:'Tables'}];
  ngOnChanges(): void { this.draft = JSON.parse(JSON.stringify(this.settings)); }
  set(key: keyof GhostSettings, value: unknown): void { this.draft = {...this.draft, [key]:value}; }
  number(key: keyof GhostSettings, value: string): void { this.set(key,value === '' ? NaN : Number(value)); }
  enabled(key: keyof GhostSettings): boolean { return Boolean(this.draft[key]); }
  value(key: keyof GhostSettings): string | number { return this.draft[key] as string | number; }
  save(): void {
    const d = this.draft;
    if (![d.ribbonOpacity,d.labelOffset,d.atrMultiplier,d.minuteMin,d.minuteMax,d.precision,d.ema9Width,d.ema21Width,d.vwapWidth].every(Number.isFinite)
      || d.ribbonOpacity<0 || d.ribbonOpacity>100 || !Number.isInteger(d.labelOffset) || d.labelOffset<1 || d.atrMultiplier<.1
      || d.minuteMin<1 || d.minuteMax>59 || d.minuteMin>d.minuteMax || d.precision < -1 || d.precision>8
      || ![d.precision,d.ribbonOpacity,d.minuteMin,d.minuteMax,d.ema9Width,d.ema21Width,d.vwapWidth].every(Number.isInteger)
      || [d.ema9Width,d.ema21Width,d.vwapWidth].some(v=>v<1||v>4)
      || Object.values(d.timeframes).some(v=>!Number.isInteger(v.min)||!Number.isInteger(v.max)||v.min<1||v.max<v.min)) {
      this.error='Enter valid values within the displayed ranges.'; return;
    }
    this.apply.emit(JSON.parse(JSON.stringify(d)));
  }
  trapFocus(event: Event): void {
    const keyboard = event as KeyboardEvent;
    const controls = Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('button,input,select')).filter(e=>e.offsetParent !== null);
    const first=controls[0], last=controls.at(-1);
    if (keyboard.shiftKey && document.activeElement === first) { event.preventDefault();last?.focus(); }
    else if (!keyboard.shiftKey && document.activeElement === last) { event.preventDefault();first?.focus(); }
  }
  @HostListener('document:keydown.escape', ['$event']) escape(event: Event): void { event.stopPropagation(); this.cancel.emit(); }
}
