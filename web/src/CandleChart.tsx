import {
  CandlestickSeries, ColorType, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Candle } from "./api";

export type ChartLine = { price: number; color: string; title: string; dashed?: boolean };
export type ChartMarker = { timeMs: number; side: 1 | -1; text: string };

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
};

/** Candlestick chart that keeps its view when older bars are prepended, so panning left keeps loading history. */
export function CandleChart({ candles, lines = [], markers = [], height = 420, focusTimeMs, onNeedOlder }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLines = useRef<IPriceLine[]>([]);
  const firstT = useRef<number | null>(null);
  const needOlder = useRef(onNeedOlder);
  needOlder.current = onNeedOlder;

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--muted") || "#9aa3b2", fontFamily: "JetBrains Mono, Consolas, monospace" },
      grid: { vertLines: { color: "rgba(128,128,128,0.08)" }, horzLines: { color: "rgba(128,128,128,0.08)" } },
      rightPriceScale: { borderColor: "rgba(128,128,128,0.25)" },
      timeScale: { borderColor: "rgba(128,128,128,0.25)", timeVisible: true, secondsVisible: false, rightOffset: 4 },
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
    chartRef.current = chart;
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series, []);
    return () => {
      chart.remove();
      chartRef.current = seriesRef.current = markersRef.current = null;
      priceLines.current = [];
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
    if (prevFirst === null) {
      const n = candles.length;
      const idx = focusTimeMs ? candles.findIndex((c) => c.t >= focusTimeMs) : -1;
      if (idx >= 0) scale.setVisibleLogicalRange({ from: Math.max(-5, idx - 70), to: Math.min(n + 4, idx + 70) });
      else scale.setVisibleLogicalRange({ from: Math.max(0, n - 150), to: n + 4 });
    } else if (candles[0].t < prevFirst && prevRange) {
      const added = candles.findIndex((c) => c.t >= prevFirst);
      if (added > 0) scale.setVisibleLogicalRange({ from: prevRange.from + added, to: prevRange.to + added });
    }
    firstT.current = candles[0].t;
  }, [candles, focusTimeMs]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    for (const l of priceLines.current) series.removePriceLine(l);
    priceLines.current = lines.map((l) =>
      series.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title: l.title }),
    );
  }, [lines]);

  useEffect(() => {
    const plugin = markersRef.current;
    if (!plugin) return;
    plugin.setMarkers(
      [...markers]
        .sort((a, b) => a.timeMs - b.timeMs)
        .map((m) => ({
          time: Math.floor(m.timeMs / 1000) as UTCTimestamp,
          position: m.side === 1 ? ("belowBar" as const) : ("aboveBar" as const),
          color: m.side === 1 ? css("--up") || "#34d399" : css("--down") || "#f4607a",
          shape: m.side === 1 ? ("arrowUp" as const) : ("arrowDown" as const),
          text: m.text,
        })),
    );
  }, [markers, candles]);

  return <div ref={host} style={{ height }} role="img" aria-label="Candlestick chart" />;
}
