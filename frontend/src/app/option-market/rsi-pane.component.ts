import { CommonModule } from '@angular/common';
import { Component, Input, ElementRef, ViewChild, AfterViewInit, OnChanges, OnDestroy } from '@angular/core';
import { createChart, ColorType, LineSeries, IChartApi, ISeriesApi, UTCTimestamp, LineWidth, Time, MouseEventParams } from 'lightweight-charts';
import { RsiOverlay,RsiSettings,defaultRsiSettings,rsiVisible } from './rsi.types';
import { RsiPrimitive } from './rsi.primitive';

@Component({selector:'app-rsi-pane',standalone:true,imports:[CommonModule],host:{'[class.shared-rsi]':'!!sharedChart'},template:`<div class="rsi-values" *ngIf="!sharedChart && settings.statusValues">RSI {{ last?.rsi == null ? 'n/a' : last?.rsi | number:digits }} <span [style.color]="settings.styles['ma'].color">MA {{ last?.ma == null ? 'n/a' : last?.ma | number:digits }}</span></div><div #host class="rsi-canvas" [hidden]="!!sharedChart" aria-label="RSI divergence chart"></div>`,styles:[`:host{display:flex;flex-direction:column;height:100%;min-height:360px;background:#000;color:#b2b5be}:host(.shared-rsi){display:none!important}.rsi-canvas{flex:1;min-height:340px}.rsi-values{font:12px Arial;padding:4px 0 8px}.rsi-values span{margin-left:14px}`]})
export class RsiPaneComponent implements AfterViewInit,OnChanges,OnDestroy {
  @Input() data?:RsiOverlay; @Input() settings:RsiSettings=defaultRsiSettings(); @Input() interval=5;
  @Input() sharedChart?:IChartApi;
  @ViewChild('host') host?:ElementRef<HTMLElement>;
  private chart?:IChartApi; private rsi?:ISeriesApi<'Line'>; private ma?:ISeriesApi<'Line'>;
  private bb:ISeriesApi<'Line'>[]=[]; private divergence:ISeriesApi<'Line'>[]=[];private primitive?:RsiPrimitive;
  private fitted=false; private hovered?:number;
  private ownsChart=true;
  private paneIndex=0;
  private crosshairMoved=(e:MouseEventParams<Time>)=>{this.hovered=typeof e.time==='number'?e.time*1000:undefined;};
  get last(){return this.data?.points.find(p=>Date.parse(p.timestamp)===this.hovered)??this.data?.points.at(-1);}
  get digits(){return '1.'+this.settings.precision+'-'+this.settings.precision;}
  ngAfterViewInit():void {
    if(!this.host&&!this.sharedChart)return;
    this.ownsChart=!this.sharedChart;this.paneIndex=this.sharedChart?1:0;
    this.chart=this.sharedChart??createChart(this.host!.nativeElement,{autoSize:true,layout:{background:{type:ColorType.Solid,color:'#000'},textColor:'#b2b5be'},grid:{vertLines:{visible:false},horzLines:{visible:false}},rightPriceScale:{scaleMargins:{top:.15,bottom:.15}},timeScale:{timeVisible:true,secondsVisible:false,rightOffset:4},localization:{timeFormatter:(t:Time)=>new Date(Number(t)*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})}});
    this.rsi=this.chart.addSeries(LineSeries,{priceLineVisible:false,autoscaleInfoProvider:()=>({priceRange:{minValue:0,maxValue:100}})},this.paneIndex);
    this.ma=this.chart.addSeries(LineSeries,{priceLineVisible:false},this.paneIndex);
    this.bb=[0,1].map(()=>this.chart!.addSeries(LineSeries,{priceLineVisible:false,lastValueVisible:false},this.paneIndex));
    this.rsi.priceScale().applyOptions({scaleMargins:{top:.12,bottom:.12}});
    if(this.sharedChart){
      this.chart.applyOptions({layout:{panes:{separatorColor:'#292929',separatorHoverColor:'#555555',enableResize:true}}});
      this.chart.panes()[0].setStretchFactor(3);this.chart.panes()[1].setStretchFactor(2);
    }
    this.chart.subscribeCrosshairMove(this.crosshairMoved);
    this.draw();
  }
  ngOnChanges():void {this.draw();}
  private draw():void {
    if(!this.chart||!this.rsi||!this.ma)return;
    const s=this.settings.styles,visible=rsiVisible(this.settings,this.interval),points=visible?this.data?.points??[]:[];
    const format={type:'price' as const,precision:this.settings.precision,minMove:10**(-this.settings.precision)};
    this.rsi.applyOptions({visible:visible&&s['rsi'].enabled,color:s['rsi'].color,lineWidth:s['rsi'].width as LineWidth,lastValueVisible:this.settings.scaleLabels,priceFormat:format});
    this.ma.applyOptions({visible:visible&&s['ma'].enabled,color:s['ma'].color,lineWidth:s['ma'].width as LineWidth,lastValueVisible:this.settings.scaleLabels,priceFormat:format});
    const line=(key:'rsi'|'ma'|'bbUpper'|'bbLower')=>points.map(p=>({time:(Date.parse(p.timestamp)/1000) as UTCTimestamp,...(p[key]==null?{}:{value:p[key]!})}));
    this.rsi.setData(line('rsi'));this.ma.setData(line('ma'));
    this.bb.forEach((b,i)=>{b.applyOptions({visible:visible&&s['bb'].enabled,color:s['bb'].color,lineWidth:s['bb'].width as LineWidth});b.setData(line(i?'bbLower':'bbUpper'));});
    if(this.primitive){this.rsi.detachPrimitive(this.primitive);this.primitive=undefined;}
    for(const series of this.divergence)this.chart.removeSeries(series);this.divergence=[];
    for(const key of ['upper','middle','lower']){
      const style=s[key];if(!visible||!style.enabled)continue;
      const series=this.chart.addSeries(LineSeries,{color:style.color+(key==='middle'?'80':''),lineWidth:style.width as LineWidth,lineStyle:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false},this.paneIndex);
      series.setData(points.map(p=>({time:Date.parse(p.timestamp)/1000 as UTCTimestamp,value:style.value??50})));this.divergence.push(series);
    }
    if(visible&&this.data){
      this.primitive=new RsiPrimitive(this.data,this.settings,!!this.sharedChart);this.rsi.attachPrimitive(this.primitive);
      for(const e of this.data.events){
        const style=s[e.direction==='BULLISH'?'bull':'bear'];if(!style.enabled)continue;
        const series=this.chart.addSeries(LineSeries,{color:style.color,lineWidth:Math.max(2,style.width) as LineWidth,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false},this.paneIndex);
        series.setData([{time:Date.parse(e.pivot1At)/1000 as UTCTimestamp,value:e.pivot1Rsi},{time:Date.parse(e.pivot2At)/1000 as UTCTimestamp,value:e.pivot2Rsi}]);this.divergence.push(series);
      }
    }
    if(points.length&&!this.fitted){this.chart.timeScale().fitContent();this.fitted=true;}
  }
  releaseSharedChart():void {
    if(!this.chart||this.ownsChart)return;
    this.chart.unsubscribeCrosshairMove(this.crosshairMoved);
    if(this.primitive&&this.rsi)this.rsi.detachPrimitive(this.primitive);
    this.primitive=undefined;
    for(const series of [...this.divergence,...this.bb,...(this.ma?[this.ma]:[]),...(this.rsi?[this.rsi]:[])])this.chart.removeSeries(series);
    this.chart=undefined;this.rsi=undefined;this.ma=undefined;this.bb=[];this.divergence=[];
  }
  ngOnDestroy():void {if(this.ownsChart)this.chart?.remove();else this.releaseSharedChart();}
}
