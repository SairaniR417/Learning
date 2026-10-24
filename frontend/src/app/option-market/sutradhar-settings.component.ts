// Derived from Sutradhar by © sairanir23, MPL-2.0; see docs/sutradhar.pine.
import { CommonModule } from '@angular/common';
import { Component,Input,Output,EventEmitter,OnChanges,HostListener,ViewChild,ElementRef } from '@angular/core';
import { SutradharSettings,SutradharLevel,defaultSutradharSettings,sutradharLevels } from './sutradhar.types';

@Component({selector:'app-sutradhar-settings',standalone:true,imports:[CommonModule],template:`
<div class="backdrop" (click)="cancel.emit()"><section role="dialog" aria-modal="true" aria-label="Sutradhar settings" (click)="$event.stopPropagation()" (keydown.tab)="trap($event)">
<header><h2>Sutradhar</h2><button #close aria-label="Close Sutradhar settings" (click)="cancel.emit()">×</button></header>
<nav><button *ngFor="let t of tabs" [class.active]="tab===t" (click)="tab=t">{{t}}</button></nav>
<div class="content">
<ng-container *ngIf="tab==='Inputs'">
<label><span><input type="checkbox" [checked]="draft.labels" (change)="draft.labels=$any($event.target).checked"> Show Labels</span></label>
<label><span><input type="checkbox" [checked]="draft.fills" (change)="draft.fills=$any($event.target).checked"> Show Fills</span></label>
<label><span><input type="checkbox" [checked]="draft.inputs.use_ema" (change)="draft.inputs.use_ema=$any($event.target).checked"> Use EMA instead of SMA</span></label>
<label>Period 1 (Flow/Value)<input type="number" min="1" max="1000" [value]="draft.inputs.p1" (input)="draft.inputs.p1=+$any($event.target).value"></label>
<label>Period 2 (Crest/Base)<input type="number" min="1" max="1000" [value]="draft.inputs.p2" (input)="draft.inputs.p2=+$any($event.target).value"></label>
<label>Period 3 (Crown/Origin)<input type="number" min="1" max="1000" [value]="draft.inputs.p3" (input)="draft.inputs.p3=+$any($event.target).value"></label>
<label *ngFor="let name of colorNames">{{name==='O'?'Open':name}}<input type="color" [value]="draft.colors[name]" (input)="color(name,$any($event.target).value)" [attr.aria-label]="name+' color'"></label>
</ng-container>
<ng-container *ngIf="tab==='Style'">
<label *ngFor="let name of levels"><span><input type="checkbox" [checked]="draft.plots[name].enabled" (change)="draft.plots[name].enabled=$any($event.target).checked">{{name}}</span><span class="tools"><input type="number" min="1" max="4" [value]="draft.plots[name].width" (input)="draft.plots[name].width=+$any($event.target).value" [attr.aria-label]="name+' width'"><select [value]="draft.plots[name].style" (change)="draft.plots[name].style=$any($event.target).value" [attr.aria-label]="name+' plot style'"><option value="line">Line</option><option value="circles">Circles</option><option value="step">Step line</option></select></span></label>
<h3>Graphic objects</h3><label><span><input type="checkbox" [checked]="draft.paneLabels" (change)="draft.paneLabels=$any($event.target).checked"> Pane labels</span></label>
<h3>Output values</h3><label>Precision<select [value]="draft.precision" (change)="draft.precision=+$any($event.target).value"><option value="-1">Default</option><option *ngFor="let n of [0,1,2,3,4,5,6,7,8]" [value]="n">{{n}}</option></select></label>
<label><span><input type="checkbox" [checked]="draft.scaleLabels" (change)="draft.scaleLabels=$any($event.target).checked"> Labels on price scale</span></label>
<label><span><input type="checkbox" [checked]="draft.statusValues" (change)="draft.statusValues=$any($event.target).checked"> Values in status line</span></label>
<h3>Input values</h3><label><span><input type="checkbox" [checked]="draft.statusInputs" (change)="draft.statusInputs=$any($event.target).checked"> Inputs in status line</span></label>
</ng-container>
<ng-container *ngIf="tab==='Visibility'"><label *ngFor="let frame of frames"><span><input type="checkbox" [checked]="draft.visibility[frame].enabled" (change)="draft.visibility[frame].enabled=$any($event.target).checked">{{frame}}</span><span class="range" *ngIf="frame!=='Ticks'&&frame!=='Ranges'"><input type="number" min="1" [value]="draft.visibility[frame].min" (input)="draft.visibility[frame].min=+$any($event.target).value" [attr.aria-label]="frame+' minimum'">to<input type="number" min="1" [value]="draft.visibility[frame].max" (input)="draft.visibility[frame].max=+$any($event.target).value" [attr.aria-label]="frame+' maximum'"></span></label><p class="hint">Sutradhar runs on intraday charts only. Tick/second feeds are unavailable in this application.</p></ng-container>
<p *ngIf="error" role="alert">{{error}}</p>
</div><footer><button (click)="draft=defaults()">Defaults</button><span></span><button (click)="cancel.emit()">Cancel</button><button class="ok" (click)="save()">Ok</button></footer>
</section></div>`,styles:[`
.backdrop{position:fixed;inset:0;background:#0009;z-index:2100;display:flex;align-items:center;justify-content:center;padding:16px}section{width:440px;max-width:100%;max-height:90vh;background:#131313;color:#b2b5be;border:1px solid #363a45;border-radius:10px;display:flex;flex-direction:column;color-scheme:dark;font:14px Arial}header{display:flex;justify-content:space-between;align-items:center;padding:20px 24px}h2{font-size:20px;margin:0}button,input,select{font:inherit;color:inherit}button{background:#131313;border:1px solid #555;border-radius:7px;padding:8px 14px;cursor:pointer}header button{border:0;font-size:24px}nav{display:flex;gap:24px;margin:0 24px;border-bottom:3px solid #363a45}nav button{padding:10px 0;border:0;border-radius:0}.active{box-shadow:0 3px #eee;color:#eee}.content{overflow:auto;padding:12px 24px}h3{text-transform:uppercase;font-size:10px;font-weight:400;margin:26px 0}label{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:20px 0}label span{display:flex;align-items:center;gap:8px}input[type=number],select{width:118px;background:#141414;border:1px solid #555;padding:9px;border-radius:6px;box-sizing:border-box}input[type=color]{width:36px;height:32px;background:#202024;border:1px solid #555;border-radius:5px;padding:3px;margin-right:82px}input[type=checkbox]{width:18px;height:18px;accent-color:#eee}.tools input{width:50px}.tools select{width:100px}.range input{width:66px}footer{display:flex;gap:10px;padding:18px 24px;border-top:1px solid #363a45}footer span{flex:1}.ok{background:#eee;color:#131313}.hint{font-size:12px;line-height:1.6;color:#92949a}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #ff8000;outline-offset:2px}`]})
export class SutradharSettingsComponent implements OnChanges {
  @Input() settings=defaultSutradharSettings();@Output() apply=new EventEmitter<SutradharSettings>();@Output() cancel=new EventEmitter<void>();
  @ViewChild('close') set close(ref:ElementRef<HTMLButtonElement>|undefined){ref?.nativeElement.focus();}
  draft=defaultSutradharSettings();defaults=defaultSutradharSettings;error='';tab='Inputs';tabs=['Inputs','Style','Visibility'];
  levels=sutradharLevels;colorNames=sutradharLevels.filter(n=>n!=='Mid');frames=Object.keys(this.draft.visibility);
  ngOnChanges():void{this.draft=JSON.parse(JSON.stringify(this.settings));}
  color(name:SutradharLevel,value:string):void{this.draft.colors[name]=value;if(name==='O')this.draft.colors.Mid=value;}
  save():void{
    if([this.draft.inputs.p1,this.draft.inputs.p2,this.draft.inputs.p3].some(n=>!Number.isInteger(n)||n<1||n>1000)
       ||Object.values(this.draft.plots).some(p=>!Number.isInteger(p.width)||p.width<1||p.width>4)
       ||Object.values(this.draft.visibility).some(r=>!Number.isInteger(r.min)||!Number.isInteger(r.max)||r.min<1||r.max<r.min)) {this.error='Enter valid periods, widths and visibility ranges.';return;}
    this.apply.emit(JSON.parse(JSON.stringify(this.draft)));
  }
  trap(event:Event):void{const e=event as KeyboardEvent,controls=Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('button,input,select')).filter(x=>x.offsetParent!==null&&!x.hasAttribute('disabled')),first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
  @HostListener('document:keydown.escape',['$event']) escape(e:Event):void{e.stopPropagation();this.cancel.emit();}
}
