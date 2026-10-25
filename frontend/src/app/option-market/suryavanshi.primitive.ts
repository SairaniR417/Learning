import { IChartApi,ISeriesApi,ISeriesPrimitive,IPrimitivePaneView,SeriesAttachedParameter,Time,Logical } from 'lightweight-charts';
import { CanvasRenderingTarget2D } from 'fancy-canvas';
import { SuryavanshiOverlay,SuryavanshiSettings } from './suryavanshi.types';

/** Retained Pine drawings, independently limited to 500 lines and 500 labels. */
export class SuryavanshiPrimitive implements ISeriesPrimitive<Time> {
  private chart?:IChartApi;private series?:ISeriesApi<any>;private request?:()=>void;
  private hits:{x:number;y:number;width:number;text:string}[]=[];
  constructor(private overlay:SuryavanshiOverlay,private settings:SuryavanshiSettings){}
  attached(p:SeriesAttachedParameter<Time>):void{this.chart=p.chart;this.series=p.series;this.request=p.requestUpdate;}
  detached():void{this.chart=undefined;this.series=undefined;this.request=undefined;this.hits=[];}
  update(o:SuryavanshiOverlay,s:SuryavanshiSettings):void{this.overlay=o;this.settings=s;this.request?.();}
  tooltipAt(x:number,y:number):string{return this.hits.find(h=>x>=h.x&&x<=h.x+h.width&&Math.abs(y-h.y)<=11)?.text??'';}
  paneViews():readonly IPrimitivePaneView[]{return [{zOrder:()=> 'bottom',renderer:()=>({draw:t=>this.background(t)})},{zOrder:()=> 'top',renderer:()=>({draw:t=>this.objects(t)})}];}
  private x(i:number):number|null{return this.chart?.timeScale().logicalToCoordinate(i as Logical)??null;}
  private y(p:number|null):number|null{return p==null?null:this.series?.priceToCoordinate(p)??null;}
  autoscaleInfo(start:number,end:number){
    const values=this.settings.lines?this.overlay.lines.filter(l=>l.x2>=start&&l.x1<=end).flatMap(l=>[l.y1,l.y2]).filter((v):v is number=>v!=null):[];
    return values.length?{priceRange:{minValue:Math.min(...values),maxValue:Math.max(...values)}}:null;
  }
  private background(target:CanvasRenderingTarget2D):void{
    if(!this.settings.background)return;
    target.useMediaCoordinateSpace(({context:ctx,mediaSize})=>{
      ctx.save();const width=Math.abs((this.x(1)??1)-(this.x(0)??0));
      for(const p of this.overlay.points){if(p.state==='neutral')continue;const x=this.x(p.index);if(x==null||x+width<0||x-width>mediaSize.width)continue;
        const n=p.state==='short'?0:1;ctx.globalAlpha=this.settings.backgroundOpacity[n]/100;ctx.fillStyle=this.settings.backgroundColors[n];ctx.fillRect(x-width/2,0,width+.5,mediaSize.height);
      }ctx.restore();
    });
  }
  private objects(target:CanvasRenderingTarget2D):void{
    this.hits=[];
    target.useMediaCoordinateSpace(({context:ctx,mediaSize})=>{
      const s=this.settings;ctx.save();ctx.lineWidth=1;
      if(s.lines)for(const l of this.overlay.lines){
        const x1=this.x(l.x1),x2=this.x(l.x2),y1=this.y(l.y1),y2=this.y(l.y2);
        if(x1==null||x2==null||y1==null||y2==null||Math.max(x1,x2)<0||Math.min(x1,x2)>mediaSize.width)continue;
        ctx.strokeStyle=l.kind==='breakout'?(l.direction==='long'?s.bull:s.bear):l.kind==='stop'?'#f60707':'#148d9a';
        ctx.lineWidth=l.kind==='breakout'||l.kind==='connector'?2:1;
        const style=l.kind==='breakout'?s.lineStyle:'Dashed';ctx.setLineDash(style==='Solid'?[]:style==='Dotted'?[2,4]:[7,6]);
        ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();
      }
      ctx.setLineDash([]);
      if(s.paneLabels)for(const l of this.overlay.labels){
        const x=this.x(l.x),y=this.y(l.y);if(x==null||y==null||x < -100||x>mediaSize.width+100)continue;
        ctx.textAlign='center';ctx.textBaseline='middle';
        if(l.kind==='structure'){
          const long=l.direction==='long',offset=long?-22:22;ctx.font='9px Arial';ctx.fillStyle='#ffffff';ctx.fillText(l.text??'',x,y+offset);
          ctx.fillStyle=l.sign==='green'?'#4ecf87':l.sign==='red'?'#f23862':'#f5d56e';ctx.beginPath();ctx.arc(x,y+offset+(long?11:-11),4,0,Math.PI*2);ctx.fill();
        }else if(l.kind==='entry'){
          const long=l.direction==='long',dir=long?1:-1,tip=y+dir*10,base=tip+dir*7;
          ctx.fillStyle=long?'#00e676':'#f60707';ctx.beginPath();ctx.moveTo(x,tip);ctx.lineTo(x+8,base);ctx.lineTo(x+8,base+dir*11);ctx.lineTo(x-8,base+dir*11);ctx.lineTo(x-8,base);ctx.closePath();ctx.fill();
        }else{
          ctx.font='11px Arial';const width=ctx.measureText('Target').width+20;
          ctx.fillStyle=l.state==='STOP'?'#f607074d':l.state==='TARGET'?'#028545':'#148d9a';
          ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+7,y-11);ctx.lineTo(x+width,y-11);ctx.lineTo(x+width,y+11);ctx.lineTo(x+7,y+11);ctx.closePath();ctx.fill();ctx.fillStyle='#fff';ctx.fillText('Target',x+width/2+3,y);
          if(l.stop!=null)this.hits.push({x,y,width,text:'Stoploss Hit : '+(Math.floor(l.stop/.05+.5)*.05).toFixed(2)});
        }
      }ctx.restore();
    });
  }
}
