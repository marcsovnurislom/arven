import { useMemo, useState } from "react";
import { api, type Signal } from "../api";
import { CandleChart, type ChartLine } from "../CandleChart";
import { useI18n } from "../i18n";
import { useLoad, useNow } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, SidePill, Skeleton, fmt, fmtTime, shortId } from "../ui";

const MIN15 = 15 * 60_000;

function Detail({ s }: { s: Signal }) {
  const { t } = useI18n();
  const now = useNow();
  const { data, error, reload } = useLoad(() => api.candles("15m", 220), [s.signal_id], 30000);
  const lines = useMemo<ChartLine[]>(
    () => [
      { price: s.entry_reference, color: "#d9b256", title: t("entry") },
      { price: s.stop, color: "#f4607a", title: t("stop"), dashed: true },
      ...s.tp_ladder.map(([r, , price], i) => ({ price, color: "#34d399", title: `TP${i + 1} ${r.toFixed(1)}R`, dashed: true })),
    ],
    [s, t],
  );
  const markers = useMemo(() => [{ timeMs: s.event_time_ms, side: s.side, text: s.strategy_id.split("_")[0].toUpperCase() }], [s]);
  const countdown = Math.max(0, Math.ceil(now / MIN15) * MIN15 - now);
  const mm = String(Math.floor(countdown / 60000)).padStart(2, "0"), ss = String(Math.floor((countdown % 60000) / 1000)).padStart(2, "0");

  return (
    <Card
      title={<span className="flex items-center gap-2"><SidePill side={s.side} /> <span className="num">{s.strategy_id}</span> <span className="faint num">#{shortId(s.signal_id)}</span></span>}
      right={<span className="text-xs muted">{t("nextClose")} <span className="num gold">{mm}:{ss}</span></span>}
    >
      {error && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Skeleton h={380} />}
      {data && <CandleChart candles={data.candles} lines={lines} markers={markers} height={380} />}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div>
          <table>
            <tbody>
              <tr><th>{t("entry")}</th><td className="num">{fmt(s.entry_reference)}</td></tr>
              <tr><th>{t("stop")}</th><td className="num down">{fmt(s.stop)}</td></tr>
              {s.tp_ladder.map(([r, frac, price], i) => (
                <tr key={i}><th>TP{i + 1}</th><td className="num up">{fmt(price)} <span className="faint">({r.toFixed(2)}R, {Math.round(frac * 100)}%)</span></td></tr>
              ))}
              <tr><th>{t("grade")}</th><td><Chip tone="gold">{s.grade}</Chip></td></tr>
              <tr><th>{t("confidence")}</th><td className="num">{Math.round(s.confidence * 100)}%</td></tr>
              <tr><th>{t("regime")}</th><td className="num">{s.regime}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="grid gap-3 text-sm">
          <div>
            <div className="text-xs uppercase tracking-wider faint">{t("why")}</div>
            <ul className="mt-1 list-disc pl-5 muted">{s.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider faint">{t("risk")}</div>
            <p className="mt-1 muted">{s.risk_checks.length ? s.risk_checks.join("; ") : "—"}</p>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wider faint">{t("updates")}</div>
            {s.updates.length === 0 ? <p className="mt-1 muted">—</p> : (
              <ul className="mt-1 grid gap-1">
                {s.updates.map((u, i) => <li key={i} className="num text-xs"><span className="faint">{fmtTime(u.time_ms)}</span> <Chip>{u.kind}</Chip> <span className="muted">{u.detail}</span></li>)}
              </ul>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

export function Signals() {
  const { t } = useI18n();
  const [strategy, setStrategy] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const { data, error, loading, reload } = useLoad(() => api.signals(strategy || undefined, 150), [strategy], 20000);
  const strategies = useLoad(api.strategies, []);
  const list = data?.signals ?? [];
  const current = list.find((s) => s.signal_id === selected) ?? list[0] ?? null;

  return (
    <>
      <PageTitle sub={t("honesty")}>{t("nav_signals")}</PageTitle>
      <div className="mb-3 max-w-xs">
        <label className="sr-only" htmlFor="strategy-filter">Strategy</label>
        <select id="strategy-filter" value={strategy} onChange={(e) => { setStrategy(e.target.value); setSelected(null); }}>
          <option value="">All strategies</option>
          {(strategies.data?.strategies ?? []).map((sid) => <option key={sid} value={sid}>{sid}</option>)}
        </select>
      </div>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Skeleton h={300} />}
      {data && list.length === 0 && <Empty>{t("emptySignals")}</Empty>}
      {current && (
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <div className="glass max-h-[70vh] overflow-y-auto p-2" role="listbox" aria-label="Signals">
            {list.map((s) => (
              <button
                key={s.signal_id}
                role="option"
                aria-selected={s.signal_id === current.signal_id}
                onClick={() => setSelected(s.signal_id)}
                className="mb-1 w-full rounded-xl p-3 text-left"
                style={{ background: s.signal_id === current.signal_id ? "var(--gold-soft)" : "transparent", border: "1px solid var(--border)", color: "inherit", cursor: "pointer" }}
              >
                <div className="flex items-center justify-between gap-2">
                  <SidePill side={s.side} />
                  <Chip tone={s.status === "closed" ? "" : "gold"}>{s.status}</Chip>
                </div>
                <div className="num mt-1 text-sm">{s.strategy_id}</div>
                <div className="num text-xs faint">{fmtTime(s.event_time_ms)} · {fmt(s.entry_reference, 0)}</div>
              </button>
            ))}
          </div>
          <Detail s={current} />
        </div>
      )}
    </>
  );
}
