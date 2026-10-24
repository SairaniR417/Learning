import { CommonModule } from '@angular/common';
import { Component,Input,Output,EventEmitter,OnChanges,HostListener,ViewChild,ElementRef } from '@angular/core';
import { RsiSettings,defaultRsiSettings } from './rsi.types';

@Component({selector:'app-rsi-settings',standalone:true,imports:[CommonModule],template:`
<div class="backdrop" (click)="cancel.emit()"><section role="dialog" aria-modal="true" aria-label="RSI settings" (click)="$event.stopPropagation()" (keydown.tab)="trap($event)">
<header><h2>RSI</h2><button #close aria-label="Close RSI settings" (click)="cancel.emit()">×</button></header>
<nav><button *ngFor="let t of tabs" [class.active]="tab===t" (click)="tab=t">{{t}}</button></nav>
<div class="content">
<ng-container *ngIf="tab==='Inputs'">
<h3>RSI settings</h3>
<label>RSI Length<input type="number" min="1" max="1000" [value]="draft.inputs.period" (input)="draft.inputs.period=+$any($event.target).value"></label>
<label>Source<select [value]="draft.inputs.source" (change)="draft.inputs.source=$any($event.target).value"><option *ngFor="let s of sources" [value]="s">{{s}}</option></select></label>
<label><span><input type="checkbox" [checked]="draft.inputs.calculate_divergence" (change)="draft.inputs.calculate_divergence=$any($event.target).checked"> Calculate Divergence</span></label>
<h3>Smoothing</h3>
<label>Type<select [value]="draft.inputs.ma_type" (change)="draft.inputs.ma_type=$any($event.target).value"><option *ngFor="let m of maTypes">{{m}}</option></select></label>
<label>Length<input type="number" min="1" max="1000" [disabled]="draft.inputs.ma_type==='None'" [value]="draft.inputs.ma_length" (input)="draft.inputs.ma_length=+$any($event.target).value"></label>
<label>BB StdDev<input type="number" min="0.001" max="50" step="0.5" [disabled]="draft.inputs.ma_type!=='SMA + Bollinger Bands'" [value]="draft.inputs.bb_mult" (input)="draft.inputs.bb_mult=+$any($event.target).value"></label>
<h3>Calculation</h3>
<label>Timeframe<select [value]="draft.inputs.timeframe" (change)="draft.inputs.timeframe=+$any($event.target).value"><option value="0">Chart</option><option value="5">5 minutes</option><option value="15">15 minutes</option><option value="60">1 hour</option><option value="1440">1 day</option><option value="10080">1 week</option></select></label>
<label><span><input type="checkbox" [checked]="draft.inputs.wait_close" (change)="draft.inputs.wait_close=$any($event.target).checked"> Wait for timeframe closes</span></label>
<p class="hint">Pivots use 5 bars left and right. Labels appear only after the five right-side bars are available. With waiting disabled, live candle signals may change.</p>
</ng-container>
<ng-container *ngIf="tab==='Style'">
<label *ngFor="let item of styleItems"><span><input type="checkbox" [checked]="draft.styles[item.key].enabled" (change)="draft.styles[item.key].enabled=$any($event.target).checked">{{item.label}}</span><span class="style-tools"><input type="color" [value]="draft.styles[item.key].color" (input)="draft.styles[item.key].color=$any($event.target).value" [attr.aria-label]="item.label+' color'"><input *ngIf="item.line" type="number" min="1" max="4" [value]="draft.styles[item.key].width" (input)="draft.styles[item.key].width=+$any($event.target).value" [attr.aria-label]="item.label+' width'"><input *ngIf="item.band" type="number" min="0" max="100" [value]="draft.styles[item.key].value" (input)="draft.styles[item.key].value=+$any($event.target).value" [attr.aria-label]="item.label+' value'"></span></label>
<h3>Output values</h3><label>Precision<select [value]="draft.precision" (change)="draft.precision=+$any($event.target).value"><option value="2">Default (2)</option><option *ngFor="let n of [0,1,3,4,5,6,7,8]" [value]="n">{{n}}</option></select></label>
<label><span><input type="checkbox" [checked]="draft.scaleLabels" (change)="draft.scaleLabels=$any($event.target).checked"> Labels on price scale</span></label>
<label><span><input type="checkbox" [checked]="draft.statusValues" (change)="draft.statusValues=$any($event.target).checked"> Values in status line</span></label>
<label><span><input type="checkbox" [checked]="draft.statusInputs" (change)="draft.statusInputs=$any($event.target).checked"> Inputs in status line</span></label>
</ng-container>
<ng-container *ngIf="tab==='Visibility'"><label *ngFor="let frame of frames"><span><input type="checkbox" [checked]="draft.visibility[frame].enabled" (change)="draft.visibility[frame].enabled=$any($event.target).checked">{{frame}}</span><span class="range" *ngIf="frame!=='Ticks'&&frame!=='Ranges'"><input type="number" min="1" [value]="draft.visibility[frame].min" (input)="draft.visibility[frame].min=+$any($event.target).value" [attr.aria-label]="frame+' minimum'">to<input type="number" min="1" [value]="draft.visibility[frame].max" (input)="draft.visibility[frame].max=+$any($event.target).value" [attr.aria-label]="frame+' maximum'"></span></label><p class="hint">Visibility controls the indicator on the offered chart intervals. Tick and second candle feeds are not available in this application.</p></ng-container>
<p *ngIf="error" role="alert">{{error}}</p>
</div><footer><button (click)="draft=defaults()">Defaults</button><span></span><button (click)="cancel.emit()">Cancel</button><button class="ok" (click)="save()">Ok</button></footer>
</section></div>`,styles:[`
.backdrop{position:fixed;inset:0;background:#0009;z-index:2100;display:flex;align-items:center;justify-content:center;padding:16px}section{width:460px;max-width:100%;max-height:90vh;background:#131313;color:#b2b5be;border:1px solid #363a45;border-radius:10px;display:flex;flex-direction:column;color-scheme:dark;font:14px Arial}header{display:flex;justify-content:space-between;align-items:center;padding:20px 24px}h2{font-size:20px;margin:0}button,input,select{font:inherit;color:inherit}button{background:#131313;border:1px solid #555;border-radius:7px;padding:8px 14px;cursor:pointer}header button{border:0;font-size:24px}nav{display:flex;gap:24px;margin:0 24px;border-bottom:3px solid #363a45}nav button{padding:10px 0;border:0;border-radius:0}.active{box-shadow:0 3px #eee;color:#eee}.content{overflow:auto;padding:12px 24px}h3{text-transform:uppercase;font-size:10px;font-weight:400;margin:26px 0}label{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:20px 0}label span{display:flex;align-items:center;gap:8px}input[type=number],select{width:118px;background:#141414;border:1px solid #555;padding:9px;border-radius:6px;box-sizing:border-box}input[type=color]{width:36px;height:32px;background:#202024;border:1px solid #555;border-radius:5px;padding:3px}input[type=checkbox]{width:18px;height:18px;accent-color:#eee}.style-tools input[type=number]{width:55px}.range input{width:66px}footer{display:flex;gap:10px;padding:18px 24px;border-top:1px solid #363a45}footer span{flex:1}.ok{background:#eee;color:#131313}.hint{font-size:12px;line-height:1.6;color:#92949a}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #7e57c2;outline-offset:2px}input:disabled{opacity:.4}`]})
export class RsiSettingsComponent implements OnChanges {
  @Input() settings=defaultRsiSettings();@Output() apply=new EventEmitter<RsiSettings>();@Output() cancel=new EventEmitter<void>();
  @ViewChild('close') set close(ref:ElementRef<HTMLButtonElement>|undefined){ref?.nativeElement.focus();}
  draft=defaultRsiSettings(); defaults=defaultRsiSettings;error='';tab='Inputs';tabs=['Inputs','Style','Visibility'];frames=Object.keys(this.draft.visibility);
  sources=['close','open','high','low','hl2','hlc3','ohlc4','hlcc4'];maTypes=['None','SMA','SMA + Bollinger Bands','EMA','SMMA (RMA)','WMA','VWMA'];
  styleItems=[{key:'rsi',label:'RSI',line:true},{key:'ma',label:'RSI-based MA',line:true},{key:'bull',label:'Regular Bullish',line:true},{key:'bullLabel',label:'Regular Bullish Label'},{key:'bear',label:'Regular Bearish',line:true},{key:'bearLabel',label:'Regular Bearish Label'},{key:'upper',label:'RSI Upper Band',band:true},{key:'middle',label:'RSI Middle Band',band:true},{key:'lower',label:'RSI Lower Band',band:true},{key:'background',label:'RSI Background Fill'},{key:'overbought',label:'Overbought Gradient Fill'},{key:'oversold',label:'Oversold Gradient Fill'},{key:'bb',label:'Bollinger Bands',line:true},{key:'bbFill',label:'Bollinger Bands Background Fill'}];
  ngOnChanges():void {this.draft=JSON.parse(JSON.stringify(this.settings));}
  save():void {
    const d=this.draft,i=d.inputs;
    if([i.period,i.ma_length].some(n=>!Number.isInteger(n)||n<1||n>1000)||!Number.isFinite(i.bb_mult)||i.bb_mult<.001||i.bb_mult>50
       ||Object.values(d.styles).some(s=>!Number.isInteger(s.width)||s.width<1||s.width>4||(s.value!==undefined&&(!Number.isFinite(s.value)||s.value<0||s.value>100)))
       ||Object.values(d.visibility).some(r=>!Number.isInteger(r.min)||!Number.isInteger(r.max)||r.min<1||r.max<r.min)) {this.error='Enter valid lengths, band levels and visibility ranges.';return;}
    this.apply.emit(JSON.parse(JSON.stringify(d)));
  }
  trap(event:Event):void {const e=event as KeyboardEvent,controls=Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('button,input,select')).filter(x=>x.offsetParent!==null&&!x.hasAttribute('disabled')),first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
  @HostListener('document:keydown.escape',['$event']) escape(e:Event):void {e.stopPropagation();this.cancel.emit();}
}
