import { HistoricalCandle } from '../market-api.service';
import { defaultSuryavanshiSettings } from './suryavanshi.types';
export type GoldenInputs=Record<string,number|boolean>;
export const goldenPlots=['sma50','sma200','ema9','ema20'] as const;
export type GoldenPlot=typeof goldenPlots[number];
export interface GoldenOverlay {inputs:GoldenInputs;candles?:HistoricalCandle[];state:string;barsSinceCross:number|null;points:({timestamp:string}&Record<GoldenPlot,number|null>)[];events:{timestamp:string;index:number;direction:string;kind:string;price:number}[];}
export interface GoldenSettings {inputs:GoldenInputs;plots:Record<GoldenPlot,{enabled:boolean;color:string;width:number}>;labels:boolean;precision:number;scaleLabels:boolean;statusInputs:boolean;statusValues:boolean;visibility:ReturnType<typeof defaultSuryavanshiSettings>['visibility'];}
export function defaultGoldenSettings():GoldenSettings {
  return {inputs:{require_confirmation:false,ema_fast:9,ema_slow:20,sma_medium:50,sma_long:200,rsi_period:14,bullish_rsi:55,bearish_rsi:45,volume_lookback:20,volume_multiplier:1.5,breakout_lookback:20,slope_lookback:5,max_confirmation_bars:30},
    plots:{sma50:{enabled:true,color:'#ffb74d',width:2},sma200:{enabled:true,color:'#42a5f5',width:2},ema9:{enabled:false,color:'#26a69a',width:1},ema20:{enabled:false,color:'#ab47bc',width:1}},labels:true,precision:-1,scaleLabels:true,statusInputs:true,statusValues:true,visibility:defaultSuryavanshiSettings().visibility};
}
