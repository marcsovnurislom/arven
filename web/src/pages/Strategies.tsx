import { api } from "../api";
import { useI18n } from "../i18n";
import { useLoad } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, Skeleton, fmt, fmtPct, fmtR, signClass } from "../ui";

// Static reference: the offline studies recorded in docs/ (unchanged v1 strategies). Labelled with its source on the page.
const STUDIES = [
  { id: "s4_impulse_retest", dev: "127 / +7.7%", val: "58 / +18.3%", note: "~0 under spread stress" },
  { id: "s5_squeeze_breakout", dev: "208 / -26.3%", val: "97 / +1.4%", note: "weakest; no robust regime" },
  { id: "s6_trend_pullback", dev: "342 / +5.7%", val: "212 / +4.1%", note: "most frequent; ~-5% under stress" },
];

export function Strategies() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useLoad(api.strategies, [], 60000);
  const sum = data?.forward_summary ?? null;
  return (
    <>
      <PageTitle sub={t("honesty")}>{t("nav_strategies")}</PageTitle>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Skeleton h={160} />}
      {data && (
        <div className="grid gap-4">
          <div className="grid gap-4 md:grid-cols-3">
            {data.strategies.length === 0 && <Empty>{t("emptySignals")}</Empty>}
            {data.strategies.map((sid) => {
              const s = sum?.strategies[sid];
              return (
                <Card key={sid} title={<span className="num">{sid}</span>} right={<Chip tone="gold">EXPERIMENTAL</Chip>}>
                  {!s ? <span className="muted">—</span> : (
                    <dl className="grid grid-cols-2 gap-2 text-sm">
                      <dt className="muted">{t("total")}</dt><dd className="num text-right">{s.signals}</dd>
                      <dt className="muted">{t("closed")}</dt><dd className="num text-right">{s.closed}</dd>
                      <dt className="muted">{t("winRate")}</dt><dd className="num text-right">{fmtPct(s.win_rate)}</dd>
                      <dt className="muted">{t("meanR")}</dt><dd className={`num text-right ${signClass(s.mean_r)}`}>{fmtR(s.mean_r)}</dd>
                      <dt className="muted">{t("totalR")}</dt><dd className={`num text-right ${signClass(s.total_r)}`}>{fmtR(s.total_r)}</dd>
                      <dt className="muted">{t("perWeek")}</dt><dd className="num text-right">{fmt(s.signals_per_week, 1)}</dd>
                    </dl>
                  )}
                  {s && s.closed < 100 && <p className="mt-3 text-xs" style={{ color: "var(--warn)" }}>{t("sampleWarn")}</p>}
                </Card>
              );
            })}
          </div>
          <Card title={t("verified")}>
            <div className="overflow-x-auto">
              <table>
                <thead><tr><th>Strategy</th><th>Development (trades / return, CFD)</th><th>Validation (trades / return, CFD)</th><th>Note</th></tr></thead>
                <tbody>
                  {STUDIES.map((r) => <tr key={r.id}><td className="num">{r.id}</td><td className="num">{r.dev}</td><td className="num">{r.val}</td><td className="muted">{r.note}</td></tr>)}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs faint">{t("verifiedSrc")}</p>
            <p className="mt-1 text-xs faint">{t("breakeven")}</p>
          </Card>
        </div>
      )}
    </>
  );
}
