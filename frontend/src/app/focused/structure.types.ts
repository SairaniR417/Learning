export interface PriceZone { price:number; low:number; high:number; touches:number; lastDate:string; origin:string; distancePct:number; }
export interface SwingPoint { index:number; kind:string; price:number; date:string; }
export interface CandlePattern {
  name:string;bias:'bullish'|'bearish'|'neutral';state:string;forming:boolean;at:string;startAt:string;
  high:number;low:number;explanation:string;context:string;confirmation:string;followUpAt:string|null;
  volume:string;volumeRatio:number|null;
}
export interface StructureView {
  label:string; frame:string; scope:string; count:number; asOf:string|null; firstDate:string|null;
  trend:string; narrative:string[]; supports:PriceZone[]; resistances:PriceZone[];
  trendlines:{kind:string;start:SwingPoint;end:SwingPoint;current:number;state:string;note:string}[];
  events:string[];watch:string[];volume:{ratio:number|null;description:string}|null;
  high:{price:number;date:string}|null;low:{price:number;date:string}|null;close:number|null;
  swings:SwingPoint[];limitedCoverage?:boolean;staleData:boolean;oldHistory:boolean;source:string;developingExcluded:number;
  candlesticks?:{patterns:CandlePattern[];checkedThrough:string|null;note:string};
}
export interface StructureAnalysis { stock:{key:string;symbol:string;name:string};views:StructureView[];warnings:string[];receivedAt:string;methodology:string;historyContext:{firstDate:string|null;asOf:string|null;count:number;narrative:string[]}; }
