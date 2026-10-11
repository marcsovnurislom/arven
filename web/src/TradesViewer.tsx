import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { api, type TradeRec } from "./api";
import type { ChartLine, ChartMarker, ChartOverlay } from "./CandleChart";
import { useI18n, type Key } from "./i18n";
import { useLoad } from "./hooks";
import { Card, ChartFrame, Empty, ErrorBox, SidePill, Skeleton, Stat, fmt, fmtPct, fmtR, fmtTime, signClass } from "./ui";

const CandleChart = lazy(() => import("./CandleChart").then((m) => ({ default: m.CandleChart })));
export const usd = (x: number) => `${x < 0 ? "-" : ""}$${Math.abs(x).toFixed(2)}`;
export const ZONE_STYLE: Record<string, { color: string; label: string }> = {
  order_block: { color: "#a78bfa", label: "Order block" },
  fvg: { color: "#60a5fa", label: "FVG" },
  ifvg: { color: "#22d3ee", label: "iFVG" },
  level: { color: "#94a3b8", label: "SnR level" },
};

/** Balance after each trade, with the starting balance as a dashed reference line. */
export function EquityCurve({ values, start, label, marked }: { values: number[]; start: number; label: string; marked: number }) {
  const W = 1000, H = 160, pad = 8;
  const min = Math.min(start, ...values), max = Math.max(start, ...values);
  const span = max - min || 1;
  const x = (i: number) => (i / Math.max(1, values.length - 1)) * W;
  const y = (v: number) => pad + (1 - (v - min) / span) * (H - 2 * pad);
  const pts = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const up = values[values.length - 1] >= start;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-40 w-full" role="img" aria-label={label}>
        <defs>
          <linearGradient id="eqfill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={up ? "var(--up)" : "var(--down)"} stopOpacity="0.28" />
            <stop offset="100%" stopColor={up ? "var(--up)" : "var(--down)"} stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon points={`0,${H} ${pts} ${W},${H}`} fill="url(#eqfill)" />
        <line x1={0} x2={W} y1={y(start)} y2={y(start)} stroke="currentColor" strokeOpacity={0.35} strokeDasharray="6 6" vectorEffect="non-scaling-stroke" />
        <polyline points={pts} fill="none" stroke={up ? "var(--up)" : "var(--down)"} strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {marked > 0 && marked < values.length && <circle cx={x(marked)} cy={y(values[marked])} r={5} fill="var(--gold)" vectorEffect="non-scaling-stroke" />}
      </svg>
      <div className="mt-1 flex justify-between text-xs faint num"><span>min {usd(Math.min(...values))}</span><span>start {usd(start)}</span><span>max {usd(Math.max(...values))}</span></div>
    </div>
  );
}

export function TradeChart({ tr }: { tr: TradeRec }) {
  const { t } = useI18n();
  const lines = useMemo<ChartLine[]>(
    () => [
      { price: tr.entry, color: "#eceff4", title: t("s7tEntry") },
      { price: tr.stop, color: "#f87171", title: t("s7tStop") },
      ...tr.targets.map((p, k) => ({ price: p, color: "#34d399", title: `TP${k + 1}`, dashed: true })),
      ...(tr.zone ? [{ price: tr.zone.low, color: "#d9b256", title: "", dashed: true }, { price: tr.zone.high, color: "#d9b256", title: "", dashed: true }] : []),
    ],
    [tr, t],
  );
  const overlays = useMemo<ChartOverlay[]>(() => {
    const c = tr.candles;
    const snap = (ms: number) => {
      let lo = 0;
      for (let k = 0; k < c.length; k++) if (c[k].t <= ms) lo = k;
      return c[lo].t;
    };
    const end = snap(tr.exit_time_ms);
    const o: ChartOverlay[] = tr.line ? [{ points: tr.line.points, color: "#f5d061", width: 2 }] : [];
    for (const z of tr.smc_zones ?? []) {
      const st = ZONE_STYLE[z.kind] ?? ZONE_STYLE.level;
      const from = snap(Math.max(z.timeMs, c[0].t));
      if (from >= end) continue;
      o.push({ points: [{ timeMs: from, price: z.high }, { timeMs: end, price: z.high }], color: st.color, width: 1 });
      if (z.low !== z.high) o.push({ points: [{ timeMs: from, price: z.low }, { timeMs: end, price: z.low }], color: st.color, width: 1, dashed: true });
    }
    return o;
  }, [tr]);
  const markers = useMemo<ChartMarker[]>(
    () => [
      { timeMs: tr.entry_time_ms, side: tr.side, text: t("s7tEntry") },
      { timeMs: tr.exit_time_ms, side: tr.side === 1 ? -1 : 1, text: `${t("s7tExit")} ${fmtR(tr.net_r)}`, shape: "square" as const, color: tr.net_r >= 0 ? "#34d399" : "#f87171" },
    ],
    [tr, t],
  );
  const range = useMemo(() => ({
    fromMs: tr.line && tr.level0 ? Math.min(tr.line.points[0].timeMs, tr.level0.timeMs) : tr.entry_time_ms - 24 * 3_600_000,
    toMs: tr.exit_time_ms,
  }), [tr]);
  return (
    <ChartFrame height={500} labels={{ fit: t("chartFit"), full: t("chartFull"), exit: t("chartExit") }}>
      {({ fill, fitKey }) => (
        <Suspense fallback={<Skeleton h={500} />}>
          <CandleChart key={tr.id} candles={tr.candles} lines={lines} overlays={overlays} markers={markers} range={range} fitKey={fitKey} fill={fill} />
        </Suspense>
      )}
    </ChartFrame>
  );
}

type Filter = "all" | "wins" | "losses";
const PERIOD_ORDER = ["development", "validation", "devval", "test", "forward"];

/** Every strategy's trades: pick a strategy and a period, see the account, the balance curve and each trade on its chart. */
export function StrategyTrades() {
  const { t } = useI18n();
  const index = useLoad(() => api.strategyTradesIndex(), []);
  const entries = index.data?.entries ?? [];
  const strategies = useMemo(() => [...new Map(entries.map((e) => [e.strategy, e.title])).entries()], [entries]);
  const [sid, setSid] = useState<string | null>(null);
  const [period, setPeriod] = useState<string | null>(null);
  const cur = sid ?? strategies[0]?.[0] ?? null;
  const periods = entries.filter((e) => e.strategy === cur).sort((a, b) => PERIOD_ORDER.indexOf(a.period) - PERIOD_ORDER.indexOf(b.period));
  const per = period && periods.some((e) => e.period === period) ? period : periods[0]?.period ?? null;
  const file = useLoad(() => (cur && per ? api.strategyTrades(cur, per) : Promise.resolve(null)), [cur, per]);
  const [filter, setFilter] = useState<Filter>("all");
  const [id, setId] = useState<string | null>(null);
  useEffect(() => { setId(null); setFilter("all"); }, [cur, per]);
  const all = file.data?.trades ?? [];
  const sum = file.data?.summary ?? null;
  const shown = all.filter((x) => (filter === "wins" ? x.pnl_usd > 0 : filter === "losses" ? x.pnl_usd <= 0 : true));
  const idx = Math.max(0, shown.findIndex((x) => x.id === id));
  const tr = shown[idx];
  const curve = useMemo(() => [sum?.account.start_equity ?? 1000, ...all.map((x) => x.equity_after)], [all, sum]);

  return (
    <section className="mb-8">
      <h2 className="mb-1 text-xl font-semibold">{t("stTitle")}</h2>
      <p className="mb-4 max-w-3xl text-sm muted">{t("stHelp")}</p>
      {index.error && !index.data && <ErrorBox error={index.error} onRetry={index.reload} />}
      {index.data && entries.length === 0 && <Empty>{t("stEmpty")}</Empty>}
      {strategies.length > 0 && (
        <div className="strategy-grid mb-4">
          {strategies.map(([s, title]) => {
            const rows = entries.filter((e) => e.strategy === s).sort((a, b) => PERIOD_ORDER.indexOf(a.period) - PERIOD_ORDER.indexOf(b.period));
            return (
              <button key={s} className={`strategy-card ${s === cur ? "on" : ""}`} aria-pressed={s === cur} onClick={() => { setSid(s); setPeriod(null); }}>
                <span className="font-semibold">{title}</span>
                <span className="mt-2 grid gap-1 text-xs">
                  {rows.map((e) => (
                    <span key={e.period} className="flex justify-between gap-2">
                      <span className="faint">{t(`per_${e.period}` as Key)}</span>
                      <span className={`num ${signClass(e.summary.total_r)}`}>{fmtR(e.summary.total_r)} · {e.summary.trades}</span>
                    </span>
                  ))}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {periods.length > 0 && (
        <div className="seg mb-4 flex-wrap" role="group" aria-label={t("stPeriod")}>
          {periods.map((e) => <button key={e.period} className={e.period === per ? "on" : ""} aria-pressed={e.period === per} onClick={() => setPeriod(e.period)}>{t(`per_${e.period}` as Key)}</button>)}
        </div>
      )}
      {file.loading && !file.data && <Skeleton h={300} />}
      {sum && all.length === 0 && <Empty>{t("stNoTrades")}</Empty>}
      {sum && all.length > 0 && (
        <div className="mb-4 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <Card>
            <div className="grid grid-cols-2 gap-5">
              <Stat label={t("s7tAccount")} value={<span className={signClass(sum.account.return)}>{usd(sum.account.final_equity)}</span>} sub={fmtPct(sum.account.return)} />
              <Stat label={t("s7tTrades")} value={sum.trades} />
              <Stat label={t("s7tWinRate")} value={fmtPct(sum.win_rate)} />
              <Stat label={t("s7tMaxDd")} value={fmtPct(sum.account.max_drawdown)} />
            </div>
          </Card>
          <Card title={t("s7tEquity")} right={<span className={`num text-sm ${signClass(sum.total_r)}`}>{fmtR(sum.total_r)}</span>}>
            <EquityCurve values={curve} start={sum.account.start_equity} label={t("s7tEquity")} marked={tr ? tr.n : 0} />
          </Card>
        </div>
      )}
      {all.length > 0 && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          {tr ? (
            <Card
              title={<span className="flex items-center gap-2"><SidePill side={tr.side} /><span className="num">{fmtTime(tr.entry_time_ms)}</span><span className="faint num">#{tr.n}</span></span>}
              right={<span className={`num text-base font-semibold ${signClass(tr.pnl_usd)}`}>{usd(tr.pnl_usd)} · {fmtR(tr.net_r)}</span>}
            >
              <TradeChart tr={tr} />
              <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
                <dt className="muted">{t("s7tEntry")}</dt><dd className="num">{fmt(tr.entry, 1)}</dd>
                <dt className="muted">{t("s7tStop")}</dt><dd className="num">{fmt(tr.stop, 1)}</dd>
                <dt className="muted">{t("s7tSize")}</dt><dd className="num">{tr.size_btc.toFixed(2)} BTC</dd>
                <dt className="muted">{t("s7tExit")}</dt><dd className="num">{fmtTime(tr.exit_time_ms)} · {tr.exit_reasons.join(", ")}</dd>
              </dl>
              <div className="mt-3 flex justify-between">
                <button className="btn" onClick={() => setId(shown[Math.max(0, idx - 1)].id)} disabled={idx === 0}>← {t("tourPrev")}</button>
                <button className="btn" onClick={() => setId(shown[Math.min(shown.length - 1, idx + 1)].id)} disabled={idx >= shown.length - 1}>{t("tourNext")} →</button>
              </div>
            </Card>
          ) : <Empty>{t("s7tNoneInFilter")}</Empty>}
          <Card title={`${t("s7tList")} (${shown.length})`}>
            <div className="mb-3 flex flex-wrap gap-1">
              {([["all", t("s7tFilterAll")], ["wins", t("s7tFilterWins")], ["losses", t("s7tFilterLosses")]] as [Filter, string][]).map(([k, label]) => (
                <button key={k} className={`btn sm ${filter === k ? "primary" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
              ))}
            </div>
            <div className="max-h-[640px] overflow-y-auto" role="listbox" aria-label={t("s7tList")}>
              {shown.map((x) => (
                <button key={x.id} role="option" aria-selected={x.id === tr?.id} onClick={() => setId(x.id)} className={`trade-row ${x.id === tr?.id ? "on" : ""}`}>
                  <span className="num faint w-8">{x.n}</span>
                  <span className="num">{fmtTime(x.entry_time_ms).slice(0, 10)}</span>
                  <span className={x.side === 1 ? "up" : "down"}>{x.side === 1 ? "L" : "S"}</span>
                  <span className={`num ml-auto ${signClass(x.pnl_usd)}`}>{usd(x.pnl_usd)}</span>
                  <span className="num faint w-20 text-right">{usd(x.equity_after)}</span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      )}
    </section>
  );
}
