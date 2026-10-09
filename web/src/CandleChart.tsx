import { CandlestickSeries, ColorType, LineStyle, createChart, createSeriesMarkers, type IChartApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Candle } from "./api";

export type ChartLine = { price: number; color: string; title: string; dashed?: boolean };
export type ChartMarker = { timeMs: number; side: 1 | -1; text: string };

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function CandleChart({ candles, lines = [], markers = [], height = 420 }: { candles: Candle[]; lines?: ChartLine[]; markers?: ChartMarker[]; height?: number }) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--muted") || "#9aa3b2", fontFamily: "JetBrains Mono, Consolas, monospace" },
      grid: { vertLines: { color: "rgba(128,128,128,0.08)" }, horzLines: { color: "rgba(128,128,128,0.08)" } },
      rightPriceScale: { borderColor: "rgba(128,128,128,0.25)" },
      timeScale: { borderColor: "rgba(128,128,128,0.25)", timeVisible: true, secondsVisible: false },
      crosshair: { mode: 1 },
    });
    chartRef.current = chart;
    const series = chart.addSeries(CandlestickSeries, {
      upColor: css("--up") || "#34d399", downColor: css("--down") || "#f4607a",
      borderUpColor: css("--up") || "#34d399", borderDownColor: css("--down") || "#f4607a",
      wickUpColor: css("--up") || "#34d399", wickDownColor: css("--down") || "#f4607a",
    });
    series.setData(candles.map((c) => ({ time: Math.floor(c.t / 1000) as UTCTimestamp, open: c.o, high: c.h, low: c.l, close: c.c })));
    for (const l of lines) {
      series.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title: l.title });
    }
    if (markers.length) {
      const firstT = candles.length ? candles[0].t : 0;
      createSeriesMarkers(
        series,
        markers
          .filter((m) => m.timeMs >= firstT)
          .sort((a, b) => a.timeMs - b.timeMs)
          .map((m) => ({
            time: Math.floor(m.timeMs / 1000) as UTCTimestamp,
            position: m.side === 1 ? ("belowBar" as const) : ("aboveBar" as const),
            color: m.side === 1 ? css("--up") || "#34d399" : css("--down") || "#f4607a",
            shape: m.side === 1 ? ("arrowUp" as const) : ("arrowDown" as const),
            text: m.text,
          })),
      );
    }
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, lines, markers, height]);

  return <div ref={host} style={{ height }} role="img" aria-label="Candlestick chart" />;
}
