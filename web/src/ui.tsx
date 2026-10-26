import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "./api";
import { CountUp } from "./fx";
import { useI18n } from "./i18n";

export const fmt = (x: number | null | undefined, digits = 2) =>
  x === null || x === undefined || !Number.isFinite(x) ? "n/a" : x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
/** A price with decimals for its size (same rule as arven.core.prices): >= 100 two, >= 10 three, below that five;
 * ``ref`` (a signal's entry) sets the precision so every level of one signal is written alike. */
export const priceDigits = (x: number) => (Math.abs(x) >= 100 ? 2 : Math.abs(x) >= 10 ? 3 : 5);
export const fmtPrice = (x: number | null | undefined, ref?: number | null) =>
  x === null || x === undefined || !Number.isFinite(x) ? "n/a" : fmt(x, priceDigits(ref ?? x));
export const fmtPct = (x: number | null | undefined, digits = 1) => (x === null || x === undefined || !Number.isFinite(x) ? "n/a" : `${(x * 100).toFixed(digits)}%`);
export const fmtR = (x: number | null | undefined) => (x === null || x === undefined || !Number.isFinite(x) ? "n/a" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}R`);
export const signClass = (x: number | null | undefined) => (x === null || x === undefined ? "" : x > 0 ? "up" : x < 0 ? "down" : "");
export const fmtTime = (ms: number) => new Date(ms).toISOString().replace("T", " ").slice(0, 16) + " UTC";
export const shortId = (id: string) => id.slice(0, 8);
/** A theme colour for canvas / chart drawing (read when drawn - pair it with useThemeName() so a theme switch redraws). */
export const cssVar = (name: string, fallback: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

/** A countdown in words: "2 d 3 h" / "7 h 12 min" / "4 min 05 s". */
export function until(ms: number, lang: "en" | "ru"): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const [d, h, m, sec] = [Math.floor(s / 86400), Math.floor((s % 86400) / 3600), Math.floor((s % 3600) / 60), s % 60];
  const u = lang === "ru" ? { d: "д", h: "ч", m: "мин", s: "с" } : { d: "d", h: "h", m: "min", s: "s" };
  if (d > 0) return `${d} ${u.d} ${h} ${u.h}`;
  if (h > 0) return `${h} ${u.h} ${m} ${u.m}`;
  return `${m} ${u.m} ${String(sec).padStart(2, "0")} ${u.s}`;
}

export function Card({ title, children, right, className = "" }: { title?: ReactNode; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <section className={`glass rise p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <header className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <h2 className="min-w-0 break-words text-sm font-medium uppercase tracking-wider muted">{title}</h2>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, tone, sub }: { label: string; value: ReactNode; tone?: string; sub?: ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider faint">{label}</div>
      <div className={`num mt-1 text-2xl font-semibold ${tone ?? ""}`}>{typeof value === "number" && Number.isFinite(value) ? <CountUp value={value} /> : value}</div>
      {sub && <div className="mt-1 text-xs muted">{sub}</div>}
    </div>
  );
}

export function Chip({ children, tone = "" }: { children: ReactNode; tone?: "up" | "down" | "gold" | "warn" | "" }) {
  return <span className={`chip ${tone}`}>{children}</span>;
}

export function Skeleton({ h = 24, w = "100%" }: { h?: number; w?: number | string }) {
  return <div className="skeleton" style={{ height: h, width: w }} aria-hidden="true" />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed p-6 text-center text-sm muted" style={{ borderColor: "var(--border)" }}>{children}</div>;
}

export function ErrorBox({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const { t } = useI18n();
  const message = error.status === 0 ? t("offline") : error.status === 503 ? t("busy") : error.message;
  return (
    <div role="alert" className="glass flex items-center justify-between gap-3 p-4 text-sm" style={{ borderColor: "var(--down)" }}>
      <span className="down">{message}</span>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          {t("retry")}
        </button>
      )}
    </div>
  );
}

export function SidePill({ side }: { side: 1 | -1 }) {
  const { t } = useI18n();
  return <Chip tone={side === 1 ? "up" : "down"}>{side === 1 ? t("long") : t("short")}</Chip>;
}

export function Sparkline({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${28 - ((v - min) / span) * 26}`).join(" ");
  return (
    <svg viewBox="0 0 100 30" width="110" height="30" role="img" aria-label="24 hour price sparkline">
      <polyline points={pts} fill="none" stroke={up ? "var(--up)" : "var(--down)"} strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="page-title mb-5">
      <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{children}</h1>
      {sub && <p className="mt-2 max-w-3xl text-sm leading-relaxed muted">{sub}</p>}
    </div>
  );
}

/** Frame around a chart: "fit" and "full screen" buttons (Escape leaves full screen). The child gets ``fill`` (always fill
 * this frame) and ``fitKey`` (bumped by the fit button). */
export function ChartFrame({ height, labels, children }: { height: number; labels: { fit: string; full: string; exit: string }; children: (o: { fill: true; fitKey: number }) => ReactNode }) {
  const [full, setFull] = useState(false);
  const [fitKey, setFitKey] = useState(0);
  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFull(false); };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [full]);
  return (
    <div className={full ? "chart-full" : "chart-frame"} style={full ? undefined : { height }}>
      <div className="chart-tools">
        <button className="btn sm" onClick={() => setFitKey((k) => k + 1)} title={labels.fit} aria-label={labels.fit}>⤢ <span className="hidden sm:inline">{labels.fit}</span></button>
        <button className="btn sm" onClick={() => setFull((f) => !f)} title={full ? labels.exit : labels.full} aria-label={full ? labels.exit : labels.full} aria-pressed={full}>
          {full ? "✕" : "⛶"} <span className="hidden sm:inline">{full ? labels.exit : labels.full}</span>
        </button>
      </div>
      {children({ fill: true, fitKey })}
    </div>
  );
}
