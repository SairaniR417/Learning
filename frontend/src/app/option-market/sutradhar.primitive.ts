// Derived from Sutradhar by © sairanir23, MPL-2.0; see docs/sutradhar.pine.
import { IChartApi,ISeriesApi,ISeriesPrimitive,IPrimitivePaneView,SeriesAttachedParameter,Time,UTCTimestamp,Logical } from 'lightweight-charts';
import { CanvasRenderingTarget2D } from 'fancy-canvas';
import { SutradharOverlay,SutradharSettings,SutradharLevel,sutradharLevels } from './sutradhar.types';

/** Pine's four translucent fills and last-bar labels one bar to the right. */
export class SutradharPrimitive implements ISeriesPrimitive<Time> {
  private chart?:IChartApi;private series?:ISeriesApi<any>;private request?:()=>void;
  constructor(private overlay:SutradharOverlay,private settings:SutradharSettings){}
  attached(p:SeriesAttachedParameter<Time>):void{this.chart=p.chart;this.series=p.series;this.request=p.requestUpdate;}
  detached():void{this.chart=undefined;this.series=undefined;this.request=undefined;}
  update(o:SutradharOverlay,s:SutradharSettings):void{this.overlay=o;this.settings=s;this.request?.();}
  paneViews():readonly IPrimitivePaneView[]{return[{zOrder:()=> 'bottom',renderer:()=>({draw:t=>this.fills(t)})},{zOrder:()=> 'top',renderer:()=>({draw:t=>this.labels(t)})}];}
  private x(t:string):number|null{return this.chart?.timeScale().timeToCoordinate(Date.parse(t)/1000 as UTCTimestamp)??null;}
  private y(p:number):number|null{return this.series?.priceToCoordinate(p)??null;}
  private fills(target:CanvasRenderingTarget2D):void{
    if(!this.settings.fills)return;
    target.useMediaCoordinateSpace(({context:ctx,mediaSize})=>{
      ctx.save();
      const zones:[SutradharLevel,SutradharLevel,string][]=[['Flow','Crest','#ff40001f'],['Value','Base','#00ff001f'],['Crest','Crown','#ff60000f'],['Base','Origin','#00ff600f']];
      for(let i=1;i<this.overlay.points.length;i++){
        const a=this.overlay.points[i-1],b=this.overlay.points[i],x1=this.x(a.timestamp),x2=this.x(b.timestamp);
        if(x1==null||x2==null||x2<0||x1>mediaSize.width)continue;
        for(const [upper,lower,color] of zones){
          if(!this.settings.plots[upper].enabled||!this.settings.plots[lower].enabled)continue;
          if([a[upper],b[upper],a[lower],b[lower]].some(v=>v==null))continue;
          const coords=[[x1,this.y(a[upper]!)],[x2,this.y(b[upper]!)],[x2,this.y(b[lower]!)],[x1,this.y(a[lower]!)]];
          if(coords.some(c=>c[1]==null))continue;
          ctx.fillStyle=color;ctx.beginPath();coords.forEach(([x,y],n)=>n?ctx.lineTo(x!,y!):ctx.moveTo(x!,y!));ctx.closePath();ctx.fill();
        }
      }ctx.restore();
    });
  }
  private labels(target:CanvasRenderingTarget2D):void{
    if(!this.settings.labels||!this.settings.paneLabels||!this.chart)return;
    const point=this.overlay.points.at(-1);if(!point)return;
    const logical=this.chart.timeScale().timeToIndex(Date.parse(point.timestamp)/1000 as UTCTimestamp);
    if(logical==null)return;
    const x=this.chart.timeScale().logicalToCoordinate((logical+1) as Logical);if(x==null)return;
    target.useMediaCoordinateSpace(({context:ctx})=>{
      ctx.save();ctx.font='12px Arial';ctx.textBaseline='middle';
      // Source draws labels independently of the plot visibility checkboxes.
      for(const name of [...sutradharLevels.filter(n=>n!=='Mid'&&n!=='O'),'O','Mid'] as SutradharLevel[]){
        const value=point[name];if(value==null)continue;const y=this.y(value);if(y==null)continue;
        const width=ctx.measureText(name).width+14;ctx.fillStyle=this.settings.colors[name]+(name==='Mid'?'99':'');
        ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+6,y-10);ctx.lineTo(x+width,y-10);ctx.lineTo(x+width,y+10);ctx.lineTo(x+6,y+10);ctx.closePath();ctx.fill();
        ctx.fillStyle=['Crown','O','Mid'].includes(name)?'#fff':'#363a45';ctx.fillText(name,x+8,y);
      }ctx.restore();
    });
  }
}
