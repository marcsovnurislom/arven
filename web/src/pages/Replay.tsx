import {
  CandlestickSeries, ColorType, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type TMItem, type TMScenario } from "../api";
import { useI18n, type Key } from "../i18n";
import { useLoad, useThemeName } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, Skeleton, cssVar, fmtTime } from "../ui";

const SPEEDS = [1, 4, 16, 64]; // x1 = 4 candles of 15 minutes per second (an hour a second)
const BASE_CPS = 4;
const EVENT_HOLD_MS = 700; // a short pause on every new event while playing, so it can be read
const css = (n: string, fb: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || fb;
const px = (x: number | undefined) => (x === undefined ? "—" : x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const usd = (x: number) => `$${x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Index of the last item with t <= time (items sorted by t), -1 if none. */
function lastAtOrBefore(items: TMItem[], time: number): number {
  let lo = 0, hi = items.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (items[mid].t <= time) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

function useText() {
  const { t } = useI18n();
  return (i: TMItem): string => {
    const side = i.side === 1 ? t("tmLong") : t("tmShort");
    const sub = (k: Key, v: Record<string, string>) => Object.entries(v).reduce((s, [a, b]) => s.replace(`{${a}}`, b), t(k));
    switch (i.kind) {
      case "setup": return sub("tmSetup", { dir: i.side === 1 ? t("tmUp") : t("tmDown"), lo: px(i.zone?.low), hi: px(i.zone?.high) });
      case "fill": return sub("tmFill", { side, p: px(i.price), stop: px(i.stop), tps: (i.targets ?? []).map(px).join(" / ") || "—" });
      case "tp": return sub("tmTp", { level: i.level ?? "TP", p: px(i.price), f: `${Math.round((i.fraction ?? 0) * 100)} %` });
      case "stop_moved": return sub("tmStopMoved", { p: px(i.stop) });
      case "close": return sub("tmClose", { why: t(i.reason === "STOP" ? "tmWhyStop" : i.reason === "TIME_STOP" ? "tmWhyTime" : "tmWhyOther") });
      case "result": return sub("tmResult", { n: String(i.trade), r: `${(i.net_r ?? 0) >= 0 ? "+" : ""}${(i.net_r ?? 0).toFixed(2)}R`, pnl: `${(i.pnl_usd ?? 0) >= 0 ? "+" : "-"}${usd(Math.abs(i.pnl_usd ?? 0))}`, eq: usd(i.equity_after ?? 0) });
    }
  };
}

/** The replay chart: candles revealed up to `shown`, the active trade's levels and the strategy's markers so far. */
function ReplayChart({ sc, items, shown, follow }: { sc: TMScenario; items: TMItem[]; shown: number; follow: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const overlay = useRef<ISeriesApi<"Line"> | null>(null);
  const drawn = useRef(0);
  const theme = useThemeName();

  useEffect(() => {
    if (!host.current) return;
    const c = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--muted", "#9aa3b2"), fontFamily: "JetBrains Mono, Consolas, monospace" },
      grid: { vertLines: { color: "rgba(128,128,128,0.08)" }, horzLines: { color: "rgba(128,128,128,0.08)" } },
      rightPriceScale: { borderColor: "rgba(128,128,128,0.25)" },
      timeScale: { borderColor: "rgba(128,128,128,0.25)", timeVisible: true, secondsVisible: false, rightOffset: 8 },
    });
    const up = css("--up", "#34d399"), down = css("--down", "#f4607a");
    const s = c.addSeries(CandlestickSeries, { upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down });
    chart.current = c;
    series.current = s;
    markers.current = createSeriesMarkers(s, []);
    drawn.current = 0;
    return () => { c.remove(); chart.current = series.current = markers.current = overlay.current = null; lines.current = []; };
  }, [sc.id, theme]);

  // candles: append when moving forward a little, redraw when jumping
  useEffect(() => {
    const s = series.current, c = chart.current;
    if (!s || !c) return;
    const bar = (k: number) => { const [t, o, h, l, cl] = sc.candles[k]; return { time: Math.floor(t / 1000) as UTCTimestamp, open: o, high: h, low: l, close: cl }; };
    if (shown >= drawn.current && shown - drawn.current < 400 && drawn.current > 0) {
      for (let k = drawn.current; k < shown; k++) s.update(bar(k));
    } else {
      s.setData(Array.from({ length: shown }, (_, k) => bar(k)));
      c.timeScale().setVisibleLogicalRange({ from: Math.max(0, shown - 220), to: shown + 8 });
    }
    drawn.current = shown;
    if (follow) c.timeScale().scrollToRealTime();
  }, [shown, sc, follow, theme]);

  // levels, setup line and markers from the items known so far
  useEffect(() => {
    const s = series.current, c = chart.current;
    if (!s || !c) return;
    for (const l of lines.current) s.removePriceLine(l);
    lines.current = [];
    if (overlay.current) { c.removeSeries(overlay.current); overlay.current = null; }
    const done = new Set(items.filter((i) => i.kind === "result").map((i) => i.trade));
    const open = [...items].reverse().find((i) => (i.kind === "fill" || i.kind === "setup") && !done.has(i.trade));
    if (open) {
      const mine = items.filter((i) => i.trade === open.trade);
      const setup = mine.find((i) => i.kind === "setup");
      const fill = mine.find((i) => i.kind === "fill");
      const moved = [...mine].reverse().find((i) => i.kind === "stop_moved");
      const hit = new Set(mine.filter((i) => i.kind === "tp").map((i) => i.level));
      const add = (price: number | undefined, color: string, title: string, dashed = false) => {
        if (price !== undefined) lines.current.push(s.createPriceLine({ price, color, lineWidth: 1, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title }));
      };
      if (setup) {
        add(setup.zone?.low, "#d9b256", "", true);
        add(setup.zone?.high, "#d9b256", "", true);
        add(setup.level0?.price, "#9aa3b2", "fib 0", true);
        add(setup.level1?.price, cssVar("--text", "#eceff4"), "fib 1", true);
        const ls = c.addSeries(LineSeries, { color: "#f5d061", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        ls.setData((setup.line ?? []).map((p) => ({ time: Math.floor(p.timeMs / 1000) as UTCTimestamp, value: p.price })));
        overlay.current = ls;
      }
      if (fill) {
        add(fill.price, cssVar("--text", "#eceff4"), "entry");
        add(moved?.stop ?? fill.stop, "#f87171", "stop");
        (fill.targets ?? []).forEach((p, k) => { if (!hit.has(`TP${k + 1}`)) add(p, "#34d399", `TP${k + 1}`, true); });
      }
    }
    const snap = (ms: number) => Math.floor(Math.floor(ms / sc.tf_ms) * sc.tf_ms / 1000) as UTCTimestamp;
    markers.current?.setMarkers(items.filter((i) => i.kind === "fill" || i.kind === "tp" || i.kind === "result").map((i) => {
      if (i.kind === "fill") return { time: snap(i.t), position: i.side === 1 ? "belowBar" as const : "aboveBar" as const, color: i.side === 1 ? "#34d399" : "#f87171", shape: i.side === 1 ? "arrowUp" as const : "arrowDown" as const, text: "in" };
      if (i.kind === "tp") return { time: snap(i.t), position: "aboveBar" as const, color: "#34d399", shape: "circle" as const, text: i.level ?? "TP" };
      return { time: snap(i.t), position: "aboveBar" as const, color: (i.net_r ?? 0) >= 0 ? "#34d399" : "#f87171", shape: "square" as const, text: `${(i.net_r ?? 0) >= 0 ? "+" : ""}${(i.net_r ?? 0).toFixed(1)}R` };
    }));
  }, [items, sc, theme]);

  return <div ref={host} className="replay-chart" role="img" aria-label="Replay chart" />;
}

function Player({ sc }: { sc: TMScenario }) {
  const { t, lang } = useI18n();
  const text = useText();
  const sids = Object.keys(sc.timelines);
  const [sid, setSid] = useState(sids.includes("s7") ? "s7" : sids[0]);
  const tl = sc.timelines[sid];
  const n = sc.candles.length;
  const first = Math.max(1, sc.candles.findIndex((c) => c[0] >= sc.context_until_ms));
  const [shown, setShown] = useState(first);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const hold = useRef(0);
  const acc = useRef(0);
  const reduced = typeof window !== "undefined" && (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);

  const time = sc.candles[Math.max(0, shown - 1)][0] + sc.tf_ms; // the close of the newest candle shown: "now" in the replay
  const items = tl ? tl.items : [];
  const k = lastAtOrBefore(items, time);
  const visible = useMemo(() => items.slice(0, k + 1), [items, k]);
  const results = visible.filter((i) => i.kind === "result");
  const equity = results.length ? results[results.length - 1].equity_after ?? sc.account_rules.start_equity : sc.account_rules.start_equity;

  useEffect(() => { if (k >= 0 && playing) hold.current = performance.now() + EVENT_HOLD_MS; }, [k]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!playing) return;
    let raf = 0, last = performance.now();
    const step = (now: number) => {
      const dt = now - last;
      last = now;
      if (now >= hold.current) {
        acc.current += (dt / 1000) * BASE_CPS * speed;
        const add = Math.floor(acc.current);
        if (add > 0) {
          acc.current -= add;
          setShown((x) => {
            const y = Math.min(n, x + add);
            if (y >= n) setPlaying(false);
            return y;
          });
        }
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, n]);

  const nextEvent = useCallback(() => {
    const nxt = items.find((i) => i.t > time);
    if (!nxt) { setShown(n); return; }
    let j = shown;
    while (j < n && sc.candles[j - 1][0] + sc.tf_ms < nxt.t) j++;
    setShown(Math.min(n, j));
  }, [items, time, shown, n, sc]);

  const restart = () => { setPlaying(false); setShown(first); acc.current = 0; };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (["TEXTAREA", "INPUT", "SELECT"].includes((e.target as HTMLElement).tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.code === "Space") { e.preventDefault(); if (shown >= n) restart(); setPlaying((p) => !p); }
      else if (e.code === "ArrowRight") { e.preventDefault(); setPlaying(false); nextEvent(); }
      else if (e.code === "Home") { e.preventDefault(); restart(); }
      else if (/^Digit[1-4]$/.test(e.code)) setSpeed(SPEEDS[Number(e.code.slice(5)) - 1]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  const feed = [...visible].reverse().slice(0, 40);
  const finished = shown >= n;

  return (
    <>
      {sids.length > 1 && (
        <div className="seg mb-3 flex-wrap" role="group" aria-label={t("tmStrategy")}>
          {sids.map((s) => <button key={s} className={s === sid ? "on" : ""} aria-pressed={s === sid} onClick={() => setSid(s)}>{sc.timelines[s].title}</button>)}
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="num text-sm muted">{fmtTime(time)}</span>
            <span className="num text-sm"><span className="faint">{t("tmAccount")}</span> <b className={equity >= sc.account_rules.start_equity ? "up" : "down"}>{usd(equity)}</b></span>
          </div>
          <ReplayChart sc={sc} items={visible} shown={shown} follow={playing} />
          <div className="replay-controls mt-3">
            <button className="btn" onClick={restart} aria-label={t("tmRestart")}>⏮</button>
            <button className="btn primary replay-play" onClick={() => { if (finished) restart(); setPlaying((p) => !p); }} aria-label={playing ? t("tmPause") : t("tmPlay")}>{playing ? "⏸" : "▶"}</button>
            <button className="btn" onClick={nextEvent} aria-label={t("tmNext")}>⏭ <span className="hidden sm:inline">{t("tmNext")}</span></button>
            <div className="seg" role="group" aria-label={t("tmSpeed")}>
              {SPEEDS.map((s) => <button key={s} className={s === speed ? "on" : ""} aria-pressed={s === speed} onClick={() => setSpeed(s)}>×{s}</button>)}
            </div>
          </div>
          <input className="replay-scrub mt-3" type="range" min={first} max={n} value={shown} aria-label={t("tmScrub")}
            onChange={(e) => { setPlaying(false); setShown(Number(e.target.value)); }} />
          <p className="mt-2 text-xs faint">{reduced ? t("tmReduced") + " " : ""}{t("tmLegend")}</p>
        </Card>
        <Card title={t("tmFeed")} right={<span className="num text-xs faint">{results.length} / {tl?.trades ?? 0}</span>}>
          {feed.length === 0 ? <p className="text-sm muted">{t("tmWaiting")}</p> : (
            <ol className="replay-feed">
              {feed.map((i, j) => (
                <li key={`${i.trade}-${i.kind}-${i.t}-${j}`} className={`kind-${i.kind}`}>
                  <span className="num text-xs faint">{new Date(i.t).toLocaleString(lang === "ru" ? "ru-RU" : "en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} · #{i.trade}</span>
                  <span className="block text-sm">{text(i)}</span>
                </li>
              ))}
            </ol>
          )}
          {finished && tl && (
            <p className="mt-3 text-sm">
              {t("tmFinal")} <b className={tl.final_equity >= tl.start_equity ? "up" : "down"}>{usd(tl.final_equity)}</b> · {tl.trades} {t("uvTrades")} · {tl.total_r >= 0 ? "+" : ""}{tl.total_r.toFixed(2)}R
            </p>
          )}
        </Card>
      </div>
    </>
  );
}

export function Replay() {
  const { t, lang } = useI18n();
  const index = useLoad(api.timeMachineIndex, []);
  const scenarios = index.data?.scenarios ?? [];
  const [id, setId] = useState<string | null>(null);
  const cur = id ?? scenarios[0]?.id ?? null;
  const file = useLoad(() => (cur ? api.timeMachine(cur) : Promise.resolve(null)), [cur]);
  const sc = file.data;

  return (
    <>
      <PageTitle sub={t("tmSub")}>{t("nav_replay")}</PageTitle>
      {index.error && !index.data && <ErrorBox error={index.error} onRetry={index.reload} />}
      {index.loading && !index.data && <Skeleton h={200} />}
      {index.data && scenarios.length === 0 && <Empty>{t("tmEmpty")}</Empty>}
      {scenarios.length > 0 && (
        <div className="strategy-grid mb-4">
          {scenarios.map((s) => (
            <button key={s.id} className={`strategy-card ${s.id === cur ? "on" : ""}`} aria-pressed={s.id === cur} onClick={() => setId(s.id)}>
              <span className="font-semibold">{s.title[lang]}</span>
              <span className="mt-1 text-xs muted">{s.about[lang]}</span>
              <span className="mt-2 text-xs faint num">{fmtTime(s.start_ms).slice(0, 10)} – {fmtTime(s.end_ms).slice(0, 10)} · {Object.values(s.strategies).reduce((a, b) => a + b.trades, 0)} {t("uvTrades")}</span>
            </button>
          ))}
        </div>
      )}
      {file.loading && !sc && <Skeleton h={480} />}
      {file.error && !sc && <ErrorBox error={file.error} onRetry={file.reload} />}
      {sc && <Player key={sc.id} sc={sc} />}
      {sc && <p className="mt-4 text-xs faint"><Chip>{t("tmHonestChip")}</Chip> {t("tmHonest")}</p>}
    </>
  );
}
