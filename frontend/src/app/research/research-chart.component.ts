import { Component, ElementRef, Input, NgZone, OnChanges, OnDestroy, ViewChild, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { CandlestickSeries, HistogramSeries, LineSeries, ColorType, createChart, IChartApi, Time } from 'lightweight-charts';
import { Bar, TrendLine } from './research.types';

@Component({ selector: 'app-research-chart', standalone: true, imports: [CommonModule],
  template: `<div #host class="chart" [style.height.px]="height"></div><p *ngIf="!bars.length">No completed candles stored for this timeframe.</p><div class="legend"><span>● Price</span><span class="ema">― EMA 20</span><span>▥ Volume</span><button type="button" (click)="download()" [disabled]="!bars.length">Download PNG</button></div>`,
  styles: [`:host{display:block;min-width:0}.chart{width:100%}p{font-size:12px;color:#91a4b8}.legend{display:flex;gap:12px;align-items:center;font-size:10px;color:#8fa7ba;padding:6px 0}.ema{color:#e8bd61}button{margin-left:auto;background:transparent;color:#a7c4d5;border:1px solid #2a4152;border-radius:4px;padding:4px 8px;cursor:pointer}`]
})
export class ResearchChartComponent implements OnChanges, OnDestroy {
  @Input() bars: Bar[] = [];
  @Input() lines: TrendLine[] = [];
  @Input() levels: { label: string; value: number; color?: string }[] = [];
  @Input() label = 'Research';
  @Input() height = 230;
  @Input() hourly = false;
  private chart?: IChartApi;
  private zone = inject(NgZone);
  private element?: HTMLElement;
  private lastBars?: Bar[];
  private lastSettings = '';
  @ViewChild('host') set host(ref: ElementRef<HTMLElement> | undefined) { this.element = ref?.nativeElement; this.draw(); }
  ngOnChanges(): void {
    // Angular may recreate level arrays during change detection. Rebuilding a
    // chart for equivalent inputs would cause repeated resize/render work.
    const settings = JSON.stringify([this.lines,this.levels,this.hourly,this.height]);
    if (this.lastBars === this.bars && settings === this.lastSettings) return;
    this.lastBars = this.bars; this.lastSettings = settings;
    if (this.element) this.draw();
  }
  private time(stamp: string): Time { return (this.hourly ? Math.floor(Date.parse(stamp) / 1000) : new Date(Date.parse(stamp) + 19800000).toISOString().slice(0,10)) as Time; }
  private draw(): void {
    this.zone.runOutsideAngular(() => this.render());
  }
  private render(): void {
    this.chart?.remove();
    if (!this.element) return;
    const chart = this.chart = createChart(this.element, { autoSize: true, layout: { background: { type: ColorType.Solid, color: '#0b1621' }, textColor: '#8fa7ba', fontSize: 10 }, grid: { vertLines: { visible: false }, horzLines: { color: '#1b2b38' } }, timeScale: { timeVisible: this.hourly, borderColor: '#263c4c' }, rightPriceScale: { borderColor: '#263c4c', scaleMargins: { top: .1, bottom: .25 } } });
    const candles = chart.addSeries(CandlestickSeries, { upColor: '#35c99a', downColor: '#ed697e', wickUpColor: '#35c99a', wickDownColor: '#ed697e', borderVisible: false });
    candles.setData(this.bars.map(b => ({ ...b, time: this.time(b.timestamp) })));
    const volume = chart.addSeries(HistogramSeries, { priceScaleId: 'volume', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: .84, bottom: 0 } });
    volume.setData(this.bars.map(b => ({ time: this.time(b.timestamp), value: b.volume, color: b.close >= b.open ? '#23715f' : '#773b4b' })));
    const average = chart.addSeries(LineSeries, { color: '#e8bd61', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    let value = this.bars[0]?.close ?? 0;
    average.setData(this.bars.map((b,i) => { value = i ? b.close * (2 / 21) + value * (19 / 21) : value; return { time: this.time(b.timestamp), value }; }).slice(19));
    for (const line of this.lines ?? []) { const series = chart.addSeries(LineSeries, { color: line.side === 'support' ? '#46d1a0' : '#ed697e', lineWidth: 2, priceLineVisible: false, lastValueVisible: false }); series.setData(line.points.map(p => ({ time: this.time(p.timestamp), value: p.value }))); }
    for (const level of this.levels) candles.createPriceLine({ price: level.value, title: level.label, color: level.color ?? '#6cb5e4', lineWidth: 1, lineStyle: 2 });
    chart.timeScale().fitContent();
  }
  download(): void { const canvas = this.chart?.takeScreenshot(); if (!canvas) return; const link = document.createElement('a'); link.download = this.label.replace(/[^a-z0-9_-]/gi, '-') + '.png'; link.href = canvas.toDataURL('image/png'); link.click(); }
  ngOnDestroy(): void { this.chart?.remove(); }
}
