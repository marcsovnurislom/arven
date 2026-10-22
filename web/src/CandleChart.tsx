import {
  CandlestickSeries, ColorType, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import type { Candle } from "./api";

export type ChartLine = { price: number; color: string; title: string; dashed?: boolean };
export type ChartMarker = { timeMs: number; side: 1 | -1; text: string; shape?: "circle" | "square"; color?: string; position?: "aboveBar" | "belowBar" };
/** A free line drawn through time/price points (trendlines, range edges). */
export type ChartOverlay = { points: { timeMs: number; price: number }[]; color: string; width?: number; dashed?: boolean };

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const LOAD_MORE_WHEN_BARS_LEFT = 25;

type Props = {
  candles: Candle[];
  lines?: ChartLine[];
  markers?: ChartMarker[];
  height?: number;
  /** Centre the first view on this time (e.g. a signal); default is the latest ~150 bars. */
  focusTimeMs?: number;
  /** Called when the user pans close to the oldest loaded bar - the parent should prepend older candles. */
  onNeedOlder?: () => void;
  overlays?: ChartOverlay[];
  /** Fit the first view to this time span (e.g. a whole trade); wins over ``focusTimeMs``. */
  range?: { fromMs: number; toMs: number };
  /** Change this number to re-apply ``range``/``focusTimeMs`` (a "fit" button). */
  fitKey?: number;
  /** Fill the parent's height instead of ``height`` (full-screen frames). */
  fill?: boolean;
};

type Hover = { t: number; o: number; h: number; l: number; c: number };
const fmtPx = (x: number) => x.toLocaleString("en-US", { maximumFractionDigits: 2 });

/** Candlestick chart that keeps its view when older bars are prepended, so panning left keeps loading history. */
export function CandleChart({ candles, lines = [], markers = [], height = 420, focusTimeMs, onNeedOlder, overlays = [], range, fitKey = 0, fill = false }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLines = useRef<IPriceLine[]>([]);
  const firstT = useRef<number | null>(null);
  const overlaySeries = useRef<ISeriesApi<"Line">[]>([]);
  const needOlder = useRef(onNeedOlder);
  needOlder.current = onNeedOlder;
  const [hover, setHover] = useState<Hover | null>(null);
  const lastFit = useRef(fitKey);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--muted") || "#9aa3b2", fontFamily: "JetBrains Mono, Consolas, monospace" },
      grid: { vertLines: { color: "rgba(128,128,128,0.08)" }, horzLines: { color: "rgba(128,128,128,0.08)" } },
      rightPriceScale: { borderColor: "rgba(128,128,128,0.25)" },
      // a fixed set of candles (a trade's window, no `onNeedOlder`) keeps its edges: zooming or panning out never shows empty space
      timeScale: { borderColor: "rgba(128,128,128,0.25)", timeVisible: true, secondsVisible: false, rightOffset: 4, fixLeftEdge: !needOlder.current, fixRightEdge: !needOlder.current },
      crosshair: { mode: 1 },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: css("--up") || "#34d399", downColor: css("--down") || "#f4607a",
      borderUpColor: css("--up") || "#34d399", borderDownColor: css("--down") || "#f4607a",
      wickUpColor: css("--up") || "#34d399", wickDownColor: css("--down") || "#f4607a",
    });
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range && range.from < LOAD_MORE_WHEN_BARS_LEFT) needOlder.current?.();
    });
    chart.subscribeCrosshairMove((param) => {
      const d = param.time !== undefined ? (param.seriesData.get(series) as { open?: number; high?: number; low?: number; close?: number } | undefined) : undefined;
      setHover(d && d.open !== undefined ? { t: (param.time as number) * 1000, o: d.open, h: d.high ?? d.open, l: d.low ?? d.open, c: d.close ?? d.open } : null);
    });
    chartRef.current = chart;
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series, []);
    return () => {
      chart.remove();
      chartRef.current = seriesRef.current = markersRef.current = null;
      priceLines.current = [];
      overlaySeries.current = [];
      firstT.current = null;
    };
  }, [height]);

  useEffect(() => {
    const chart = chartRef.current, series = seriesRef.current;
    if (!chart || !series || candles.length === 0) return;
    const scale = chart.timeScale();
    const prevRange = scale.getVisibleLogicalRange();
    const prevFirst = firstT.current;
    series.setData(candles.map((c) => ({ time: Math.floor(c.t / 1000) as UTCTimestamp, open: c.o, high: c.h, low: c.l, close: c.c })));
    const refit = lastFit.current !== fitKey;
    lastFit.current = fitKey;
    if (prevFirst === null || refit) {
      const n = candles.length;
      const idx = focusTimeMs ? candles.findIndex((c) => c.t >= focusTimeMs) : -1;
      if (range) {
        const a = Math.max(0, candles.findIndex((c) => c.t >= range.fromMs));
        const bRaw = candles.findIndex((c) => c.t > range.toMs);
        const b = bRaw < 0 ? n - 1 : bRaw;
        const pad = Math.max(3, Math.round((b - a) * 0.08));
        scale.setVisibleLogicalRange({ from: a - pad, to: b + pad });
      } else if (idx >= 0) scale.setVisibleLogicalRange({ from: Math.max(-5, idx - 70), to: Math.min(n + 4, idx + 70) });
      else scale.setVisibleLogicalRange({ from: Math.max(0, n - 150), to: n + 4 });
    } else if (candles[0].t < prevFirst && prevRange) {
      const added = candles.findIndex((c) => c.t >= prevFirst);
      if (added > 0) scale.setVisibleLogicalRange({ from: prevRange.from + added, to: prevRange.to + added });
    }
    firstT.current = candles[0].t;
  }, [candles, focusTimeMs, range, fitKey, height]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    for (const l of priceLines.current) series.removePriceLine(l);
    priceLines.current = lines.map((l) =>
      series.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title: l.title }),
    );
  }, [lines, height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    for (const ls of overlaySeries.current) chart.removeSeries(ls);
    overlaySeries.current = overlays.map((o) => {
      const ls = chart.addSeries(LineSeries, { color: o.color, lineWidth: (o.width ?? 2) as 1 | 2 | 3 | 4, lineStyle: o.dashed ? LineStyle.Dashed : LineStyle.Solid, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      const pts = [...o.points].sort((a, b) => a.timeMs - b.timeMs).filter((p, i, arr) => i === 0 || p.timeMs !== arr[i - 1].timeMs);
      ls.setData(pts.map((p) => ({ time: Math.floor(p.timeMs / 1000) as UTCTimestamp, value: p.price })));
      return ls;
    });
  }, [overlays, height]);

  useEffect(() => {
    const plugin = markersRef.current;
    if (!plugin) return;
    plugin.setMarkers(
      [...markers]
        .sort((a, b) => a.timeMs - b.timeMs)
        .map((m) => ({
          time: Math.floor(m.timeMs / 1000) as UTCTimestamp,
          position: m.position ?? (m.side === 1 ? ("belowBar" as const) : ("aboveBar" as const)),
          color: m.color ?? (m.side === 1 ? css("--up") || "#34d399" : css("--down") || "#f4607a"),
          shape: m.shape ?? (m.side === 1 ? ("arrowUp" as const) : ("arrowDown" as const)),
          text: m.text,
        })),
    );
  }, [markers, candles, height]);

  return (
    <div className="relative" style={{ height: fill ? "100%" : height }}>
      <div ref={host} style={{ height: "100%" }} role="img" aria-label="Candlestick chart" />
      {hover && (
        <div className="chart-legend num" aria-hidden="true">
          <span className="faint">{new Date(hover.t).toISOString().slice(0, 16).replace("T", " ")}</span>
          <span>O <b>{fmtPx(hover.o)}</b></span><span>H <b>{fmtPx(hover.h)}</b></span><span>L <b>{fmtPx(hover.l)}</b></span>
          <span>C <b className={hover.c >= hover.o ? "up" : "down"}>{fmtPx(hover.c)}</b></span>
        </div>
      )}
    </div>
  );
}
