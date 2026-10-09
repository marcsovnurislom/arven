import { useState } from "react";
import { api, type Overview as OverviewT } from "../api";
import { useI18n } from "../i18n";
import { useLoad, useOverviewStream } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, Skeleton, Stat, fmt, fmtPct, fmtR, signClass, fmtTime } from "../ui";

export function Overview() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useLoad(api.overview, [], 15000);
  const [live, setLive] = useState<OverviewT | null>(null);
  const connected = useOverviewStream<OverviewT>(setLive);
  const o = live ?? data;
  const sum = o?.strategies_summary ?? null;

  return (
    <>
      <PageTitle sub={t("appTagline")}>{t("nav_overview")}</PageTitle>
      {error && !o && <ErrorBox error={error} onRetry={reload} />}
      {loading && !o && <div className="grid gap-4 sm:grid-cols-3"><Skeleton h={110} /><Skeleton h={110} /><Skeleton h={110} /></div>}
      {o && (
        <div className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Card>
              <Stat
                label={t("dataAge")}
                value={o.data_age_seconds === null ? "n/a" : `${Math.round(o.data_age_seconds)} s`}
                tone={o.data_stale ? "down" : "up"}
                sub={o.data_stale ? t("stale") : t("fresh")}
              />
            </Card>
            <Card>
              <Stat
                label={t("runtime")}
                value={!o.runtime.present ? "—" : o.runtime.stale ? "!" : "OK"}
                tone={!o.runtime.present || o.runtime.stale ? "down" : "up"}
                sub={!o.runtime.present ? t("runtimeNone") : o.runtime.stale ? t("runtimeStale") : t("runtimeOk")}
              />
            </Card>
            <Card><Stat label={t("openSignals")} value={o.signals_open} sub={`${t("total")}: ${o.signals_total}`} /></Card>
            <Card><Stat label={t("last24h")} value={o.signals_last_24h} sub={<Chip tone={connected ? "up" : ""}>{connected ? t("live") : t("polling")}</Chip>} /></Card>
          </div>

          <Card title={t("forward")} right={sum && <span className="text-xs faint num">{fmtTime(sum.data_through_ms)}</span>}>
            {!sum ? (
              <Empty>{t("emptySignals")}</Empty>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table>
                    <thead>
                      <tr><th>Strategy</th><th>#</th><th>{t("closed")}</th><th>{t("winRate")}</th><th>{t("meanR")}</th><th>{t("totalR")}</th><th>{t("perWeek")}</th></tr>
                    </thead>
                    <tbody>
                      {Object.entries(sum.strategies).map(([sid, s]) => (
                        <tr key={sid}>
                          <td className="num">{sid}</td>
                          <td className="num">{s.signals}</td>
                          <td className="num">{s.closed}</td>
                          <td className="num">{fmtPct(s.win_rate)}</td>
                          <td className={`num ${signClass(s.mean_r)}`}>{fmtR(s.mean_r)}</td>
                          <td className={`num ${signClass(s.total_r)}`}>{fmtR(s.total_r)}</td>
                          <td className="num">{fmt(s.signals_per_week, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-3 text-sm" style={{ color: "var(--warn)" }}>{t("sampleWarn")}</p>
                <p className="mt-1 text-xs faint">{t("breakeven")}</p>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div>
                    <div className="text-xs uppercase tracking-wider faint">{t("agreement")}</div>
                    <p className="mt-1 text-xs muted">{t("agreementHelp")}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <Stat label={t("alone")} value={fmtR(sum.agreement_hypothesis.alone.mean_r)} tone={signClass(sum.agreement_hypothesis.alone.mean_r)} sub={`n=${sum.agreement_hypothesis.alone.n}`} />
                    <Stat label={t("agreed")} value={fmtR(sum.agreement_hypothesis.agreed_by_another_strategy.mean_r)} tone={signClass(sum.agreement_hypothesis.agreed_by_another_strategy.mean_r)} sub={`n=${sum.agreement_hypothesis.agreed_by_another_strategy.n}`} />
                  </div>
                </div>
              </>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
