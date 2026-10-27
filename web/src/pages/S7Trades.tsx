import { useCallback, useEffect, useMemo, useState } from "react";
import { api, getMarket, marketName, setMarketId, tradeSize, type S7IndexEntry, type S7Trade, type S7TradeLabel } from "../api";
import { useI18n } from "../i18n";
import { useLoad } from "../hooks";
import { EquityCurve, TradeChart, ZONE_STYLE, usd } from "../TradesViewer";
import { Card, Chip, Empty, ErrorBox, fmt, fmtPct, fmtPrice, fmtR, fmtTime, PageTitle, SidePill, signClass, Skeleton, Stat } from "../ui";

type Filter = "all" | "wins" | "losses" | "unmarked" | "wrong";
type Verdict = S7TradeLabel["verdict"];

/** The live S7 models (config/live.yaml), in the order of the page's switch. */
export const S7_MODELS: [string, string][] = [
  ["s7_trend_break_fib", "S7 15m"], ["s7_smc", "S7-SMC 15m"], ["s7_30m", "S7 30m"], ["s7_1h", "S7 1h"], ["s7_4h", "S7 4h"], ["s7_1d", "S7 1d"],
];
const PERIODS = ["development", "validation", "forward"] as const;

/** One cell of the summary tables: trades and total R (coloured), the $1000 account's return below. */
function Cell({ e, on, onClick }: { e?: S7IndexEntry; on: boolean; onClick: () => void }) {
  if (!e) return <td className="faint">—</td>;
  return (
    <td>
      <button className={`s7-cell ${on ? "on" : ""}`} onClick={onClick} aria-pressed={on} title={`${e.trades} / ${fmtR(e.total_r)}`}>
        <span className="num">{e.trades}</span> · <span className={`num ${signClass(e.total_r)}`}>{fmtR(e.total_r)}</span>
        <span className={`num block text-[11px] ${signClass(e.account_return)}`}>{e.trades ? fmtPct(e.account_return) : ""}</span>
      </button>
    </td>
  );
}

export function S7Trades() {
  const { t } = useI18n();
  const [period, setPeriod] = useState<string>("forward");
  const [model, setModel] = useState("s7_trend_break_fib");
  const load = useLoad(() => api.s7Trades(period, model), [period, model]);
  const index = useLoad(() => api.s7TradesIndex(), []);
  const overview = useLoad(() => api.s7TradesOverview(), []);
  const periodLabel: Record<string, string> = { development: t("s7tDev"), validation: t("s7tVal"), forward: t("s7tFwd") };
  const byKey = useMemo(() => Object.fromEntries((index.data?.entries ?? []).map((e) => [`${e.model}|${e.period}`, e])), [index.data]);
  const labelsLoad = useLoad(() => api.s7TradeLabels(), []);
  const [labels, setLabels] = useState<Record<string, S7TradeLabel>>({});
  const [filter, setFilter] = useState<Filter>("all");
  const [id, setId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  useEffect(() => setLabels(labelsLoad.data?.labels ?? {}), [labelsLoad.data]);
  useEffect(() => { setId(null); setFilter("all"); }, [period, model]);

  const all = load.data?.trades ?? [];
  const sum = load.data?.summary ?? null;
  const shown = useMemo(() => all.filter((x) => {
    if (filter === "wins") return x.pnl_usd > 0;
    if (filter === "losses") return x.pnl_usd <= 0;
    if (filter === "unmarked") return !labels[x.id];
    if (filter === "wrong") return labels[x.id]?.verdict === "wrong";
    return true;
  }), [all, filter, labels]);
  const idx = Math.max(0, shown.findIndex((x) => x.id === id));
  const tr: S7Trade | undefined = shown[idx];
  useEffect(() => setNote(tr ? labels[tr.id]?.note ?? "" : ""), [tr?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const curve = useMemo(() => [sum?.account.start_equity ?? 1000, ...all.map((x) => x.equity_after)], [all, sum]);
  const marked = all.filter((x) => labels[x.id]).length;
  const counts = { ok: 0, wrong: 0, unsure: 0 };
  for (const x of all) if (labels[x.id]) counts[labels[x.id].verdict] += 1;

  const step = useCallback((d: number) => {
    if (shown.length === 0) return;
    setId(shown[Math.min(shown.length - 1, Math.max(0, idx + d))].id);
  }, [shown, idx]);

  const save = useCallback(async (verdict: Verdict, advance = true) => {
    if (!tr || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      await api.s7TradeLabel(tr.id, verdict, note);
      setLabels((l) => ({ ...l, [tr.id]: { verdict, note, at_ms: Date.now() } }));
      if (advance && filter !== "unmarked") step(1);
    } catch (e) {  // never fail silently: the owner must see that a verdict was not stored
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [tr, note, saving, step, filter]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (["TEXTAREA", "INPUT", "SELECT"].includes((e.target as HTMLElement).tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.code;  // physical keys: the same on a Russian layout
      if (k === "KeyY") void save("ok");
      else if (k === "KeyN") void save("wrong");
      else if (k === "KeyU") void save("unsure");
      else if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, step]);

  const filters: [Filter, string][] = [["all", t("s7tFilterAll")], ["wins", t("s7tFilterWins")], ["losses", t("s7tFilterLosses")], ["unmarked", t("s7tFilterUnmarked")], ["wrong", t("s7tFilterWrong")]];
  const current = tr ? labels[tr.id]?.verdict : undefined;
  const verdictBtn = (v: Verdict, label: string, key: string, color: string) => (
    <button className={`btn ${current === v ? "selected" : ""}`} style={{ borderColor: color }} onClick={() => save(v)} disabled={saving} aria-pressed={current === v}>
      {label} <kbd>{key}</kbd>
    </button>
  );

  return (
    <>
      <PageTitle sub={t("s7tHelpAll")}>{t("nav_s7trades")}</PageTitle>

      <Card title={`${t("s7tAllModels")} · ${marketName()}`}>
        {index.data && index.data.entries.length === 0 && <Empty>{t("s7tEmpty")}</Empty>}
        {(index.data?.entries.length ?? 0) > 0 && (
          <div className="overflow-x-auto">
            <table className="s7-table">
              <thead><tr><th>{t("s7tModel")}</th>{PERIODS.map((p) => <th key={p}>{periodLabel[p]}</th>)}</tr></thead>
              <tbody>
                {S7_MODELS.map(([m, label]) => (
                  <tr key={m}>
                    <th scope="row">{label}</th>
                    {PERIODS.map((p) => <Cell key={p} e={byKey[`${m}|${p}`]} on={m === model && p === period} onClick={() => { setModel(m); setPeriod(p); }} />)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs faint">{t("s7tCellHelp")}</p>
      </Card>

      <div className="my-5 flex flex-wrap items-center gap-2">
        <div className="seg" role="group" aria-label={t("s7tModel")}>
          {S7_MODELS.map(([k, label]) => (
            <button key={k} className={k === model ? "on" : ""} aria-pressed={k === model} onClick={() => setModel(k)}>{label}</button>
          ))}
        </div>
        <div className="seg" role="group" aria-label={t("nav_s7trades")}>
          {PERIODS.map((k) => (
            <button key={k} className={k === period ? "on" : ""} aria-pressed={k === period} onClick={() => setPeriod(k)}>{periodLabel[k]}</button>
          ))}
        </div>
        {all.length > 0 && (
          <>
            <Chip tone="gold">{marked} / {all.length} {t("s7tMarked")}</Chip>
            <Chip tone="up">{t("s7tMarkOk")}: {counts.ok}</Chip>
            <Chip tone="down">{t("s7tMarkWrong")}: {counts.wrong}</Chip>
            <Chip>{t("s7tMarkUnsure")}: {counts.unsure}</Chip>
          </>
        )}
      </div>
      {load.error && !load.data && <ErrorBox error={load.error} onRetry={load.reload} />}
      {load.loading && !load.data && <Skeleton h={460} />}
      {load.data && all.length === 0 && <Empty>{t("s7tEmpty")}</Empty>}
      {sum && all.length > 0 && (
        <div className="mb-4 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <Card>
            <div className="grid grid-cols-2 gap-5">
              <Stat label={t("s7tAccount")} value={<span className={signClass(sum.account.return)}>{usd(sum.account.final_equity)}</span>} sub={fmtPct(sum.account.return)} />
              <Stat label={t("s7tTrades")} value={sum.account.trades} sub={sum.account.skipped ? `skipped ${sum.account.skipped}` : undefined} />
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
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="grid min-w-0 content-start gap-4">
            {tr ? (
              <Card
                title={<span className="flex items-center gap-2"><SidePill side={tr.side} /><span className="num">{fmtTime(tr.entry_time_ms)}</span><span className="faint num">#{tr.n}</span></span>}
                right={<span className={`num text-base font-semibold ${signClass(tr.pnl_usd)}`}>{usd(tr.pnl_usd)} · {fmtR(tr.net_r)}</span>}
              >
                <TradeChart tr={tr} />
                <p className="mt-2 text-xs faint">{t("s7tLegend")}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <span className="muted">{t("s7tZones")}:</span>
                  {(tr.smc_zones ?? []).length === 0 && <span className="faint">{t("s7tNoZones")}</span>}
                  {(tr.smc_zones ?? []).map((z, k) => {
                    const st = ZONE_STYLE[z.kind] ?? ZONE_STYLE.level;
                    return <span key={k} className="chip num" style={{ borderColor: st.color, color: st.color }}>{st.label} {fmtPrice(z.low, tr.entry)}{z.high !== z.low ? `–${fmtPrice(z.high, tr.entry)}` : ""}</span>;
                  })}
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
                  <dt className="muted">{t("s7tEntry")}</dt><dd className="num">{fmtPrice(tr.entry)}</dd>
                  <dt className="muted">{t("s7tStop")}</dt><dd className="num">{fmtPrice(tr.stop, tr.entry)}</dd>
                  <dt className="muted">{t("s7tSize")}</dt><dd className="num">{tradeSize(tr)}</dd>
                  <dt className="muted">{t("s7tExit")}</dt><dd className="num">{fmtTime(tr.exit_time_ms)} · {tr.exit_reasons.join(", ")}</dd>
                </dl>
              </Card>
            ) : (
              <Empty>{t("s7tNoneInFilter")}</Empty>
            )}
            {tr && (
              <Card title={t("s7tVerdict")}>
                <div className="grid grid-cols-3 gap-2">
                  {verdictBtn("ok", t("s7tMarkOk"), "Y", "var(--up)")}
                  {verdictBtn("wrong", t("s7tMarkWrong"), "N", "var(--down)")}
                  {verdictBtn("unsure", t("s7tMarkUnsure"), "U", "var(--border)")}
                </div>
                {saveError && <p role="alert" className="mt-3 text-sm down">{t("s7tSaveFailed")} ({saveError})</p>}
                <label className="mt-3 grid gap-1 text-sm">{t("notes")}<textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("s7tNotePh")} /></label>
                <div className="mt-3 flex flex-wrap justify-between gap-2">
                  <button className="btn" onClick={() => step(-1)} disabled={idx === 0}>← {t("tourPrev")}</button>
                  {current && <button className="btn" onClick={() => save(current, false)} disabled={saving}>{t("s7tSave")}</button>}
                  <button className="btn" onClick={() => step(1)} disabled={idx >= shown.length - 1}>{t("tourNext")} →</button>
                </div>
              </Card>
            )}
          </div>
          <Card title={`${t("s7tList")} (${shown.length})`}>
            <div className="mb-3 flex flex-wrap gap-1">
              {filters.map(([k, label]) => <button key={k} className={`btn sm ${filter === k ? "primary" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>)}
            </div>
            <div className="max-h-[760px] overflow-y-auto" role="listbox" aria-label={t("s7tList")}>
              {shown.map((x) => {
                const lab = labels[x.id]?.verdict;
                return (
                  <button key={x.id} role="option" aria-selected={x.id === tr?.id} onClick={() => setId(x.id)} className={`trade-row ${x.id === tr?.id ? "on" : ""}`}>
                    <span className="num faint w-8">{x.n}</span>
                    <span className={`vdot ${lab ?? ""}`} aria-label={lab ?? "not marked"} />
                    <span className="num">{fmtTime(x.entry_time_ms).slice(0, 10)}</span>
                    <span className={x.side === 1 ? "up" : "down"}>{x.side === 1 ? "L" : "S"}</span>
                    <span className={`num ml-auto ${signClass(x.pnl_usd)}`}>{usd(x.pnl_usd)}</span>
                    <span className="num faint w-20 text-right">{usd(x.equity_after)}</span>
                  </button>
                );
              })}
            </div>
          </Card>
        </div>
      )}

      <div className="mt-5">
        <Card title={`${t("s7tAllMarkets")} · ${S7_MODELS.find(([m]) => m === model)?.[1] ?? model}`}>
          <div className="overflow-x-auto">
            <table className="s7-table">
              <thead><tr><th>{t("market")}</th>{PERIODS.map((p) => <th key={p}>{periodLabel[p]}</th>)}</tr></thead>
              <tbody>
                {(overview.data?.markets ?? []).map((mk) => {
                  const e = Object.fromEntries(mk.entries.filter((x) => x.model === model).map((x) => [x.period, x]));
                  const here = mk.id === getMarket();
                  return (
                    <tr key={mk.id} className={here ? "here" : ""}>
                      <th scope="row">{mk.label.replace(/\s*\(.*\)$/, "")}</th>
                      {PERIODS.map((p) => <Cell key={p} e={e[p]} on={here && p === period} onClick={() => { if (here) setPeriod(p); else { setMarketId(mk.id); window.location.reload(); } }} />)}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs faint">{t("s7tMarketsHelp")}</p>
        </Card>
      </div>
    </>
  );
}
