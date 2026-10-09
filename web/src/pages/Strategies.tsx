import { api } from "../api";
import { Reveal, Tilt } from "../fx";
import { LegacyPipelineCard } from "../Legacy";
import { useI18n } from "../i18n";
import { useLoad } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, Skeleton, fmt, fmtPct, fmtR, signClass } from "../ui";

// Static reference: the offline studies recorded in docs/ (unchanged v1 strategies). Labelled with its source on the page.
const STUDIES = [
  { id: "s1_s2_s3_pipeline", dev: "410 / -17.4%", val: "530 / -9.9%", note: "trend_momentum + breakout + mean_reversion voting; gross also negative: no edge", devPct: -17.4, valPct: -9.9 },
  { id: "s4_impulse_retest", dev: "127 / +7.7%", val: "58 / +18.3%", note: "~0 under spread stress", devPct: 7.7, valPct: 18.3 },
  { id: "s5_squeeze_breakout", dev: "208 / -26.3%", val: "97 / +1.4%", note: "weakest; no robust regime", devPct: -26.3, valPct: 1.4 },
  { id: "s6_trend_pullback", dev: "342 / +5.7%", val: "212 / +4.1%", note: "most frequent; ~-5% under stress", devPct: 5.7, valPct: 4.1 },
];

function CompareChart() {
  const { t } = useI18n();
  const W = 640, H = 260, base = 150, scale = 3.4;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={t("compareTitle")}>
      <line x1="30" x2={W - 10} y1={base} y2={base} stroke="currentColor" opacity="0.3" />
      {STUDIES.map((s, i) => {
        const x0 = 40 + i * 150;
        return [["dev", s.devPct, "#d9b256"], ["val", s.valPct, "#6aa8ff"]].map(([k, v, c], j) => {
          const val = v as number, h = Math.abs(val) * scale, x = x0 + j * 54;
          return (
            <g key={`${s.id}-${k}`}>
              <rect x={x} y={val >= 0 ? base - h : base} width="44" height={h} rx="6" fill={c as string} opacity="0.85" className="grow-y" style={{ transformOrigin: `${x}px ${base}px`, animationDelay: `${0.12 * (i * 2 + j)}s` }} />
              <text x={x + 22} y={val >= 0 ? base - h - 6 : base + h + 14} textAnchor="middle" fontSize="12" fill="currentColor" className="num">{val > 0 ? "+" : ""}{val}%</text>
              <text x={x + 22} y={H - 8} textAnchor="middle" fontSize="10" fill="currentColor" opacity="0.6">{k === "dev" ? "dev" : "val"}</text>
            </g>
          );
        });
      })}
      {STUDIES.map((s, i) => (
        <text key={s.id} x={40 + i * 150 + 49} y="20" textAnchor="middle" fontSize="12" fill="currentColor" className="num">{s.id.startsWith("s1_") ? "S1-S3" : s.id.split("_")[0].toUpperCase()}</text>
      ))}
    </svg>
  );
}

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
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <LegacyPipelineCard />
            {data.strategies.length === 0 && <Empty>{t("emptySignals")}</Empty>}
            {data.strategies.map((sid) => {
              const s = sum?.strategies[sid];
              return (
                <Tilt key={sid}><Card title={<span className="num">{sid}</span>} right={<Chip tone="gold">EXPERIMENTAL</Chip>}>
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
                </Card></Tilt>
              );
            })}
          </div>
          <Reveal>
            <Card title={t("compareTitle")}>
              <CompareChart />
              <div className="mt-2 flex gap-4 text-xs muted"><span><span className="dot mr-1" style={{ color: "#d9b256" }} />development 2020-2023</span><span><span className="dot mr-1" style={{ color: "#6aa8ff" }} />validation 2023-2025</span></div>
            </Card>
          </Reveal>
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
