import { useMemo, useState } from "react";
import { api, marketSubtitle } from "../api";
import { Suspense, lazy } from "react";
import type { ChartMarker } from "../CandleChart";
import { useI18n } from "../i18n";
import { useCandleFeed, useLoad } from "../hooks";
import { Card, ErrorBox, PageTitle, Skeleton } from "../ui";

const CandleChart = lazy(() => import("../CandleChart").then((m) => ({ default: m.CandleChart })));
const TFS = ["5m", "15m", "1h", "4h"] as const;

export function Charts() {
  const { t } = useI18n();
  const [tf, setTf] = useState<(typeof TFS)[number]>("15m");
  const feed = useCandleFeed(tf);
  const signals = useLoad(() => api.signals(undefined, 300), [], 60000);
  const markers = useMemo<ChartMarker[]>(
    () => (signals.data?.signals ?? []).map((s) => ({ timeMs: s.event_time_ms, side: s.side, text: s.strategy_id.slice(0, 2).toUpperCase() })),
    [signals.data],
  );
  return (
    <>
      <PageTitle sub={marketSubtitle()}>{t("nav_charts")}</PageTitle>
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
        {feed.error && feed.candles.length === 0 && <ErrorBox error={feed.error} />}
        {feed.loading && feed.candles.length === 0 && <Skeleton h={460} />}
        {feed.candles.length > 0 && <Suspense fallback={<Skeleton h={460} />}><CandleChart key={tf} candles={feed.candles} markers={markers} height={460} onNeedOlder={feed.loadOlder} /></Suspense>}
        <p className="mt-2 text-xs faint">{feed.exhausted ? "Start of stored history reached." : "Drag the chart to the right to load older history automatically."}</p>
      </Card>
    </>
  );
}
