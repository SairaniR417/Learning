export interface RsiInputs { period:number; source:string; calculate_divergence:boolean; ma_type:string; ma_length:number; bb_mult:number; timeframe:number; wait_close:boolean; }
export interface RsiPoint { timestamp:string; rsi:number|null; ma:number|null; bbUpper:number|null; bbLower:number|null; }
export interface RsiEvent { divergenceType:string; direction:string; pivot1At:string; pivot2At:string; detectedAt:string; pivot1Rsi:number; pivot2Rsi:number; pivot1Price:number; pivot2Price:number; detectedIndex:number; }
export interface RsiOverlay { points:RsiPoint[]; events:RsiEvent[]; settings:RsiInputs; interval:number; }
export interface RsiSettings {
  inputs:RsiInputs;
  styles:Record<string,{enabled:boolean;color:string;width:number;value?:number}>;
  precision:number; scaleLabels:boolean; statusValues:boolean; statusInputs:boolean;
  visibility:Record<string,{enabled:boolean;min:number;max:number}>;
}
export function defaultRsiSettings():RsiSettings {
  const style=(color:string,enabled=true,value?:number)=>({enabled,color,width:1,value});
  return {inputs:{period:14,source:'close',calculate_divergence:true,ma_type:'SMA',ma_length:14,bb_mult:2,timeframe:0,wait_close:true},
    styles:{rsi:style('#7e57c2'),ma:style('#fdd835'),bull:style('#4caf50'),bullLabel:style('#4caf50'),bear:style('#f23645'),bearLabel:style('#f23645'),
      upper:style('#787b86',false,70),middle:style('#787b86',false,50),lower:style('#787b86',false,30),background:style('#7e57c2'),overbought:style('#4caf50'),oversold:style('#f23645'),bb:style('#4caf50'),bbFill:style('#4caf50')},
    precision:2,scaleLabels:true,statusValues:true,statusInputs:true,
    visibility:Object.fromEntries(Object.entries({Ticks:1,Seconds:59,Minutes:59,Hours:24,Days:366,Weeks:52,Months:12,Ranges:1}).map(([key,max])=>[key,{enabled:true,min:1,max}]))};
}
export function rsiVisible(settings:RsiSettings,interval:number):boolean {
  const key=interval>=10080?'Weeks':interval>=1440?'Days':interval>=60?'Hours':'Minutes';
  const n=interval/(key==='Weeks'?10080:key==='Days'?1440:key==='Hours'?60:1), r=settings.visibility[key];
  return r.enabled && n>=r.min && n<=r.max;
}
