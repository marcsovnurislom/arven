import { useState } from "react";
import { api, type Overview as OverviewT } from "../api";
import { Bar, EquityCurve, Gauge } from "../Charts2";
import { CountUp, Reveal, Tilt } from "../fx";
import { LegacyPipelineCard } from "../Legacy";
import { useI18n } from "../i18n";
import { useLoad, useOverviewStream } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, Skeleton, fmt, fmtPct, fmtR, signClass, fmtTime } from "../ui";

const COLOR: Record<string, string> = { s4_impulse_retest: "#d9b256", s5_squeeze_breakout: "#6aa8ff", s6_trend_pullback: "#34d399", s7_trend_break_fib: "#c084fc", crowded_shorts: "#f59e7a" };

export function Overview() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useLoad(api.overview, [], 15000);
  const [live, setLive] = useState<OverviewT | null>(null);
  const connected = useOverviewStream<OverviewT>(setLive);
  const o = live ?? data;
  const sum = o?.strategies_summary ?? null;
  const age = o?.data_age_seconds ?? null;
  const freshness = age === null ? 0 : Math.max(0, 1 - age / 3600);

  return (
    <>
      <PageTitle sub={t("appTagline")}>{t("nav_overview")}</PageTitle>
      {error && !o && <ErrorBox error={error} onRetry={reload} />}
      {loading && !o && <div className="grid gap-4 sm:grid-cols-3"><Skeleton h={150} /><Skeleton h={150} /><Skeleton h={150} /></div>}
      {o && (
        <div className="grid gap-5">
          <div className="stagger grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Tilt className="glass flex items-center gap-4 p-4">
              <Gauge value={freshness} label={t("freshness")} tone={o.data_stale ? "down" : "up"} />
              <div>
                <div className="text-xs uppercase tracking-wider faint">{t("dataAge")}</div>
                <div className={`num text-2xl font-semibold ${o.data_stale ? "down" : "up"}`}>{age === null ? "n/a" : <CountUp value={Math.round(age)} suffix=" s" />}</div>
                <div className="mt-1 text-xs muted">{o.data_stale ? t("stale") : t("fresh")}</div>
              </div>
            </Tilt>
            <Tilt className="glass p-4">
              <div className="text-xs uppercase tracking-wider faint">{t("runtime")}</div>
              <div className="mt-2 flex items-center gap-3">
                <span className={`dot ${o.runtime.present && !o.runtime.stale ? "ring-pulse" : ""}`} style={{ color: o.runtime.present && !o.runtime.stale ? "var(--up)" : "var(--down)", width: 14, height: 14 }} />
                <span className="num text-2xl font-semibold">{!o.runtime.present ? "—" : o.runtime.stale ? "!" : "OK"}</span>
              </div>
              <div className="mt-2 text-xs muted">{!o.runtime.present ? t("runtimeNone") : o.runtime.stale ? t("runtimeStale") : t("runtimeOk")}</div>
            </Tilt>
            <Tilt className="glass p-4">
              <div className="text-xs uppercase tracking-wider faint">{t("openSignals")}</div>
              <div className="num mt-2 text-4xl font-bold gold"><CountUp value={o.signals_open} /></div>
              <div className="mt-1 text-xs muted">{t("total")}: <CountUp value={o.signals_total} /></div>
            </Tilt>
            <Tilt className="glass p-4">
              <div className="text-xs uppercase tracking-wider faint">{t("last24h")}</div>
              <div className="num mt-2 text-4xl font-bold"><CountUp value={o.signals_last_24h} /></div>
              <div className="mt-1"><Chip tone={connected ? "up" : ""}>{connected ? t("live") : t("polling")}</Chip></div>
            </Tilt>
          </div>

          <Reveal>
            <Card title={t("equityTitle")} right={sum && <span className="text-xs faint num">{fmtTime(sum.data_through_ms)}</span>}>
              {sum?.trades ? <EquityCurve trades={sum.trades} /> : <Empty>{t("noClosed")}</Empty>}
              <p className="mt-3 text-xs faint">{t("equityHelp")}</p>
            </Card>
          </Reveal>

          <Reveal>
            <Card title={t("forward")}>
              {!sum ? (
                <Empty>{t("emptySignals")}</Empty>
              ) : (
                <>
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                    <LegacyPipelineCard />
                    {Object.entries(sum.strategies).map(([sid, s]) => (
                      <Tilt key={sid} className="rounded-2xl border p-4" >
                        <div className="flex items-center gap-2"><span className="dot" style={{ color: COLOR[sid] ?? "var(--muted)" }} /><span className="num text-sm">{sid}</span></div>
                        <div className={`num mt-2 text-3xl font-bold ${signClass(s.mean_r)}`}>{fmtR(s.mean_r)}</div>
                        <div className="text-xs muted">{t("meanR")} · {s.closed} {t("closed").toLowerCase()} · {fmt(s.signals_per_week, 1)} {t("perWeek")}</div>
                        <div className="mt-3 text-xs muted">{t("winRate")} {fmtPct(s.win_rate)}</div>
                        <Bar value={s.win_rate ?? 0} color={COLOR[sid]} />
                      </Tilt>
                    ))}
                  </div>
                  <p className="mt-4 text-sm" style={{ color: "var(--warn)" }}>{t("sampleWarn")}</p>
                  <p className="mt-1 text-xs faint">{t("breakeven")}</p>
                  <div className="mt-5 grid gap-3 sm:grid-cols-2">
                    <div>
                      <div className="text-xs uppercase tracking-wider faint">{t("agreement")}</div>
                      <p className="mt-1 text-xs muted">{t("agreementHelp")}</p>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div><div className="text-xs faint">{t("alone")} (n={sum.agreement_hypothesis.alone.n})</div><div className={`num text-2xl font-bold ${signClass(sum.agreement_hypothesis.alone.mean_r)}`}>{fmtR(sum.agreement_hypothesis.alone.mean_r)}</div></div>
                      <div><div className="text-xs faint">{t("agreed")} (n={sum.agreement_hypothesis.agreed_by_another_strategy.n})</div><div className={`num text-2xl font-bold ${signClass(sum.agreement_hypothesis.agreed_by_another_strategy.mean_r)}`}>{fmtR(sum.agreement_hypothesis.agreed_by_another_strategy.mean_r)}</div></div>
                    </div>
                  </div>
                </>
              )}
            </Card>
          </Reveal>
        </div>
      )}
    </>
  );
}
