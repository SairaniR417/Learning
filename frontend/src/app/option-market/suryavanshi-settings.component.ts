import { CommonModule } from '@angular/common';
import { Component,Input,Output,EventEmitter,OnChanges,HostListener,ViewChild,ElementRef } from '@angular/core';
import { SuryavanshiSettings,defaultSuryavanshiSettings } from './suryavanshi.types';

@Component({selector:'app-suryavanshi-settings',standalone:true,imports:[CommonModule],template:`
<div class="backdrop" (click)="cancel.emit()"><section role="dialog" aria-modal="true" aria-label="Suryavanshi settings" (click)="$event.stopPropagation()" (keydown.tab)="trap($event)">
<header><h2>Suryavanshi</h2><button #close aria-label="Close Suryavanshi settings" (click)="cancel.emit()">×</button></header>
<nav><button *ngFor="let t of tabs" [class.active]="tab===t" (click)="tab=t">{{t}}</button></nav>
<div class="content">
<ng-container *ngIf="tab==='Inputs'">
<h3>&rarr; Core settings <span style="color:#f66">&#9670;</span></h3>
<label>Length<input type="number" min="0" max="5000" [value]="draft.inputs.length" (input)="draft.inputs.length=+$any($event.target).value" title="Swing Length"></label>
<label>Type &rarr;<select [value]="draft.inputs.candle_type" (change)="draft.inputs.candle_type=$any($event.target).value"><option>Wicks</option><option>Body</option></select></label>
<label>RR Ratio<input type="number" step="0.1" [value]="draft.inputs.rr_ratio" (input)="draft.inputs.rr_ratio=+$any($event.target).value"></label>
<label>SL Type<select [value]="draft.inputs.sl_type" (change)="draft.inputs.sl_type=$any($event.target).value"><option>Close</option><option>High/Low</option></select></label>
<label><span><input type="checkbox" [checked]="draft.inputs.show_sl" (change)="draft.inputs.show_sl=$any($event.target).checked"> Show SL</span></label>
<label>Line Style<span class="tools"><select [value]="draft.lineStyle" (change)="draft.lineStyle=$any($event.target).value"><option>Dashed</option><option>Solid</option><option>Dotted</option></select><input type="color" aria-label="Bull line color" [value]="draft.bull" (input)="draft.bull=$any($event.target).value"><input type="color" aria-label="Bear line color" [value]="draft.bear" (input)="draft.bear=$any($event.target).value"></span></label>
</ng-container>
<ng-container *ngIf="tab==='Style'">
<label><span><input type="checkbox" [checked]="draft.barColor" (change)="draft.barColor=$any($event.target).checked"> Bar Color</span></label>
<label class="indented" *ngFor="let n of [0,1,2,3]">Color {{n}}<input type="color" [attr.aria-label]="'Bar Color '+n" [value]="draft.barColors[n]" (input)="draft.barColors[n]=$any($event.target).value"></label>
<label><span><input type="checkbox" [checked]="draft.plotCandle" (change)="draft.plotCandle=$any($event.target).checked"> PlotCandle</span></label>
<h4>Body</h4><label class="indented" *ngFor="let n of [0,1,2,3]">Color {{n}}<input type="color" [attr.aria-label]="'Body Color '+n" [value]="draft.bodyColors[n]" (input)="draft.bodyColors[n]=$any($event.target).value"></label>
<label class="indented">Wick<input type="color" aria-label="Wick color" [value]="draft.wick" (input)="draft.wick=$any($event.target).value"></label>
<h4>Border</h4><label class="indented" *ngFor="let n of [0,1,2,3]">Color {{n}}<input type="color" [attr.aria-label]="'Border Color '+n" [value]="draft.borderColors[n]" (input)="draft.borderColors[n]=$any($event.target).value"></label>
<label><span><input type="checkbox" [checked]="draft.background" (change)="draft.background=$any($event.target).checked"> Background Color</span></label>
<label class="indented" *ngFor="let n of [0,1,2]">Color {{n}}<span class="tools"><input type="color" [attr.aria-label]="'Background Color '+n" [value]="draft.backgroundColors[n]" (input)="draft.backgroundColors[n]=$any($event.target).value"><input type="number" min="0" max="100" [attr.aria-label]="'Background opacity '+n" [value]="draft.backgroundOpacity[n]" (input)="draft.backgroundOpacity[n]=+$any($event.target).value">%</span></label>
<h3>Graphic objects</h3><label><span><input type="checkbox" [checked]="draft.paneLabels" (change)="draft.paneLabels=$any($event.target).checked"> Pane labels</span></label>
<label><span><input type="checkbox" [checked]="draft.lines" (change)="draft.lines=$any($event.target).checked"> Lines</span></label><label><span><input type="checkbox" [checked]="draft.tables" (change)="draft.tables=$any($event.target).checked"> Tables</span></label>
<h3>Output values</h3><label>Precision<select [value]="draft.precision" (change)="draft.precision=+$any($event.target).value"><option value="-1">Default</option><option *ngFor="let n of [0,1,2,3,4,5,6,7,8]" [value]="n">{{n}}</option></select></label>
<label><span><input type="checkbox" [checked]="draft.scaleLabels" (change)="draft.scaleLabels=$any($event.target).checked"> Labels on price scale</span></label>
<label><span><input type="checkbox" [checked]="draft.statusValues" (change)="draft.statusValues=$any($event.target).checked"> Values in status line</span></label>
<h3>Input values</h3><label><span><input type="checkbox" [checked]="draft.statusInputs" (change)="draft.statusInputs=$any($event.target).checked"> Inputs in status line</span></label>
</ng-container>
<ng-container *ngIf="tab==='Visibility'"><label *ngFor="let frame of frames"><span><input type="checkbox" [checked]="draft.visibility[frame].enabled" (change)="draft.visibility[frame].enabled=$any($event.target).checked">{{frame}}</span><span class="range" *ngIf="frame!=='Ticks'&&frame!=='Ranges'"><input type="number" min="1" [value]="draft.visibility[frame].min" (input)="draft.visibility[frame].min=+$any($event.target).value" [attr.aria-label]="frame+' minimum'">to<input type="number" min="1" [value]="draft.visibility[frame].max" (input)="draft.visibility[frame].max=+$any($event.target).value" [attr.aria-label]="frame+' maximum'"></span></label><p class="hint">Visibility applies to supported chart timeframes. Tick, second and range feeds are unavailable.</p></ng-container>
<p *ngIf="error" role="alert">{{error}}</p>
</div><footer><button (click)="draft=defaults()">Defaults</button><span></span><button (click)="cancel.emit()">Cancel</button><button class="ok" (click)="save()">Ok</button></footer>
</section></div>`,styles:[`
.backdrop{position:fixed;inset:0;background:#0009;z-index:2100;display:flex;align-items:center;justify-content:center;padding:16px}section{width:440px;max-width:100%;max-height:90vh;background:#131313;color:#b2b5be;border:1px solid #363a45;border-radius:10px;display:flex;flex-direction:column;color-scheme:dark;font:14px Arial}header{display:flex;justify-content:space-between;align-items:center;padding:20px 24px}h2{font-size:20px;margin:0}button,input,select{font:inherit;color:inherit}button{background:#131313;border:1px solid #555;border-radius:7px;padding:8px 14px;cursor:pointer}header button{border:0;font-size:24px}nav{display:flex;gap:24px;margin:0 24px;border-bottom:3px solid #363a45}nav button{padding:10px 0;border:0;border-radius:0}.active{box-shadow:0 3px #eee;color:#eee}.content{overflow:auto;padding:12px 24px}h3{text-transform:uppercase;font-size:10px;font-weight:400;margin:26px 0}label{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:20px 0}label span{display:flex;align-items:center;gap:8px}input[type=number],select{width:118px;background:#141414;border:1px solid #555;padding:9px;border-radius:6px;box-sizing:border-box}input[type=color]{width:36px;height:32px;background:#202024;border:1px solid #555;border-radius:5px;padding:3px;margin-right:0}input[type=checkbox]{width:18px;height:18px;accent-color:#eee}.indented{padding-left:32px}h4{font-weight:400;margin:20px 32px 8px}.tools input{width:50px}.tools select{width:100px}.range input{width:66px}footer{display:flex;gap:10px;padding:18px 24px;border-top:1px solid #363a45}footer span{flex:1}.ok{background:#eee;color:#131313}.hint{font-size:12px;line-height:1.6;color:#92949a}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #ff8000;outline-offset:2px}`]})
export class SuryavanshiSettingsComponent implements OnChanges {
  @Input() settings=defaultSuryavanshiSettings();@Output() apply=new EventEmitter<SuryavanshiSettings>();@Output() cancel=new EventEmitter<void>();
  @ViewChild('close') set close(ref:ElementRef<HTMLButtonElement>|undefined){ref?.nativeElement.focus();}
  draft=defaultSuryavanshiSettings();defaults=defaultSuryavanshiSettings;error='';tab='Inputs';tabs=['Inputs','Style','Visibility'];
  frames=Object.keys(this.draft.visibility);
  ngOnChanges():void{this.draft=JSON.parse(JSON.stringify(this.settings));}
  save():void{
    if(!Number.isInteger(this.draft.inputs.length)||this.draft.inputs.length<0||this.draft.inputs.length>5000||!Number.isFinite(this.draft.inputs.rr_ratio)
       ||this.draft.backgroundOpacity.some(n=>!Number.isFinite(n)||n<0||n>100)
       ||Object.values(this.draft.visibility).some(r=>!Number.isInteger(r.min)||!Number.isInteger(r.max)||r.min<1||r.max<r.min)){this.error='Enter a valid Length, RR Ratio, opacity and visibility range.';return;}
    this.apply.emit(JSON.parse(JSON.stringify(this.draft)));
  }
  trap(event:Event):void{const e=event as KeyboardEvent,controls=Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('button,input,select')).filter(x=>x.offsetParent!==null&&!x.hasAttribute('disabled')),first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
  @HostListener('document:keydown.escape',['$event']) escape(e:Event):void{e.stopPropagation();this.cancel.emit();}
}
