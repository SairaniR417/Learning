import { HistoricalCandle } from '../market-api.service';
export interface SuryavanshiInputs {length:number;candle_type:'Wicks'|'Body';rr_ratio:number;sl_type:'Close'|'High/Low';show_sl:boolean;}
export interface SuryavanshiOverlay {
  inputs:SuryavanshiInputs;candles?:HistoricalCandle[];winningTrades:number;losingTrades:number;
  points:{timestamp:string;index:number;state:string;buy:boolean;sell:boolean}[];
  lines:{kind:string;x1:number;x2:number;y1:number|null;y2:number|null;direction?:string}[];
  labels:{kind:string;x:number;y:number|null;text?:string;direction?:string;sign?:string;state?:string;stop?:number|null}[];
}
export interface SuryavanshiSettings {
  inputs:SuryavanshiInputs;lineStyle:string;bull:string;bear:string;
  barColor:boolean;plotCandle:boolean;background:boolean;barColors:string[];bodyColors:string[];borderColors:string[];wick:string;backgroundColors:string[];backgroundOpacity:number[];
  paneLabels:boolean;lines:boolean;tables:boolean;precision:number;scaleLabels:boolean;statusValues:boolean;statusInputs:boolean;
  visibility:Record<string,{enabled:boolean;min:number;max:number}>;
}
export function defaultSuryavanshiSettings():SuryavanshiSettings {
  return {inputs:{length:20,candle_type:'Wicks',rr_ratio:1.1,sl_type:'Close',show_sl:false},lineStyle:'Dashed',bull:'#028545',bear:'#f60707',
    barColor:true,plotCandle:true,background:true,barColors:['#f60707','#026a59','#343436','#cd0202'],bodyColors:['#f60707','#026a59','#343436','#cd0202'],borderColors:['#f60707','#026a59','#343436','#cd0202'],wick:'#676363',backgroundColors:['#88040f','#08bf9e','#cd0202'],backgroundOpacity:[10,10,100],
    paneLabels:true,lines:true,tables:true,precision:-1,scaleLabels:true,statusValues:true,statusInputs:true,
    visibility:Object.fromEntries(Object.entries({Ticks:1,Seconds:59,Minutes:59,Hours:24,Days:366,Weeks:52,Months:12,Ranges:1}).map(([key,max])=>[key,{enabled:true,min:1,max}]))};
}
export function suryavanshiVisible(s:Pick<SuryavanshiSettings,'visibility'>,interval:number):boolean {
  const key=interval>=10080?'Weeks':interval>=1440?'Days':interval>=60?'Hours':'Minutes';
  const value=interval/({Weeks:10080,Days:1440,Hours:60,Minutes:1}[key]);const r=s.visibility[key];
  return r.enabled&&value>=r.min&&value<=r.max;
}
