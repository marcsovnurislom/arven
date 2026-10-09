import type { ReactNode } from "react";
import { ApiError } from "./api";
import { useI18n } from "./i18n";

export const fmt = (x: number | null | undefined, digits = 2) =>
  x === null || x === undefined || !Number.isFinite(x) ? "n/a" : x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const fmtPct = (x: number | null | undefined, digits = 1) => (x === null || x === undefined || !Number.isFinite(x) ? "n/a" : `${(x * 100).toFixed(digits)}%`);
export const fmtR = (x: number | null | undefined) => (x === null || x === undefined || !Number.isFinite(x) ? "n/a" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}R`);
export const signClass = (x: number | null | undefined) => (x === null || x === undefined ? "" : x > 0 ? "up" : x < 0 ? "down" : "");
export const fmtTime = (ms: number) => new Date(ms).toISOString().replace("T", " ").slice(0, 16) + " UTC";
export const shortId = (id: string) => id.slice(0, 8);

export function Card({ title, children, right, className = "" }: { title?: ReactNode; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <section className={`glass rise p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-medium uppercase tracking-wider muted">{title}</h2>
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
      <div className={`num mt-1 text-2xl font-semibold ${tone ?? ""}`}>{value}</div>
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
    <div className="mb-4">
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{children}</h1>
      {sub && <p className="mt-1 text-sm muted">{sub}</p>}
    </div>
  );
}
