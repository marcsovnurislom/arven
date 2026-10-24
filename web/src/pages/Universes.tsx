import { useEffect, useMemo, useRef, useState } from "react";
import { api, getMarket, type Universes as UniversesData } from "../api";
import { useI18n, type Key } from "../i18n";
import { useLoad, useThemeName } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, Skeleton, Stat } from "../ui";

const PERIODS = ["development", "validation", "devval", "forward"];
const usd = (x: number) => `$${Math.round(x).toLocaleString("en-US")}`;

function colors() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string, fb: string) => s.getPropertyValue(n).trim() || fb;
  return { gold: v("--gold", "#d9b256"), text: v("--text", "#eceff4"), faint: v("--faint", "#6b7381"), border: v("--border", "rgba(255,255,255,0.09)"),
    light: document.documentElement.dataset.theme === "light" };
}

/** The fan: every random trader's balance (faint), the strategy's (gold), the $1000 start (dashed). x = share of the trades done. */
function Fan({ d, label }: { d: UniversesData; label: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const theme = useThemeName();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const all = d.curves.flat().concat(d.strategy_result.curve);
    const sorted = [...all].sort((a, b) => a - b);
    const lo = Math.min(sorted[Math.floor(sorted.length * 0.005)], ...d.strategy_result.curve, d.account_rules.start_equity);
    const hi = Math.max(sorted[Math.floor(sorted.length * 0.995)], ...d.strategy_result.curve, d.account_rules.start_equity);
    let raf = 0;
    const start = performance.now();
    const draw = (now: number) => {
      const w = el.clientWidth, h = el.clientHeight, dpr = Math.min(2, window.devicePixelRatio || 1);
      if (el.width !== Math.round(w * dpr)) { el.width = Math.round(w * dpr); el.height = Math.round(h * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const c = colors();
      const pad = { l: 56, r: 12, t: 12, b: 22 };
      const X = (k: number, n: number) => pad.l + (n <= 1 ? 0 : (k / (n - 1)) * (w - pad.l - pad.r));
      const Y = (v: number) => pad.t + (1 - (Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo || 1)) * (h - pad.t - pad.b);
      // axis labels
      ctx.fillStyle = c.faint;
      ctx.font = "11px JetBrains Mono, Consolas, monospace";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (const v of [lo, d.account_rules.start_equity, hi]) ctx.fillText(usd(v), pad.l - 6, Y(v));
      ctx.strokeStyle = c.faint;
      ctx.setLineDash([5, 5]);
      ctx.beginPath(); ctx.moveTo(pad.l, Y(d.account_rules.start_equity)); ctx.lineTo(w - pad.r, Y(d.account_rules.start_equity)); ctx.stroke();
      ctx.setLineDash([]);
      // the random traders appear over the first second, then the strategy line draws itself
      const t = reduced ? 10 : (now - start) / 1000;
      const shown = Math.min(d.curves.length, Math.ceil(d.curves.length * Math.min(1, t / 1.0)));
      ctx.lineWidth = 1;
      ctx.strokeStyle = c.light ? "rgba(40,48,62,0.11)" : "rgba(160,175,200,0.07)";
      ctx.beginPath();
      for (let i = 0; i < shown; i++) {
        const cv = d.curves[i];
        cv.forEach((v, k) => (k === 0 ? ctx.moveTo(X(k, cv.length), Y(v)) : ctx.lineTo(X(k, cv.length), Y(v))));
      }
      ctx.stroke();
      const s = d.strategy_result.curve;
      const upto = Math.max(1, Math.round(s.length * Math.min(1, Math.max(0, (t - 1.0) / 1.2))));
      ctx.strokeStyle = c.gold;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      s.slice(0, upto).forEach((v, k) => (k === 0 ? ctx.moveTo(X(k, s.length), Y(v)) : ctx.lineTo(X(k, s.length), Y(v))));
      ctx.stroke();
      if (upto === s.length) {
        ctx.fillStyle = c.gold;
        ctx.beginPath(); ctx.arc(X(s.length - 1, s.length), Y(s[s.length - 1]), 4, 0, 2 * Math.PI); ctx.fill();
      }
      if (t < 2.4) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    let first = true; // the observer fires once on observe: that must not cut the opening animation short
    const ro = new ResizeObserver(() => {
      if (first) { first = false; return; }
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame((n) => draw(n + 1e6));
    });
    ro.observe(el);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, [d, theme]);
  return <canvas ref={ref} className="universe-fan" role="img" aria-label={label} />;
}

/** Where the strategy's final balance falls among the random traders' final balances. */
function Histogram({ d }: { d: UniversesData }) {
  const { t } = useI18n();
  const bins = 40;
  const f = d.finals;
  const lo = Math.min(...f, d.strategy_result.final_equity), hi = Math.max(...f, d.strategy_result.final_equity);
  const counts = new Array(bins).fill(0);
  for (const v of f) counts[Math.min(bins - 1, Math.floor(((v - lo) / (hi - lo || 1)) * bins))] += 1;
  const max = Math.max(...counts);
  const pos = ((d.strategy_result.final_equity - lo) / (hi - lo || 1)) * 100;
  const startPos = ((d.account_rules.start_equity - lo) / (hi - lo || 1)) * 100;
  return (
    <div>
      <div className="universe-hist" aria-hidden="true">
        {counts.map((c, i) => <span key={i} style={{ height: `${(c / max) * 100}%` }} />)}
        {startPos >= 0 && startPos <= 100 && <i className="start" style={{ left: `${startPos}%` }} />}
        <i className="mark" style={{ left: `${Math.min(99.5, Math.max(0.5, pos))}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-xs faint num"><span>{usd(lo)}</span><span>{usd(hi)}</span></div>
      <p className="mt-1 text-xs faint">{t("uvFinals")}</p>
    </div>
  );
}

export function Universes() {
  const { t } = useI18n();
  const index = useLoad(api.universesIndex, []);
  const entries = index.data?.entries ?? [];
  const strategies = useMemo(() => [...new Map(entries.map((e) => [e.strategy, e.title])).entries()], [entries]);
  const [sid, setSid] = useState<string | null>(null);
  const [period, setPeriod] = useState("validation");
  const cur = sid ?? strategies.find(([s]) => s === "s7")?.[0] ?? strategies[0]?.[0] ?? null;
  const periods = PERIODS.filter((p) => entries.some((e) => e.strategy === cur && e.period === p));
  const per = periods.includes(period) ? period : periods[0] ?? null;
  const file = useLoad(() => (cur && per ? api.universes(cur, per) : Promise.resolve(null)), [cur, per]);
  const d = file.data;
  const pct = d ? Math.round(d.percentile) : 0;
  const v = d?.verdict;
  const title = (x: string) => strategies.find(([s]) => s === x)?.[1] ?? x;

  return (
    <>
      <PageTitle sub={t("uvSub")}>{t("nav_universes")}</PageTitle>
      {index.error && !index.data && <ErrorBox error={index.error} onRetry={index.reload} />}
      {index.loading && !index.data && <Skeleton h={300} />}
      {index.data && entries.length === 0 && <Empty>{t("uvEmpty")}</Empty>}
      {strategies.length > 0 && (
        <div className="strategy-grid mb-4">
          {strategies.map(([s, name]) => {
            const e = entries.find((x) => x.strategy === s && x.period === "validation");
            return (
              <button key={s} className={`strategy-card ${s === cur ? "on" : ""}`} aria-pressed={s === cur} onClick={() => setSid(s)}>
                <span className="font-semibold">{name}</span>
                {e && <span className="mt-2 text-xs faint">{t("per_validation")}: <span className="num">{Math.round(e.percentile)} %</span></span>}
              </button>
            );
          })}
        </div>
      )}
      {periods.length > 0 && (
        <div className="seg mb-4 flex-wrap" role="group" aria-label={t("stPeriod")}>
          {periods.map((p) => <button key={p} className={p === per ? "on" : ""} aria-pressed={p === per} onClick={() => setPeriod(p)}>{t(`per_${p}` as Key)}</button>)}
        </div>
      )}
      {file.loading && !d && <Skeleton h={420} />}
      {file.error && !d && <ErrorBox error={file.error} onRetry={file.reload} />}
      {d && (
        <>
          <Card className="mb-4">
            <div className={`universe-verdict ${v}`}>
              <Chip tone={v === "skill_candidate" ? "up" : v === "too_few" ? "warn" : ""}>{t(`uvV_${v}` as Key)}</Chip>
              <p className="mt-2 text-lg font-semibold leading-snug">
                {v === "too_few"
                  ? t("uvTooFew").replace("{n}", String(d.trades)).replace("{min}", String(d.min_trades))
                  : t("uvBetterThan").replace("{s}", title(d.strategy)).replace("{p}", String(pct))}
              </p>
              <p className="mt-1 text-sm muted">{v === "luck" ? t("uvLuck") : v === "skill_candidate" ? t("uvSkill") : t("uvTooFewHelp")}</p>
              {(d.period === "development" || d.period === "devval") && <p className="mt-2 text-sm warn">{t("uvInSample")}</p>}
            </div>
          </Card>
          <div className="mb-4 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Card title={`${t("uvFan")} · ${getMarket() === "gold" ? t("evGold") : "BTC"}`}>
              <Fan d={d} label={t("uvFan")} />
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs muted">
                <span><span className="uv-key gold-bg" />{title(d.strategy)}</span>
                <span><span className="uv-key faint-bg" />{d.draws.toLocaleString("en-US")} {t("uvRandoms")}</span>
                <span><span className="uv-key dash" />{t("uvStart")}</span>
              </div>
            </Card>
            <Card title={t("uvNumbers")}>
              <div className="grid grid-cols-2 gap-4">
                <Stat label={t("uvStrategy")} value={<span className={d.strategy_result.final_equity >= 1000 ? "up" : "down"}>{usd(d.strategy_result.final_equity)}</span>} sub={`${d.trades} ${t("uvTrades")}`} />
                <Stat label={t("uvMedian")} value={usd(d.universes.final_p50)} sub={`${t("uvRange90")} ${usd(d.universes.final_p05)}–${usd(d.universes.final_p95)}`} />
                <Stat label={t("uvPercentile")} value={`${pct} %`} sub={`${t("uvBar")} ${d.skill_percentile} %`} />
                <Stat label={t("uvAbove")} value={`${Math.round(d.universes.share_above_start * 100)} %`} sub={t("uvAboveSub")} />
              </div>
              <div className="mt-5"><Histogram d={d} /></div>
            </Card>
          </div>
          <p className="text-xs faint">
            {t("uvHow")} {t("uvSeed")}: {d.seed.join("/")}, {d.created_at.slice(0, 10)}{d.git_commit ? `, ${d.git_commit.slice(0, 7)}` : ""}.
          </p>
        </>
      )}
    </>
  );
}
