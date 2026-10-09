import { useMemo, useState } from "react";
import { api } from "../api";
import { CandleChart, type ChartMarker } from "../CandleChart";
import { useI18n } from "../i18n";
import { useLoad } from "../hooks";
import { Card, ErrorBox, PageTitle, Skeleton } from "../ui";

const TFS = ["5m", "15m", "1h", "4h"] as const;

export function Charts() {
  const { t } = useI18n();
  const [tf, setTf] = useState<(typeof TFS)[number]>("15m");
  const candles = useLoad(() => api.candles(tf, 500), [tf], 30000);
  const signals = useLoad(() => api.signals(undefined, 300), [], 60000);
  const markers = useMemo<ChartMarker[]>(
    () => (signals.data?.signals ?? []).map((s) => ({ timeMs: s.event_time_ms, side: s.side, text: s.strategy_id.slice(0, 2).toUpperCase() })),
    [signals.data],
  );
  return (
    <>
      <PageTitle sub="BTC/USDT">{t("nav_charts")}</PageTitle>
      <Card
        title={t("chartTf")}
        right={
          <div className="flex gap-1" role="group" aria-label={t("chartTf")}>
            {TFS.map((x) => (
              <button key={x} className={`btn ${x === tf ? "primary" : ""}`} aria-pressed={x === tf} onClick={() => setTf(x)}>{x}</button>
            ))}
          </div>
        }
      >
        {candles.error && !candles.data && <ErrorBox error={candles.error} onRetry={candles.reload} />}
        {candles.loading && !candles.data && <Skeleton h={460} />}
        {candles.data && <CandleChart candles={candles.data.candles} markers={markers} height={460} />}
      </Card>
    </>
  );
}
