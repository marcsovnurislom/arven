import { api } from "../api";
import { useI18n } from "../i18n";
import { useLoad } from "../hooks";
import { Card, Empty, ErrorBox, fmt, fmtPrice, PageTitle, signClass, Skeleton, Sparkline } from "../ui";

export function Screener() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useLoad(api.screener, [], 30000);
  return (
    <>
      <PageTitle sub={t("screenerNote")}>{t("nav_screener")}</PageTitle>
      {error && !data && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Skeleton h={120} />}
      {data && (
        <Card>
          {data.rows.length === 0 ? (
            <Empty>{t("emptyRuns")}</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table>
                <thead>
                  <tr><th>Symbol</th><th>{t("price")}</th><th>{t("change24")}</th><th>{t("volume24")}</th><th>24h</th></tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.symbol}>
                      <td className="num">{r.symbol}</td>
                      <td className="num">{fmtPrice(r.price)}</td>
                      <td className={`num ${signClass(r.change_24h_pct)}`}>{r.change_24h_pct === null ? "n/a" : `${r.change_24h_pct >= 0 ? "+" : ""}${r.change_24h_pct.toFixed(2)}%`}</td>
                      <td className="num">{fmt(r.quote_volume_24h, 0)}</td>
                      <td><Sparkline values={r.sparkline} up={(r.change_24h_pct ?? 0) >= 0} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-3 text-xs faint">{data.note}</p>
        </Card>
      )}
    </>
  );
}
