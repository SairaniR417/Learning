import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, EventEmitter, HostListener, Input, NgZone, OnChanges, OnDestroy, Output, ViewChild, inject } from '@angular/core';
import { Subscription, interval } from 'rxjs';
import { CandlestickSeries, LineSeries, LineType, LineWidth, ColorType, createChart, createSeriesMarkers, IChartApi, IPriceLine, ISeriesApi, Time, UTCTimestamp } from 'lightweight-charts';
import { MarketApiService, OptionAnalysis, OptionStrategyResult } from '../market-api.service';
import { backendUrl } from '../backend-url';
import { GhostRiderPrimitive } from './ghost-rider.primitive';
import { GhostSettings, defaultGhostSettings, ghostFontSize } from './ghost-rider.types';
import { GhostSettingsComponent } from './ghost-settings.component';
import { RsiSettingsComponent } from './rsi-settings.component';
import { RsiPaneComponent } from './rsi-pane.component';
import { RsiSettings,defaultRsiSettings } from './rsi.types';
import { SutradharSettingsComponent } from './sutradhar-settings.component';
import { SutradharPrimitive } from './sutradhar.primitive';
import { SutradharSettings,SutradharInputs,SutradharLevel,defaultSutradharSettings,sutradharLevels,sutradharVisible } from './sutradhar.types';

@Component({
  selector: 'app-option-analysis', standalone: true, imports: [CommonModule, GhostSettingsComponent,RsiSettingsComponent,RsiPaneComponent,SutradharSettingsComponent],
  templateUrl: './option-analysis.component.html', styleUrl: './option-analysis.component.css'
})
export class OptionAnalysisComponent implements OnChanges, AfterViewInit, OnDestroy {
  @Input({ required: true }) underlyingKey = '';
  @Input() expiry = '';
  @Input() strike = 0;
  @Input() side: 'CE' | 'PE' = 'CE';
  @Input() stockMode = false;
  @Input() stockTimeframe = '1d';
  @Input() initialAtrMultiplier = 1.5;
  @Input() stockStrategy = 'ghost_rider';
  @Input() initialRsiPeriod = 14;
  @Input() initialSutradharInputs:SutradharInputs={p1:14,p2:7,p3:5,use_ema:false};
  @ViewChild('sutradharSettingsButton') sutradharSettingsButton?:ElementRef<HTMLButtonElement>;
  sutradharSettings=defaultSutradharSettings();sutradharSettingsOpen=false;
  readonly sutradharLevels=sutradharLevels;
  private sutradharSeries=new Map<SutradharLevel,ISeriesApi<'Line'>>();
  private sutradharPrimitive?:SutradharPrimitive;
  get sutradharSelected():boolean{return this.strategyId==='sutradhar';}
  get darkSelected():boolean{return this.ghostSelected||this.rsiSelected||this.sutradharSelected;}
  get sutradharVisible():boolean{return this.sutradharSelected&&sutradharVisible(this.sutradharSettings,this.interval);}
  get sutradharPoint(){return this.data?.sutradhar?.points.find(p=>Date.parse(p.timestamp)===this.hoveredTimestamp)??this.data?.sutradhar?.points.at(-1);}
  sutradharNumber(value:number|null|undefined):string{return value==null?'n/a':value.toFixed(this.sutradharSettings.precision<0?2:this.sutradharSettings.precision);}
  closeSutradharSettings():void{this.sutradharSettingsOpen=false;this.sutradharSettingsButton?.nativeElement.focus();}
  applySutradharSettings(settings:SutradharSettings):void{
    const changed=JSON.stringify(settings.inputs)!==JSON.stringify(this.sutradharSettings.inputs);
    this.sutradharSettings=settings;this.closeSutradharSettings();
    if(changed){this.request?.unsubscribe();this.loading=false;this.load();}else this.draw(false);
  }
  @ViewChild('rsiSettingsButton') rsiSettingsButton?:ElementRef<HTMLButtonElement>;
  rsiSettings=defaultRsiSettings();rsiSettingsOpen=false;
  get rsiSelected():boolean {return this.strategyId==='rsi_divergence';}
  closeRsiSettings():void {this.rsiSettingsOpen=false;this.rsiSettingsButton?.nativeElement.focus();}
  applyRsiSettings(settings:RsiSettings):void {
    const changed=JSON.stringify(settings.inputs)!==JSON.stringify(this.rsiSettings.inputs);
    this.rsiSettings=settings;this.closeRsiSettings();
    if(changed){this.request?.unsubscribe();this.loading=false;this.load();}
  }
  @Output() back = new EventEmitter<void>();
  @ViewChild('chartHost') chartHost?: ElementRef<HTMLElement>;
  @ViewChild('fullscreenButton') fullscreenButton?: ElementRef<HTMLButtonElement>;
  @ViewChild('settingsButton') settingsButton?: ElementRef<HTMLButtonElement>;
  expanded = false;
  private previousOverflow = '';
  private hasChosenStrategy = false;
  toggleFullscreen(): void {
    this.expanded = !this.expanded;
    if (this.expanded) { this.previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
    else document.body.style.overflow = this.previousOverflow;
    this.fullscreenButton?.nativeElement.focus();
  }
  @HostListener('document:keydown.escape') exitFullscreen(): void { if (!this.settingsOpen && !this.rsiSettingsOpen && !this.sutradharSettingsOpen && this.expanded) this.toggleFullscreen(); }
  private api = inject(MarketApiService);
  private zone = inject(NgZone);
  private hoveredTimestamp?: number;
  private request?: Subscription;
  private polling?: Subscription;
  private chart?: IChartApi;
  @ViewChild(RsiPaneComponent) rsiPane?:RsiPaneComponent;
  get rsiPriceChart():IChartApi|undefined{return this.stockMode?undefined:this.chart;}
  private series?: ISeriesApi<'Candlestick'>;
  private markers?: ReturnType<typeof createSeriesMarkers<Time>>;
  private lines: IPriceLine[] = [];
  private ema9Series?: ISeriesApi<'Line'>;
  private ema21Series?: ISeriesApi<'Line'>;
  private vwapSeries?: ISeriesApi<'Line'>;
  private ghostPrimitive?: GhostRiderPrimitive;
  private previousGhostMode = false;
  ghostSettings = defaultGhostSettings();
  settingsOpen = false;
  closeGhostSettings(): void { this.settingsOpen = false; this.settingsButton?.nativeElement.focus(); }
  ghostFontSize = ghostFontSize;
  get ghostSelected(): boolean { return this.strategyId === 'ghost_rider'; }
  get ghostVisible(): boolean {
    if (!this.ghostSelected) return false;
    if ([60,1440,10080].includes(this.interval)) {
      const range=this.ghostSettings.timeframes[this.interval===10080?'Weeks':this.interval===1440?'Days':'Hours'];
      return range.enabled && range.min<=1 && range.max>=1;
    }
    return this.ghostSettings.minutes && this.interval >= this.ghostSettings.minuteMin && this.interval <= this.ghostSettings.minuteMax;
  }
  get displayedTimeframe(): string { return this.stockMode ? this.stockTimeframe : ({60:'1h',1440:'1d',10080:'1w'} as Record<number,string>)[this.interval] ?? this.interval+'m'; }
  get activeCandles() { return (this.ghostSelected ? this.data?.ghostRider?.candles : this.sutradharSelected ? this.data?.sutradhar?.candles : undefined) ?? this.data?.candles ?? []; }
  get lastCandle() { return this.activeCandles.find(c=>Date.parse(c.timestamp)===this.hoveredTimestamp) ?? this.activeCandles.at(-1); }
  get ghostPoint() { return this.data?.ghostRider?.points.find(p=>Date.parse(p.timestamp)===this.hoveredTimestamp) ?? this.data?.ghostRider?.points.at(-1); }
  ghostNumber(value: number | undefined): string { return value == null ? 'n/a' : value.toFixed(this.ghostSettings.precision < 0 ? 2 : this.ghostSettings.precision); }
  applyGhostSettings(settings: GhostSettings): void {
    const riskChanged = settings.atrMultiplier !== this.ghostSettings.atrMultiplier;
    const offsetChanged = settings.labelOffset !== this.ghostSettings.labelOffset;
    this.ghostSettings = settings; this.closeGhostSettings();
    if (riskChanged) {
      this.request?.unsubscribe(); this.loading = false; this.load();
    } else this.draw(false);
    if (offsetChanged && this.ghostVisible) this.fitChart();
  }
  interval = 5;
  loading = false;
  error = '';
  needsConnection = false;
  data?: OptionAnalysis;
  strategyId = 'ghost_rider';
  readonly loginUrl = backendUrl('/auth/upstox');
  get selectedStrategy(): OptionStrategyResult | undefined { return this.data?.strategies.find(s => s.id === this.strategyId); }
  ngOnChanges(): void {
    if (this.stockMode) {this.ghostSettings={...this.ghostSettings,atrMultiplier:this.initialAtrMultiplier};this.rsiSettings={...this.rsiSettings,inputs:{...this.rsiSettings.inputs,period:this.initialRsiPeriod}};}
    if(this.stockMode)this.sutradharSettings={...this.sutradharSettings,inputs:{...this.initialSutradharInputs}};
    if (this.expanded) this.toggleFullscreen();
    this.hasChosenStrategy = false;
    if(this.stockMode){this.strategyId=this.stockStrategy;this.hasChosenStrategy=true;}
    this.request?.unsubscribe(); this.polling?.unsubscribe();
    this.data = undefined; this.interval = this.stockMode ? ({'1d':1440,'1h':60,'15m':15,'5m':5} as Record<string,number>)[this.stockTimeframe] ?? 1440 : 5; this.clearChart();
    if (!document.hidden) this.load();
    this.polling = interval(60000).subscribe(() => { if (!document.hidden && !this.loading) this.load(); });
  }
  ngAfterViewInit(): void {
    if (!this.chartHost) return;
    this.chart = createChart(this.chartHost.nativeElement, {
      autoSize: true, height: 360, layout: { background: { type: ColorType.Solid, color: '#101a19' }, textColor: '#b8c9c4' },
      grid: { vertLines: { color: '#20302c' }, horzLines: { color: '#20302c' } },
      localization: { timeFormatter: (time: Time) => new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(Number(time) * 1000)) },
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => new Intl.DateTimeFormat('en-IN', this.interval>=1440 ? {timeZone:'Asia/Kolkata',day:'2-digit',month:'short'} : { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(Number(time) * 1000)) }
    });
    this.series = this.chart.addSeries(CandlestickSeries, { upColor: '#55cba5', downColor: '#e78391', borderVisible: false, wickUpColor: '#55cba5', wickDownColor: '#e78391' });
    this.ema9Series = this.chart.addSeries(LineSeries, {visible:false,priceLineVisible:false,crosshairMarkerVisible:false});
    this.ema21Series = this.chart.addSeries(LineSeries, {visible:false,priceLineVisible:false,crosshairMarkerVisible:false});
    this.vwapSeries = this.chart.addSeries(LineSeries, {visible:false,priceLineVisible:false,crosshairMarkerVisible:false});
    this.markers = createSeriesMarkers(this.series, []);
    this.chart.subscribeCrosshairMove(event => this.zone.run(() => { this.hoveredTimestamp = typeof event.time === 'number' ? event.time*1000 : undefined; }));
    this.chart.timeScale().subscribeSizeChange(() => this.fitChart());
    this.draw(true);
  }
  changeInterval(value: string): void {
    this.interval = Number(value); this.request?.unsubscribe(); this.loading = false;
    this.data = undefined; this.clearChart(); this.load();
  }
  changeStockTimeframe(value: string): void {
    this.stockTimeframe=value;
    this.changeInterval(String(({'1d':1440,'1h':60,'15m':15,'5m':5} as Record<string,number>)[value]));
  }
  load(): void {
    if (this.loading) return;
    this.loading = true; this.error = ''; this.needsConnection = false;
    const response = this.stockMode ? (this.stockStrategy==='sutradhar'?this.api.analyzeStockSutradhar(this.underlyingKey,this.stockTimeframe,this.sutradharSettings.inputs):this.stockStrategy==='rsi_divergence'?this.api.analyzeStockRsi(this.underlyingKey,this.stockTimeframe,this.rsiSettings.inputs):this.api.analyzeStockGhost(this.underlyingKey,this.stockTimeframe,this.ghostSettings.atrMultiplier)) : this.api.analyzeOption(this.underlyingKey, this.expiry, this.strike, this.side, this.interval, this.ghostSettings.atrMultiplier,this.rsiSettings.inputs,this.sutradharSelected?this.sutradharSettings.inputs:undefined);
    this.request = response.subscribe({
      next: data => {
        const first = !this.data; this.data = data; this.loading = false;
        if (first && !this.hasChosenStrategy) this.strategyId = data.strategies.find(s => s.id === 'ghost_rider' && s.levels.length)?.id
          ?? data.strategies.find(s => s.markers.length || s.levels.length)?.id ?? data.strategies[0]?.id ?? '';
        this.draw(first);
      },
      error: error => { this.loading = false; this.needsConnection = error.status === 401; this.error = error.error?.detail || `Could not load ${this.stockMode ? 'stock' : 'option'} analysis. Please retry.`; }
    });
  }
  showStrategy(id: string): void {
    this.strategyId=id;this.hasChosenStrategy=true;
    if(this.sutradharSelected&&!this.data?.sutradhar){this.request?.unsubscribe();this.loading=false;this.load();}
    this.drawEvidence();
  }
  label(value: string): string { return value.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' '); }
  private clearChart(): void {
    this.clearSutradhar();
    if (this.ghostPrimitive && this.series) this.series.detachPrimitive(this.ghostPrimitive);
    this.ghostPrimitive = undefined;
    this.ema9Series?.setData([]); this.ema21Series?.setData([]); this.vwapSeries?.setData([]);
    this.series?.setData([]); this.markers?.setMarkers([]);
    if (this.series) for (const line of this.lines) this.series.removePriceLine(line);
    this.lines = [];
  }
  private draw(fit: boolean): void {
    if (!this.series || !this.data) return;
    this.setCandles();
    this.drawEvidence();
    if (fit) this.fitChart();
  }
  private drawEvidence(): void {
    if (!this.series || !this.data) return;
    for (const line of this.lines) this.series.removePriceLine(line);
    this.lines = [];
    this.setCandles();
    this.drawGhost();
    this.drawSutradhar();
    if(this.rsiSelected){this.markers?.setMarkers([]);return;}
    if(this.sutradharSelected){this.markers?.setMarkers([]);return;}
    if (this.ghostSelected) { this.markers?.setMarkers([]); return; }
    const strategy = this.selectedStrategy;
    const times = new Set(this.data.candles.map(c => Date.parse(c.timestamp) / 1000));
    this.markers?.setMarkers((strategy?.markers ?? []).filter(m => times.has(Date.parse(m.timestamp) / 1000)).map(m => ({
      time: (Date.parse(m.timestamp) / 1000) as UTCTimestamp,
      position: m.bias === 'bearish' ? 'aboveBar' as const : 'belowBar' as const,
      color: m.bias === 'bearish' ? '#ef9ca6' : '#69d9ad', shape: 'circle' as const, text: m.label
    })).sort((a, b) => Number(a.time) - Number(b.time)));
    this.lines = (strategy?.levels ?? []).map(level => this.series!.createPriceLine({ price: level.price, color: /stop|invalid/i.test(level.label) ? '#ef9ca6' : '#69d9ad', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: level.label }));
  }
  private setCandles(): void {
    if (!this.series || !this.data) return;
    const colors = new Map(this.ghostVisible && this.ghostSettings.barColor ? this.data.ghostRider?.points.map(p=>[p.timestamp,p.barColor]) : []);
    this.series.setData(this.activeCandles.map(c => {
      const color = colors.get(c.timestamp);
      return {time:(Date.parse(c.timestamp)/1000) as UTCTimestamp,open:c.open,high:c.high,low:c.low,close:c.close,
        ...(color ? {color}: {})};
    }));
  }
  private drawGhost(): void {
    if (!this.chart || !this.series || !this.data) return;
    const ghost = this.data.ghostRider, s = this.ghostSettings, visible = this.ghostVisible && !!ghost;
    if (this.previousGhostMode !== this.darkSelected) {
      this.previousGhostMode = this.darkSelected;
      this.chart.applyOptions({layout:{background:{type:ColorType.Solid,color:this.darkSelected?'#000000':'#101a19'},textColor:this.darkSelected?'#d1d4dc':'#b8c9c4'},
        grid:{vertLines:{visible:!this.darkSelected},horzLines:{visible:!this.darkSelected}},
        timeScale:{rightOffset:this.ghostSelected?s.labelOffset+80:3}});
      this.series.applyOptions({upColor:this.darkSelected?'#089981':'#55cba5',downColor:this.darkSelected?'#f23645':'#e78391',
        wickUpColor:this.darkSelected?'#089981':'#55cba5',wickDownColor:this.darkSelected?'#f23645':'#e78391'});
    }
    const precision = !this.ghostSelected || s.precision < 0 ? 2 : s.precision;
    this.series.applyOptions({lastValueVisible:!this.ghostSelected||s.scaleLabels,priceFormat:{type:'price',precision,minMove:10**(-precision)}});
    this.ema9Series?.applyOptions({visible:visible&&s.ema9,color:s.ema9Color+'cc',lineWidth:s.ema9Width as LineWidth,lastValueVisible:s.scaleLabels,priceFormat:{type:'price',precision,minMove:10**(-precision)}});
    this.ema21Series?.applyOptions({visible:visible&&s.ema21,color:s.ema21Color+'cc',lineWidth:s.ema21Width as LineWidth,lastValueVisible:s.scaleLabels,priceFormat:{type:'price',precision,minMove:10**(-precision)}});
    this.vwapSeries?.applyOptions({visible:visible&&s.vwap,color:ghost?.points.at(-1)?.vwapColor==='#4caf50'?s.vwapBullColor:s.vwapBearColor,lineWidth:s.vwapWidth as LineWidth,lastValueVisible:s.scaleLabels,priceFormat:{type:'price',precision,minMove:10**(-precision)}});
    if (visible && ghost) {
      this.ema9Series?.setData(ghost.points.map(p=>({time:(Date.parse(p.timestamp)/1000) as UTCTimestamp,value:p.ema9})));
      this.ema21Series?.setData(ghost.points.map(p=>({time:(Date.parse(p.timestamp)/1000) as UTCTimestamp,value:p.ema21})));
      this.vwapSeries?.setData(ghost.points.filter(p=>p.vwap!=null).map(p=>({time:(Date.parse(p.timestamp)/1000) as UTCTimestamp,value:p.vwap!,color:p.vwapColor==='#4caf50'?s.vwapBullColor:s.vwapBearColor})));
      if (!this.ghostPrimitive) { this.ghostPrimitive=new GhostRiderPrimitive(ghost,this.activeCandles,s);this.series.attachPrimitive(this.ghostPrimitive); }
      else this.ghostPrimitive.update(ghost,this.activeCandles,s);
    } else if (this.ghostPrimitive) { this.series.detachPrimitive(this.ghostPrimitive);this.ghostPrimitive=undefined; }
  }
  private fitChart(): void {
    if (!this.chart || !this.activeCandles.length) return;
    if (this.ghostSelected) this.chart.timeScale().setVisibleLogicalRange({from:0,to:this.activeCandles.length-1+this.ghostSettings.labelOffset+80});
    else if(this.sutradharSelected)this.chart.timeScale().setVisibleLogicalRange({from:0,to:this.activeCandles.length+18});
    else this.chart.timeScale().fitContent();
  }
  private clearSutradhar():void{
    if(this.sutradharPrimitive&&this.series)this.series.detachPrimitive(this.sutradharPrimitive);
    this.sutradharPrimitive=undefined;
    if(this.chart)for(const series of this.sutradharSeries.values())this.chart.removeSeries(series);
    this.sutradharSeries.clear();
  }
  private drawSutradhar():void{
    if(!this.chart||!this.series)return;
    const data=this.data?.sutradhar,s=this.sutradharSettings;
    if(!this.sutradharVisible||!data){this.clearSutradhar();return;}
    const precision=s.precision<0?2:s.precision;
    this.series.applyOptions({lastValueVisible:s.scaleLabels,priceFormat:{type:'price',precision,minMove:10**(-precision)}});
    for(const name of sutradharLevels){
      let series=this.sutradharSeries.get(name);
      if(!series){series=this.chart.addSeries(LineSeries,{priceLineVisible:false,crosshairMarkerVisible:false});this.sutradharSeries.set(name,series);}
      const plot=s.plots[name];
      series.applyOptions({visible:plot.enabled,color:s.colors[name]+(name==='Mid'?'66':''),lineWidth:plot.width as LineWidth,
        lineVisible:plot.style!=='circles',pointMarkersVisible:plot.style==='circles',pointMarkersRadius:1.5*plot.width,
        lineType:plot.style==='step'?LineType.WithSteps:LineType.Simple,lastValueVisible:s.scaleLabels,
        priceFormat:{type:'price',precision,minMove:10**(-precision)}});
      series.setData(data.points.map(p=>({time:Date.parse(p.timestamp)/1000 as UTCTimestamp,...(p[name]==null?{}:{value:p[name]!})})));
    }
    if(!this.sutradharPrimitive){this.sutradharPrimitive=new SutradharPrimitive(data,s);this.series.attachPrimitive(this.sutradharPrimitive);}
    else this.sutradharPrimitive.update(data,s);
  }
  @HostListener('document:visibilitychange') visibilityChanged(): void {
    if (document.hidden) { this.request?.unsubscribe(); this.loading = false; }
    else this.load();
  }
  ngOnDestroy(): void { this.request?.unsubscribe(); this.polling?.unsubscribe(); this.rsiPane?.releaseSharedChart(); this.chart?.remove(); if (this.expanded) document.body.style.overflow = this.previousOverflow; }
}
