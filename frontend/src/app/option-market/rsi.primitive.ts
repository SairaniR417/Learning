import { IChartApi, ISeriesApi, ISeriesPrimitive, IPrimitivePaneView, SeriesAttachedParameter, Time, UTCTimestamp } from 'lightweight-charts';
import { RsiOverlay, RsiSettings } from './rsi.types';
import { CanvasRenderingTarget2D } from 'fancy-canvas';

/** RSI band/gradient fills and absolute-coordinate Pine Bull/Bear shapes. */
export class RsiPrimitive implements ISeriesPrimitive<Time> {
  private chart?:IChartApi; private series?:ISeriesApi<any>; private request?:()=>void;
  constructor(private data:RsiOverlay,private settings:RsiSettings,private showLegend=false) {}
  attached(p:SeriesAttachedParameter<Time>):void {this.chart=p.chart;this.series=p.series;this.request=p.requestUpdate;}
  detached():void {this.chart=undefined;this.series=undefined;this.request=undefined;}
  update(data:RsiOverlay,settings:RsiSettings):void {this.data=data;this.settings=settings;this.request?.();}
  paneViews():readonly IPrimitivePaneView[] {return [{zOrder:()=> 'bottom',renderer:()=>({draw:t=>this.fills(t)})},{zOrder:()=> 'top',renderer:()=>({draw:t=>this.labels(t)})}];}
  private x(t:string):number|null {return this.chart?.timeScale().timeToCoordinate((Date.parse(t)/1000) as UTCTimestamp)??null;}
  private y(n:number):number {return this.series?.priceToCoordinate(n)??0;}
  private fills(target:CanvasRenderingTarget2D):void {
    target.useMediaCoordinateSpace(({context:ctx,mediaSize})=>{
      const s=this.settings.styles;ctx.save();
      if(s['background'].enabled){ctx.fillStyle=s['background'].color+'1a';ctx.fillRect(0,this.y(s['upper'].value??70),mediaSize.width,this.y(s['lower'].value??30)-this.y(s['upper'].value??70));}
      for(let i=1;i<this.data.points.length;i++){
        const a=this.data.points[i-1],b=this.data.points[i],x1=this.x(a.timestamp),x2=this.x(b.timestamp);
        if(x1==null||x2==null||x2<0||x1>mediaSize.width||a.rsi==null||b.rsi==null)continue;
        const polygon=(ys:number[],fill:string|CanvasGradient)=>{ctx.fillStyle=fill;ctx.beginPath();ctx.moveTo(x1,this.y(ys[0]));ctx.lineTo(x2,this.y(ys[1]));ctx.lineTo(x2,this.y(ys[2]));ctx.lineTo(x1,this.y(ys[3]));ctx.closePath();ctx.fill();};
        for(const [key,top,bottom] of [['overbought',100,70],['oversold',30,0]] as const){
          if(!s[key].enabled)continue;
          const gradient=ctx.createLinearGradient(0,this.y(top),0,this.y(bottom));
          gradient.addColorStop(0,s[key].color+(key==='overbought'?'ff':'00'));gradient.addColorStop(1,s[key].color+(key==='oversold'?'ff':'00'));
          // Pine fill joins RSI to the hidden 50 plot, with transparent color outside the gradient limits.
          ctx.save();ctx.beginPath();ctx.rect(0,this.y(top),mediaSize.width,this.y(bottom)-this.y(top));ctx.clip();polygon([a.rsi,b.rsi,50,50],gradient);ctx.restore();
        }
        if(s['bbFill'].enabled&&a.bbUpper!=null&&b.bbUpper!=null&&a.bbLower!=null&&b.bbLower!=null)polygon([a.bbUpper,b.bbUpper,b.bbLower,a.bbLower],s['bbFill'].color+'1a');
      }
      ctx.restore();
    });
  }
  private labels(target:CanvasRenderingTarget2D):void {
    target.useMediaCoordinateSpace(({context:ctx,mediaSize})=>{
      ctx.save();ctx.font='12px Arial';ctx.textAlign='center';ctx.textBaseline='middle';
      if(this.showLegend){
        const last=this.data.points.at(-1),format=(n:number|null|undefined)=>n==null?'n/a':n.toFixed(this.settings.precision);
        const title=this.settings.statusInputs?`RSI ${this.data.settings.period} ${this.data.settings.source}`:'RSI';
        ctx.textAlign='left';ctx.fillStyle='#b2b5be';ctx.fillText(title,10,14);
        if(this.settings.statusValues){ctx.fillStyle=this.settings.styles['rsi'].color;ctx.fillText(format(last?.rsi),140,14);ctx.fillStyle=this.settings.styles['ma'].color;ctx.fillText(format(last?.ma),200,14);}
        ctx.textAlign='center';
      }
      for(const e of this.data.events){
        const bull=e.direction==='BULLISH',s=this.settings.styles[bull?'bullLabel':'bearLabel'];if(!s.enabled)continue;
        const x=this.x(e.pivot2At);if(x==null||x< -30||x>mediaSize.width+30)continue;
        const y=this.y(e.pivot2Rsi),top=bull?y+5:y-25;
        ctx.fillStyle=s.color;ctx.beginPath();ctx.roundRect(x-22,top,44,20,2);ctx.fill();
        ctx.beginPath();ctx.moveTo(x-5,bull?top:top+20);ctx.lineTo(x,bull?y:y);ctx.lineTo(x+5,bull?top:top+20);ctx.fill();
        ctx.fillStyle='#ffffff';ctx.fillText(bull?'Bull':'Bear',x,top+10);
      }ctx.restore();
    });
  }
}
