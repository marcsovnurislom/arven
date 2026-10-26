import { useEffect, useMemo, useState } from "react";
import { api, getMarket, marketName, type EventHorizonStats, type EventType, type Events as EventsData } from "../api";
import { useI18n, type Key, type Lang } from "../i18n";
import { useLoad, useNow } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, Skeleton, until } from "../ui";

const TYPES: EventType[] = ["FOMC", "CPI", "NFP"];
const HORIZON_KEY: Record<string, Key> = { "15": "evH15", "60": "evH60", "240": "evH240" };

const pct = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? "—" : `${x.toFixed(d)} %`);

function when(ms: number, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === "ru" ? "ru-RU" : "en-GB", { weekday: "short", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }).format(ms);
}

function date(ms: number, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === "ru" ? "ru-RU" : "en-GB", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }).format(ms);
}

/** "5 : 03 : 12 : 40" - days, hours, minutes, seconds. */
function Clock({ ms }: { ms: number }) {
  const { t } = useI18n();
  const s = Math.max(0, Math.floor(ms / 1000));
  const parts: [number, Key][] = [[Math.floor(s / 86400), "evDays"], [Math.floor((s % 86400) / 3600), "evHours"], [Math.floor((s % 3600) / 60), "evMinutes"], [s % 60, "evSeconds"]];
  return (
    <div className="ev-clock" role="timer" aria-live="off">
      {parts.map(([v, k]) => (
        <div key={k} className="ev-clock-cell">
          <span className="num ev-clock-num">{String(v).padStart(2, "0")}</span>
          <span className="ev-clock-unit">{t(k)}</span>
        </div>
      ))}
    </div>
  );
}

/** Event hour vs an ordinary day at the same hour, as two bars on one scale. */
function Compare({ h, s, scale }: { h: string; s: EventHorizonStats; scale: number }) {
  const { t } = useI18n();
  if (!s.n) return <div className="text-sm muted">{t(HORIZON_KEY[h])}: {t("evNoHistory")}</div>;
  const w = (x: number | null | undefined) => `${Math.max(2, Math.min(100, ((x ?? 0) / scale) * 100))}%`;
  return (
    <div className="ev-compare">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">{t(HORIZON_KEY[h])}</span>
        {s.median_ratio != null && <span className="num text-sm gold">×{s.median_ratio.toFixed(1)} {t("evVsUsual")}</span>}
      </div>
      <div className="ev-bar-row"><span className="ev-bar-label">{t("evAfter")}</span><span className="ev-bar"><span className="ev-bar-fill event" style={{ width: w(s.median_range) }} /></span><span className="num ev-bar-val">{pct(s.median_range)}</span></div>
      <div className="ev-bar-row"><span className="ev-bar-label">{t("evUsual")}</span><span className="ev-bar"><span className="ev-bar-fill usual" style={{ width: w(s.median_baseline) }} /></span><span className="num ev-bar-val">{pct(s.median_baseline)}</span></div>
      <div className="mt-1 text-xs faint">
        {t("evMax")} {pct(s.max_range)} · {t("evMoreOften")} {s.share_above_baseline != null ? `${Math.round(s.share_above_baseline * 100)} %` : "—"} · {s.n} {t("evReleases")}
      </div>
    </div>
  );
}

export function Events() {
  const { t, lang } = useI18n();
  const ev = useLoad(api.events, [], 10 * 60_000);
  const now = useNow(1000);
  const data: EventsData | null = ev.data;
  const next = data?.upcoming.find((e) => e.time_ms > now) ?? null;
  const [picked, setPicked] = useState<EventType | null>(null);
  const typ: EventType = picked ?? next?.type ?? "FOMC";
  const reload = ev.reload;
  const passed = next === null && (data?.upcoming.length ?? 0) > 0;
  useEffect(() => { if (passed) reload(); }, [passed]); // eslint-disable-line react-hooks/exhaustive-deps
  const market = getMarket() === "gold" ? t("evGold") : marketName();
  const sum = data?.summary[typ] ?? {};
  const scale = useMemo(() => Math.max(0.01, ...Object.values(sum).flatMap((s) => [s.median_range ?? 0, s.median_baseline ?? 0])), [sum]);
  const recent = (data?.recent ?? []).filter((r) => r.type === typ).slice(-8).reverse();
  const known = data ? TYPES.map((k) => [k, data.known_until[k]] as const) : [];

  return (
    <>
      <PageTitle sub={t("evSub")}>{t("nav_events")}</PageTitle>
      {ev.error && !data && <ErrorBox error={ev.error} onRetry={reload} />}
      {ev.loading && !data && <Skeleton h={300} />}
      {data && (
        <>
          <div className="mb-4 grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <Card title={t("evNext")}>
              {next ? (
                <div className="ev-hero">
                  <Chip tone="gold">{next.type}</Chip>
                  <h2 className="mt-2 text-2xl font-semibold">{t(`evName_${next.type}` as Key)}</h2>
                  <p className="mt-1 text-sm muted">{when(next.time_ms, lang)} · <span className="num">{new Date(next.time_ms).toISOString().slice(11, 16)} UTC</span></p>
                  <Clock ms={next.time_ms - now} />
                  <p className="mt-3 max-w-xl text-sm muted">{t(`evWhat_${next.type}` as Key)}</p>
                  {next.note && <p className="mt-1 text-xs faint">{next.note}</p>}
                </div>
              ) : <Empty>{t("evNone")}</Empty>}
            </Card>
            <Card title={t("evUpcoming")}>
              <div className="grid gap-2">
                {data.upcoming.filter((e) => e.time_ms > now).slice(1).map((e) => (
                  <div key={`${e.type}${e.time_ms}`} className="session-row">
                    <Chip tone={e.type === "FOMC" ? "gold" : ""}>{e.type}</Chip>
                    <span className="min-w-0">
                      <span className="block text-sm">{t(`evName_${e.type}` as Key)}</span>
                      <span className="block text-xs faint">{when(e.time_ms, lang)}</span>
                    </span>
                    <span className="num ml-auto whitespace-nowrap text-xs muted">{until(e.time_ms - now, lang)}</span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs faint">
                {t("evKnownUntil")}: {known.map(([k, v]) => `${k} ${v ? date(v, lang) : "—"}`).join(", ")}. {t("evKnownNote")}
              </p>
            </Card>
          </div>

          <Card
            title={`${t("evHistory")} · ${market}`}
            right={
              <div className="seg" role="group" aria-label={t("evType")}>
                {TYPES.map((k) => <button key={k} className={k === typ ? "on" : ""} aria-pressed={k === typ} onClick={() => setPicked(k)}>{k}</button>)}
              </div>
            }
          >
            <p className="mb-4 max-w-3xl text-sm muted">{t("evHistoryHelp").replace("{n}", String(data.baseline_days))}</p>
            {data.measured === 0 ? <Empty>{t("evNoData")}</Empty> : (
              <div className="grid gap-5 md:grid-cols-3">
                {data.horizons_min.map((h) => <Compare key={h} h={String(h)} s={sum[String(h)] ?? { n: 0 }} scale={scale} />)}
              </div>
            )}
            {recent.length > 0 && (
              <div className="mt-6 overflow-x-auto">
                <h3 className="mb-2 text-sm font-medium muted">{t("evRecent")} {typ}</h3>
                <table>
                  <thead><tr><th>{t("evDate")}</th>{data.horizons_min.map((h) => <th key={h}>{t(HORIZON_KEY[String(h)])}</th>)}</tr></thead>
                  <tbody>
                    {recent.map((r) => (
                      <tr key={r.time_ms}>
                        <td className="num">{date(r.time_ms, lang)}{r.note && <span className="ml-1 faint" title={r.note}>*</span>}</td>
                        {data.horizons_min.map((h) => {
                          const x = r.horizons[String(h)];
                          return <td key={h} className="num">{x ? <>{pct(x.range)}{x.baseline ? <span className="faint"> / {pct(x.baseline)}</span> : null}</> : "—"}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs faint">{t("evTableNote")}</p>
              </div>
            )}
            <p className="mt-4 text-xs faint">{t("evHonesty")}{getMarket() === "gold" ? ` ${t("evGoldNote")}` : ""}</p>
          </Card>
        </>
      )}
    </>
  );
}
