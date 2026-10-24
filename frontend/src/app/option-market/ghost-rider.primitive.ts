import { AutoscaleInfo, IChartApi, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, Logical, SeriesAttachedParameter, Time, UTCTimestamp } from 'lightweight-charts';
import { CanvasRenderingTarget2D } from 'fancy-canvas';
import { HistoricalCandle } from '../market-api.service';
import { GhostRiderOverlay, GhostSettings, ghostFontSize } from './ghost-rider.types';

/** Chart-coordinate drawings for Pine's fill, plotshape and line/label objects. */
export class GhostRiderPrimitive implements ISeriesPrimitive<Time> {
  private chart?: IChartApi;
  private series?: ISeriesApi<any>;
  private requestUpdate?: () => void;
  private bottom: IPrimitivePaneView = { zOrder: () => 'bottom', renderer: () => ({ draw: target => this.drawRibbon(target) }) };
  private top: IPrimitivePaneView = { zOrder: () => 'top', renderer: () => ({ draw: target => this.drawObjects(target) }) };
  constructor(private overlay: GhostRiderOverlay, private candles: HistoricalCandle[], private settings: GhostSettings) {}
  attached(params: SeriesAttachedParameter<Time>): void { this.chart = params.chart; this.series = params.series; this.requestUpdate = params.requestUpdate; }
  detached(): void { this.chart = undefined; this.series = undefined; this.requestUpdate = undefined; }
  paneViews(): readonly IPrimitivePaneView[] { return [this.bottom, this.top]; }
  update(overlay: GhostRiderOverlay, candles: HistoricalCandle[], settings: GhostSettings): void {
    this.overlay = overlay; this.candles = candles; this.settings = settings; this.requestUpdate?.();
  }
  autoscaleInfo(start: Logical, end: Logical): AutoscaleInfo | null {
    const signal = this.overlay.setup;
    if (!signal || end < signal.index || !this.settings.lines) return null;
    const levels = this.overlay.levels.map(l => l.price);
    return levels.length ? { priceRange: { minValue: Math.min(...levels), maxValue: Math.max(...levels) } } : null;
  }
  private x(timestamp: string): number | null { return this.chart?.timeScale().timeToCoordinate((Date.parse(timestamp) / 1000) as UTCTimestamp) ?? null; }
  private y(price: number): number | null { return this.series?.priceToCoordinate(price) ?? null; }
  private drawRibbon(target: CanvasRenderingTarget2D): void {
    if (!this.settings.ema9 || !this.settings.ema21 || !this.settings.ribbonOpacity) return;
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      const points = this.overlay.points;
      ctx.save(); ctx.globalAlpha = this.settings.ribbonOpacity / 100;
      for (let i = 1; i < points.length; i++) {
        const a = points[i-1], b = points[i];
        const x1 = this.x(a.timestamp), x2 = this.x(b.timestamp);
        const a9 = this.y(a.ema9), a21 = this.y(a.ema21), b9 = this.y(b.ema9), b21 = this.y(b.ema21);
        if (x1 == null || x2 == null || a9 == null || a21 == null || b9 == null || b21 == null) continue;
        const fill = (coords: number[][], color: string) => {
          ctx.fillStyle = color; ctx.beginPath(); coords.forEach(([x,y], n) => n ? ctx.lineTo(x,y) : ctx.moveTo(x,y)); ctx.closePath(); ctx.fill();
        };
        if ((a.ema9-a.ema21) * (b.ema9-b.ema21) < 0) {
          const fraction = (a.ema9-a.ema21) / ((a.ema9-a.ema21) - (b.ema9-b.ema21));
          const x = x1 + (x2-x1)*fraction, y = a9 + (b9-a9)*fraction;
          fill([[x1,a9],[x,y],[x1,a21]], a.ribbonColor);
          fill([[x,y],[x2,b9],[x2,b21]], b.ribbonColor);
        } else fill([[x1,a9],[x2,b9],[x2,b21],[x1,a21]], b.ribbonColor);
      }
      ctx.restore();
    });
  }
  private drawObjects(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      ctx.save();
      const prices = new Map(this.candles.map(c => [c.timestamp, c]));
      for (const signal of this.overlay.signals) {
        const buy = signal.side === 'BUY';
        if (!(buy ? this.settings.buyShapes : this.settings.sellShapes)) continue;
        const candle = prices.get(signal.timestamp), x = this.x(signal.timestamp);
        if (!candle || x == null || x < -50 || x > mediaSize.width + 50) continue;
        const y = this.y(buy ? candle.low : candle.high);
        if (y == null) continue;
        const height = 24, width = 42, top = buy ? y+13 : y-13-height;
        ctx.fillStyle = buy ? '#4caf50' : '#f23645';
        ctx.beginPath(); ctx.roundRect(x-width/2, top, width, height, 2); ctx.fill();
        ctx.beginPath(); ctx.moveTo(x-6, buy ? top : top+height); ctx.lineTo(x, buy ? top-7 : top+height+7); ctx.lineTo(x+6, buy ? top : top+height); ctx.closePath(); ctx.fill();
        ctx.fillStyle='#ffffff'; ctx.font='10px Arial'; ctx.textAlign='center'; ctx.textBaseline='middle'; ctx.fillText(signal.label, x, top+height/2);
      }
      const setup = this.overlay.setup;
      if (setup) {
        const from = this.x(setup.signalAt);
        const last = this.candles.at(-1);
        const lastIndex = last ? this.chart?.timeScale().timeToIndex((Date.parse(last.timestamp)/1000) as UTCTimestamp) : null;
        const labelX = lastIndex == null ? null : this.chart?.timeScale().logicalToCoordinate((lastIndex + this.settings.labelOffset) as Logical);
        for (const level of this.overlay.levels) {
          const lineColor = level.label === 'ENTRY' ? '#2962ff' : level.color;
          const y = this.y(level.price);
          if (y == null || from == null) continue;
          if (this.settings.lines) {
            ctx.strokeStyle=lineColor; ctx.lineWidth=level.width; ctx.setLineDash(level.dashed ? [6,6] : []);
            ctx.beginPath(); ctx.moveTo(Math.max(0,from),y); ctx.lineTo(mediaSize.width,y); ctx.stroke(); ctx.setLineDash([]);
          }
          if (!this.settings.paneLabels || level.label === 'SL' || labelX == null) continue;
          // Pine's explicit str.tostring(price, "#.##") is independent of plot precision.
          const value = String(Number(level.price.toFixed(2)));
          const text = `${level.label}: ${value}${level.icon ? ' '+level.icon : ''}`;
          const fontSize = ghostFontSize(this.settings.tradeSize, true);
          ctx.font=`${fontSize}px Arial`; ctx.textAlign='left'; ctx.textBaseline='middle';
          const width=ctx.measureText(text).width+14, height=fontSize+12;
          ctx.fillStyle=level.labelColor ?? lineColor;
          ctx.beginPath(); ctx.roundRect(labelX,y-height/2,width,height,2); ctx.fill();
          ctx.beginPath(); ctx.moveTo(labelX,y-5); ctx.lineTo(labelX-6,y); ctx.lineTo(labelX,y+5); ctx.closePath(); ctx.fill();
          ctx.fillStyle='#ffffff'; ctx.fillText(text,labelX+7,y);
        }
      }
      ctx.restore();
    });
  }
}
