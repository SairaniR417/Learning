// Derived from Sutradhar by © sairanir23, MPL-2.0; see docs/sutradhar.pine.
import { HistoricalCandle } from '../market-api.service';
export const sutradharLevels=['Flow','Crest','Crown','Value','Base','Origin','Mid','O'] as const;
export type SutradharLevel=typeof sutradharLevels[number];
export interface SutradharInputs {p1:number;p2:number;p3:number;use_ema:boolean;}
export type SutradharPoint={timestamp:string}&Record<SutradharLevel,number|null>;
export interface SutradharOverlay {points:SutradharPoint[];settings:SutradharInputs;interval:number;status:string;message:string;candles?:HistoricalCandle[];}
export interface SutradharSettings {
  inputs:SutradharInputs;labels:boolean;fills:boolean;colors:Record<SutradharLevel,string>;
  plots:Record<SutradharLevel,{enabled:boolean;width:number;style:'line'|'circles'|'step'}>;
  paneLabels:boolean;precision:number;scaleLabels:boolean;statusValues:boolean;statusInputs:boolean;
  visibility:Record<string,{enabled:boolean;min:number;max:number}>;
}
export function defaultSutradharSettings():SutradharSettings {
  return {inputs:{p1:14,p2:7,p3:5,use_ema:false},labels:true,fills:true,
    colors:{Flow:'#ff8000',Crest:'#ff4000',Crown:'#ff0000',Value:'#80ff00',Base:'#00ff00',Origin:'#00ff80',O:'#808080',Mid:'#808080'},
    plots:Object.fromEntries(sutradharLevels.map(name=>[name,{enabled:true,width:name==='O'?2:1,style:['Crown','Origin'].includes(name)?'circles':name==='Mid'?'step':'line'}])) as SutradharSettings['plots'],
    paneLabels:true,precision:-1,scaleLabels:true,statusValues:true,statusInputs:true,
    visibility:Object.fromEntries(Object.entries({Ticks:1,Seconds:59,Minutes:59,Hours:24,Days:366,Weeks:52,Months:12,Ranges:1}).map(([name,max])=>[name,{enabled:true,min:1,max}]))};
}
export function sutradharVisible(s:SutradharSettings,interval:number):boolean {
  if(interval>=1440)return false;
  const key=interval>=60?'Hours':'Minutes',value=interval/(key==='Hours'?60:1),r=s.visibility[key];
  return r.enabled&&value>=r.min&&value<=r.max;
}
