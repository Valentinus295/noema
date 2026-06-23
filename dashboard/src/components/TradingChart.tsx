import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickSeriesPartialOptions,
  type HistogramSeriesPartialOptions,
  type Time,
  type SeriesMarker,
  type CandlestickData,
  type HistogramData,
  type IPriceLine,
  type ISeriesPrimitive,
  type SeriesAttachedParameter,
  type ISeriesPrimitivePaneView,
  type ISeriesPrimitivePaneRenderer,
} from 'lightweight-charts';
import type { ChartData, Timeframe, ChartSymbol, Candle } from '@/types';

// ── Constants ────────────────────────────────────────────────────────

const SYMBOLS: ChartSymbol[] = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'XAUUSD'];
const TIMEFRAMES: Timeframe[] = ['M15', 'H1', 'H4', 'D1'];

const C = {
  bg: '#0a0e14',
  surface: '#14191f',
  border: '#1e2a36',
  text: '#4a5568',
  textBright: '#c9d1d9',
  green: '#00c853',
  red: '#ff1744',
  buy: '#26a69a',
  sell: '#ef5350',
};

// ── Custom Primitives for SMC Overlays ───────────────────────────────

/**
 * PaneView + Renderer for drawing zone rectangles (OB, FVG).
 * Stores series reference for coordinate mapping.
 */
class ZoneRectPaneView implements ISeriesPrimitivePaneView {
  private _time: Time;
  private _top: number;
  private _bottom: number;
  private _fill: string;
  private _border: string;
  private _label: string;
  private _labelColor: string;
  private _series: ISeriesApi<'Candlestick', Time> | null;
  private _chart: IChartApi | null;

  constructor(
    time: Time, top: number, bottom: number,
    fill: string, border: string,
    label = '', labelColor = '#c9d1d9',
    chart: IChartApi | null = null,
    series: ISeriesApi<'Candlestick', Time> | null = null,
  ) {
    this._time = time;
    this._top = top;
    this._bottom = bottom;
    this._fill = fill;
    this._border = border;
    this._label = label;
    this._labelColor = labelColor;
    this._series = series;
    this._chart = chart;
  }

  update(
    time: Time, top: number, bottom: number,
    fill: string, border: string,
    label: string, labelColor: string,
    chart: IChartApi | null,
    series: ISeriesApi<'Candlestick', Time> | null,
  ) {
    this._time = time;
    this._top = top;
    this._bottom = bottom;
    this._fill = fill;
    this._border = border;
    this._label = label;
    this._labelColor = labelColor;
    this._chart = chart;
    this._series = series;
  }

  renderer(): ISeriesPrimitivePaneRenderer | null {
    const self = this;
    const chart = self._chart;
    const series = self._series;
    if (!series || !chart) return null;
    const time = self._time;
    const topP = self._top;
    const botP = self._bottom;
    const fill = self._fill;
    const border = self._border;
    const label = self._label;
    const labelColor = self._labelColor;

    return {
      draw(target) {
        target.useMediaCoordinateSpace((scope) => {
          const ctx = scope.context;
          const x = chart.timeScale().timeToCoordinate(time);
          const y1 = series.priceToCoordinate(topP);
          const y2 = series.priceToCoordinate(botP);

          if (x === null || y1 === null || y2 === null) return;

          const numX = x as number;
          const top = Math.min(y1 as number, y2 as number);
          const bot = Math.max(y1 as number, y2 as number);
          const h = bot - top;

          // Bar spacing estimation
          const barSpacing = 8; // default fallback
          const w = Math.max(barSpacing * 1.8, 14);

          const rx = numX - w / 2;
          ctx.fillStyle = fill;
          ctx.fillRect(rx, top, w, h);

          ctx.strokeStyle = border;
          ctx.lineWidth = 1;
          ctx.strokeRect(rx, top, w, h);

          if (label && h > 12) {
            ctx.font = '9px monospace';
            ctx.fillStyle = labelColor;
            ctx.textAlign = 'center';
            ctx.fillText(label, numX, top + h / 2 + 3);
          }
        });
      },
    };
  }
}

/**
 * ZoneRect primitive for Order Blocks and Fair Value Gaps.
 */
class ZoneRectPrimitive implements ISeriesPrimitive<Time> {
  private _time: Time;
  private _top: number;
  private _bottom: number;
  private _fill: string;
  private _border: string;
  private _label: string;
  private _labelColor: string;
  private _requestUpdate?: () => void;
  private _chart: IChartApi | null = null;
  private _series: ISeriesApi<'Candlestick', Time> | null = null;
  private _paneView: ZoneRectPaneView;

  constructor(
    time: Time, top: number, bottom: number,
    fill: string, border: string,
    label = '', labelColor = '#c9d1d9',
  ) {
    this._time = time;
    this._top = top;
    this._bottom = bottom;
    this._fill = fill;
    this._border = border;
    this._label = label;
    this._labelColor = labelColor;
    this._paneView = new ZoneRectPaneView(time, top, bottom, fill, border, label, labelColor);
  }

  requestUpdate(): void {
    this._requestUpdate?.();
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this._requestUpdate = param.requestUpdate;
    this._chart = param.chart;
    this._series = param.series as ISeriesApi<'Candlestick', Time>;
    this._paneView.update(
      this._time, this._top, this._bottom,
      this._fill, this._border, this._label, this._labelColor,
      this._chart, this._series,
    );
  }

  detached(): void {
    this._requestUpdate = undefined;
    this._chart = null;
    this._series = null;
  }

  paneViews(): readonly ISeriesPrimitivePaneView[] {
    return [this._paneView];
  }
}

// ── Helpers ───────────────────────────────────────────────────────────

function toTime(iso: string): Time {
  return (new Date(iso).getTime() / 1000) as Time;
}

function candleToLW(c: Candle): CandlestickData<Time> {
  return {
    time: toTime(c.time),
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  };
}

// ── Component ─────────────────────────────────────────────────────────

interface TradingChartProps {
  className?: string;
}

export function TradingChart({ className = '' }: TradingChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const primitivesRef = useRef<ISeriesPrimitive<Time>[]>([]);
  const priceLinesRef = useRef<IPriceLine[]>([]);

  const [symbol, setSymbol] = useState<ChartSymbol>('EURUSD');
  const [timeframe, setTimeframe] = useState<Timeframe>('H1');
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoverInfo, setHoverInfo] = useState<{
    time: string; o: number; h: number; l: number; c: number;
  } | null>(null);

  // ── Initialize Chart ──────────────────────────────────────────────

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: C.bg },
        textColor: C.text,
      },
      grid: {
        vertLines: { color: C.border },
        horzLines: { color: C.border },
      },
      crosshair: {
        mode: 0,
        vertLine: {
          color: C.border, width: 1, style: 2,
          labelBackgroundColor: C.surface,
        },
        horzLine: {
          color: C.border, width: 1, style: 2,
          labelBackgroundColor: C.surface,
        },
      },
      timeScale: {
        borderColor: C.border,
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: C.border,
        scaleMargins: { top: 0.05, bottom: 0.25 },
      },
      leftPriceScale: { borderColor: C.border, visible: false },
      handleScroll: { vertTouchDrag: true, mouseWheel: true },
      handleScale: { axisDoubleClickReset: true, mouseWheel: true },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: C.green,
      downColor: C.red,
      borderUpColor: C.green,
      borderDownColor: C.red,
      wickUpColor: C.green,
      wickDownColor: C.red,
    } as CandlestickSeriesPartialOptions);

    const volumeSeries = chart.addHistogramSeries({
      color: C.text,
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    } as HistogramSeriesPartialOptions);

    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point) { setHoverInfo(null); return; }
      const data = param.seriesData.get(candleSeries);
      if (data && typeof data === 'object' && 'open' in data) {
        const d = data as CandlestickData<Time>;
        setHoverInfo({
          time: new Date((d.time as number) * 1000).toLocaleString(),
          o: d.open, h: d.high, l: d.low, c: d.close,
        });
      }
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const { width, height } = e.contentRect;
        if (width > 0 && height > 0) chart.applyOptions({ width, height });
      }
    });
    ro.observe(chartContainerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // ── Fetch Chart Data ──────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    async function fetchData() {
      setLoading(true); setError(null);
      try {
        const res = await fetch(`/api/chart/${symbol}?timeframe=${timeframe}&bars=200`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: ChartData = await res.json();
        if (!cancelled) setChartData(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchData();
    return () => { cancelled = true; };
  }, [symbol, timeframe]);

  // ── Render Chart Data ─────────────────────────────────────────────

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!chart || !candleSeries || !volumeSeries || !chartData) return;

    // Candles
    candleSeries.setData(chartData.candles.map(candleToLW));

    // Volume
    const vols: HistogramData<Time>[] = chartData.candles.map((c) => ({
      time: toTime(c.time),
      value: c.volume,
      color: c.close >= c.open ? 'rgba(0,200,83,0.3)' : 'rgba(255,23,68,0.3)',
    }));
    volumeSeries.setData(vols);

    // Clear old overlays
    for (const p of primitivesRef.current) candleSeries.detachPrimitive(p);
    primitivesRef.current = [];

    for (const pl of priceLinesRef.current) candleSeries.removePriceLine(pl);
    priceLinesRef.current = [];

    // ── Order Blocks ──────────────────────────────────────────────
    for (const ob of chartData.orderBlocks) {
      const bullish = ob.direction === 'bullish';
      const p = new ZoneRectPrimitive(
        toTime(ob.time), ob.priceHigh, ob.priceLow,
        bullish ? 'rgba(0,200,83,0.12)' : 'rgba(255,23,68,0.12)',
        bullish ? 'rgba(0,200,83,0.35)' : 'rgba(255,23,68,0.35)',
        'OB',
        bullish ? C.green : C.red,
      );
      candleSeries.attachPrimitive(p);
      primitivesRef.current.push(p);
    }

    // ── Fair Value Gaps ───────────────────────────────────────────
    for (const fvg of chartData.fvgs) {
      const bullish = fvg.direction === 'bullish';
      const p = new ZoneRectPrimitive(
        toTime(fvg.time), fvg.top, fvg.bottom,
        bullish ? 'rgba(38,166,154,0.06)' : 'rgba(239,83,80,0.06)',
        bullish ? 'rgba(38,166,154,0.25)' : 'rgba(239,83,80,0.25)',
        'FVG',
        bullish ? C.buy : C.sell,
      );
      candleSeries.attachPrimitive(p);
      primitivesRef.current.push(p);
    }

    // ── Markers: Sweeps + Structure ───────────────────────────────
    const markers: SeriesMarker<Time>[] = [];

    for (const s of chartData.sweeps) {
      const bullish = s.direction === 'bullish';
      markers.push({
        time: toTime(s.time),
        position: bullish ? 'belowBar' : 'aboveBar',
        color: bullish ? C.buy : C.sell,
        shape: bullish ? 'arrowUp' : 'arrowDown',
        text: 'SWP', size: 2,
      });
    }

    for (const ev of chartData.structureEvents) {
      const bullish = ev.direction === 'bullish';
      const isBOS = ev.kind === 'BOS';
      markers.push({
        time: toTime(ev.time),
        position: bullish ? 'belowBar' : 'aboveBar',
        color: isBOS ? (bullish ? C.buy : C.sell) : '#ffd600',
        shape: isBOS ? (bullish ? 'arrowUp' : 'arrowDown') : 'circle',
        text: ev.kind, size: 2,
      });
    }

    candleSeries.setMarkers(markers);

    // ── Active Setup Lines ────────────────────────────────────────
    if (chartData.activeSetup) {
      const s = chartData.activeSetup;
      const el = candleSeries.createPriceLine({
        price: s.entry, color: '#ffffff', lineWidth: 1,
        lineStyle: 2, axisLabelVisible: true, title: 'ENTRY',
      });
      priceLinesRef.current.push(el);

      const sl = candleSeries.createPriceLine({
        price: s.sl, color: C.red, lineWidth: 1,
        lineStyle: 0, axisLabelVisible: true, title: 'SL',
      });
      priceLinesRef.current.push(sl);

      const tp = candleSeries.createPriceLine({
        price: s.tp, color: C.green, lineWidth: 1,
        lineStyle: 0, axisLabelVisible: true, title: 'TP',
      });
      priceLinesRef.current.push(tp);
    }

    chart.timeScale().fitContent();
  }, [chartData]);

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <div className={`flex flex-col ${className}`}>
      {/* Controls Bar */}
      <div className="flex items-center justify-between px-3 py-2 bg-terminal-surface border-b border-terminal-border flex-wrap gap-y-1">
        <div className="flex items-center gap-2">
          {SYMBOLS.map((s) => (
            <button
              key={s}
              onClick={() => setSymbol(s)}
              className={`px-2 py-1 text-2xs font-mono rounded transition-colors ${
                symbol === s
                  ? 'bg-blue-600 text-white'
                  : 'text-terminal-muted hover:text-terminal-text hover:bg-terminal-border/50'
              }`}
            >
              {s}
            </button>
          ))}
          <div className="w-px h-4 bg-terminal-border mx-1" />
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-2 py-1 text-2xs font-mono rounded transition-colors ${
                timeframe === tf
                  ? 'bg-blue-600 text-white'
                  : 'text-terminal-muted hover:text-terminal-text hover:bg-terminal-border/50'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>

        {/* Hover Info */}
        <div className="hidden sm:flex items-center gap-3 text-2xs font-mono">
          {loading && <span className="text-terminal-muted animate-pulse">Loading...</span>}
          {error && <span className="text-trade-loss" title={error}>Err</span>}
          {hoverInfo && (
            <>
              <span className="text-terminal-muted">{hoverInfo.time}</span>
              <span>O:{hoverInfo.o.toFixed(5)}</span>
              <span>H:{hoverInfo.h.toFixed(5)}</span>
              <span>L:{hoverInfo.l.toFixed(5)}</span>
              <span>C:{hoverInfo.c.toFixed(5)}</span>
            </>
          )}
        </div>

        {/* Legend */}
        <div className="hidden lg:flex items-center gap-3 text-2xs font-mono text-terminal-muted">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm bg-[#00c853]/30 border border-[#00c853]/40" /> OB
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm bg-[#26a69a]/10 border border-[#26a69a]/30" /> FVG
          </span>
          <span className="flex items-center gap-1"><span className="text-trade-buy">▲SWP</span> Sweep</span>
          <span className="flex items-center gap-1"><span className="text-trade-buy">▲BOS</span> BOS/CHoCH</span>
        </div>
      </div>

      {/* Chart */}
      <div className="relative flex-1 min-h-0">
        {loading && !chartData && (
          <div className="absolute inset-0 flex items-center justify-center bg-terminal-bg/80 z-10">
            <div className="flex items-center gap-3 text-terminal-muted font-mono text-sm">
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Loading {symbol} {timeframe}...
            </div>
          </div>
        )}
        {error && !chartData && (
          <div className="absolute inset-0 flex items-center justify-center bg-terminal-bg/80 z-10">
            <div className="text-center">
              <p className="text-trade-loss font-mono text-sm mb-2">Chart Error</p>
              <p className="text-terminal-muted text-xs">{error}</p>
            </div>
          </div>
        )}
        <div ref={chartContainerRef} className="w-full h-full" style={{ minHeight: '400px' }} />
      </div>
    </div>
  );
}
