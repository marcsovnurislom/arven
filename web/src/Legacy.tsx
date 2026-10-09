import { api } from "./api";
import { Bar } from "./Charts2";
import { Tilt } from "./fx";
import { useLoad } from "./hooks";
import { useI18n } from "./i18n";
import { Chip, fmtPct, signClass } from "./ui";

/** S1-S3 (trend_momentum, breakout, mean_reversion) run as one voting pipeline on the hourly paper run; this card shows its latest forward run. */
export function LegacyPipelineCard() {
  const { t } = useI18n();
  const { data } = useLoad(api.research, [], 120000);
  const run = data?.runs.find((r) => r.kind === "paper" && r.total_return !== null) ?? null;
  return (
    <Tilt className="rounded-2xl border p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="num text-sm">S1 + S2 + S3</span>
        <Chip>{t("legacyChip")}</Chip>
      </div>
      <div className="mt-1 text-xs muted">trend_momentum · breakout · mean_reversion</div>
      <div className={`num mt-2 text-3xl font-bold ${signClass(run?.total_return ?? null)}`}>{run ? fmtPct(run.total_return) : "n/a"}</div>
      <div className="text-xs muted">{run ? `${run.n_trades ?? "?"} ${t("closed").toLowerCase()} · ${t("legacyForward")}` : t("emptyRuns")}</div>
      <div className="mt-3 text-xs muted">{t("winRate")} {run ? fmtPct(run.win_rate) : "n/a"}</div>
      <Bar value={run?.win_rate ?? 0} color="#b48cff" />
      <p className="mt-3 text-xs faint">{t("legacyNote")}</p>
    </Tilt>
  );
}
