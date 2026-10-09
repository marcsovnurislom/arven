import { api } from "../api";
import { useI18n } from "../i18n";
import { useLoad } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, Skeleton, fmtPct, signClass } from "../ui";

export function Lab() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useLoad(api.research, [], 60000);
  return (
    <>
      <PageTitle sub={t("lab")}>{t("nav_lab")}</PageTitle>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Skeleton h={220} />}
      {data && data.runs.length === 0 && <Empty>{t("emptyRuns")}</Empty>}
      {data && data.runs.length > 0 && (
        <Card>
          <div className="overflow-x-auto">
            <table>
              <thead><tr><th>Kind</th><th>Run</th><th>Period</th><th>Return</th><th>Max DD</th><th>Trades</th><th>{t("sealed")}</th><th>Hash</th></tr></thead>
              <tbody>
                {data.runs.map((r) => (
                  <tr key={`${r.kind}-${r.run_id}`}>
                    <td><Chip>{r.kind}</Chip></td>
                    <td className="num">{r.run_id}</td>
                    <td>{r.period ?? "—"}{r.stress ? " (stress)" : ""}</td>
                    <td className={`num ${signClass(r.total_return)}`}>{fmtPct(r.total_return)}</td>
                    <td className="num">{fmtPct(r.max_drawdown)}</td>
                    <td className="num">{r.n_trades ?? "—"}</td>
                    <td>{r.touched_test_set === null ? "—" : <Chip tone={r.touched_test_set ? "down" : "up"}>{r.touched_test_set ? t("touched") : t("untouched")}</Chip>}</td>
                    <td className="num faint">{r.result_hash ? r.result_hash.slice(0, 10) : "—"}{r.git_dirty ? " *" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs faint">* = produced from a working tree with uncommitted changes.</p>
        </Card>
      )}
    </>
  );
}
