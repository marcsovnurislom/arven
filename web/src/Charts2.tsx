import { useMemo } from "react";
import type { Signal } from "./api";
import { useI18n } from "./i18n";

export type TradePoint = { t: number; strategy: string; side: number; r: number };

const COLORS: Record<string, string> = { s4_impulse_retest: "#d9b256", s5_squeeze_breakout: "#6aa8ff", s6_trend_pullback: "#34d399" };
const colorOf = (sid: string) => COLORS[sid] ?? "#9aa3b2";

/** Running total of closed paper signals in R: one line per strategy plus the combined line, drawn in with an animation. */
export function EquityCurve({ trades }: { trades: TradePoint[] }) {
  const { t } = useI18n();
  const model = useMemo(() => {
    const W = 900, H = 300, P = { l: 44, r: 16, t: 14, b: 26 };
    const sorted = [...trades].sort((a, b) => a.t - b.t);
    if (sorted.length < 2) return null;
    const t0 = sorted[0].t, t1 = sorted[sorted.length - 1].t || t0 + 1;
    const ids = Array.from(new Set(sorted.map((x) => x.strategy)));
    const series: { id: string; pts: [number, number][]; final: number }[] = [];
    const all: [number, number][] = [];
    let total = 0;
    const per: Record<string, number> = {};
    const lines: Record<string, [number, number][]> = Object.fromEntries(ids.map((i) => [i, [[t0, 0]] as [number, number][]]));
    for (const tr of sorted) {
      total += tr.r;
      per[tr.strategy] = (per[tr.strategy] ?? 0) + tr.r;
      all.push([tr.t, total]);
      lines[tr.strategy].push([tr.t, per[tr.strategy]]);
    }
    for (const id of ids) series.push({ id, pts: lines[id], final: per[id] });
    const ys = [0, ...all.map((p) => p[1]), ...series.flatMap((s) => s.pts.map((p) => p[1]))];
    const lo = Math.min(...ys), hi = Math.max(...ys);
    const span = hi - lo || 1;
    const x = (v: number) => P.l + ((v - t0) / (t1 - t0 || 1)) * (W - P.l - P.r);
    const y = (v: number) => P.t + (1 - (v - lo) / span) * (H - P.t - P.b);
    const path = (pts: [number, number][]) => pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
    const ticks = Array.from({ length: 5 }, (_, i) => lo + (span * i) / 4);
    return { W, H, P, x, y, path, series, all, total, ticks, zeroY: y(0), lo, hi };
  }, [trades]);

  if (!model) return <p className="muted text-sm">{t("noClosed")}</p>;
  const { W, H, P, y, path, series, all, total, ticks, zeroY } = model;
  const approxLen = 4000;
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={t("equityTitle")} style={{ display: "block", overflow: "visible" }}>
        <defs>
          <linearGradient id="eqfill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={total >= 0 ? "#34d399" : "#f4607a"} stopOpacity="0.28" />
            <stop offset="100%" stopColor={total >= 0 ? "#34d399" : "#f4607a"} stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} stroke="currentColor" opacity="0.08" />
            <text x={P.l - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="currentColor" opacity="0.55" className="num">{v.toFixed(0)}R</text>
          </g>
        ))}
        <line x1={P.l} x2={W - P.r} y1={zeroY} y2={zeroY} stroke="currentColor" opacity="0.35" strokeDasharray="4 4" />
        <path d={`${path(all)} L${model.x(all[all.length - 1][0]).toFixed(1)},${zeroY} L${model.x(all[0][0]).toFixed(1)},${zeroY} Z`} fill="url(#eqfill)" className="fade-in" />
        {series.map((s, i) => (
          <path key={s.id} d={path(s.pts)} fill="none" stroke={colorOf(s.id)} strokeWidth="1.6" opacity="0.85" className="draw" style={{ ["--len" as string]: approxLen, animationDelay: `${0.15 * i}s` }} />
        ))}
        <path d={path(all)} fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinejoin="round" className="draw" style={{ ["--len" as string]: approxLen, animationDelay: "0.4s" }} />
        <circle cx={model.x(all[all.length - 1][0])} cy={y(total)} r="5" fill={total >= 0 ? "#34d399" : "#f4607a"} />
      </svg>
      <figcaption className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs muted">
        <span className="num" style={{ color: total >= 0 ? "var(--up)" : "var(--down)" }}>{t("finalR")}: {total >= 0 ? "+" : ""}{total.toFixed(1)}R</span>
        {series.map((s) => (
          <span key={s.id} className="num"><span className="dot mr-1" style={{ color: colorOf(s.id) }} />{s.id} {s.final >= 0 ? "+" : ""}{s.final.toFixed(1)}R</span>
        ))}
      </figcaption>
    </figure>
  );
}

/** Radial gauge, fill = share of the best possible value (e.g. how fresh the data is). */
export function Gauge({ value, label, tone }: { value: number; label: string; tone: "up" | "down" | "gold" }) {
  const r = 46, c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  const color = tone === "up" ? "var(--up)" : tone === "down" ? "var(--down)" : "var(--gold)";
  return (
    <svg viewBox="0 0 120 120" width="120" height="120" role="img" aria-label={label}>
      <circle cx="60" cy="60" r={r} fill="none" stroke="currentColor" opacity="0.1" strokeWidth="9" />
      <circle cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="9" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - v)} transform="rotate(-90 60 60)" style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(.2,.7,.2,1)" }} />
      <text x="60" y="66" textAnchor="middle" fontSize="20" fontWeight="700" fill="currentColor" className="num">{Math.round(v * 100)}%</text>
    </svg>
  );
}

/** Horizontal animated bar (0..1), used for win rates and shares. */
export function Bar({ value, color = "var(--gold)" }: { value: number; color?: string }) {
  return (
    <div className="bar-track" role="presentation">
      <div className="bar-fill" ref={(el) => { if (el) requestAnimationFrame(() => { el.style.width = `${Math.max(2, Math.min(100, value * 100))}%`; }); }} style={{ background: color }} />
    </div>
  );
}

/** A vertical price ladder for one signal: stop at the bottom (long), entry, then each take-profit, bars grow in. */
export function RiskLadder({ s }: { s: Signal }) {
  const { t } = useI18n();
  const levels = [
    ...s.tp_ladder.map(([r, frac, price], i) => ({ label: `TP${i + 1}`, price, tone: "up", note: `${r.toFixed(1)}R - ${Math.round(frac * 100)}%` })),
    { label: t("entry"), price: s.entry_reference, tone: "gold", note: "" },
    { label: t("stop"), price: s.stop, tone: "down", note: "-1R" },
  ].sort((a, b) => b.price - a.price);
  const hi = levels[0].price, lo = levels[levels.length - 1].price, span = hi - lo || 1;
  const H = 230;
  const y = (p: number) => 14 + ((hi - p) / span) * (H - 28);
  const color = (tone: string) => (tone === "up" ? "#34d399" : tone === "down" ? "#f4607a" : "#d9b256");
  return (
    <svg viewBox={`0 0 340 ${H}`} width="100%" role="img" aria-label={t("ladderTitle")}>
      <line x1="150" x2="150" y1="10" y2={H - 10} stroke="currentColor" opacity="0.15" strokeWidth="2" />
      {levels.map((l, i) => (
        <g key={l.label} className="fade-in" style={{ animationDelay: `${0.08 * i}s` }}>
          <circle cx="150" cy={y(l.price)} r="6" fill={color(l.tone)} />
          <rect x="164" y={y(l.price) - 11} width={Math.max(24, 140 * (Math.abs(l.price - s.entry_reference) / span) + 30)} height="22" rx="6" fill={color(l.tone)} opacity="0.2" className="grow-x" />
          <text x="172" y={y(l.price) + 4} fontSize="12" fill="currentColor" className="num">{l.label} {l.price.toFixed(0)}</text>
          {l.note && <text x="140" y={y(l.price) + 4} fontSize="11" textAnchor="end" fill="currentColor" opacity="0.6" className="num">{l.note}</text>}
        </g>
      ))}
    </svg>
  );
}
