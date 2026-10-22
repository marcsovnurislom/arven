import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { api, getMarket, type Activity, type CentreSession, type MarketSession } from "../api";
import { useI18n, type Lang } from "../i18n";
import { useLoad, useNow } from "../hooks";
import { Card, Chip, ErrorBox, PageTitle, Skeleton, fmtTime, until } from "../ui";

const Globe = lazy(() => import("../Globe").then((m) => ({ default: m.Globe })));

const RU_CENTRES: Record<string, string> = { sydney: "Сидней", tokyo: "Токио", london: "Лондон", new_york: "Нью-Йорк" };
const RU_HOLIDAYS: Record<string, string> = {
  "New Year's Day": "Новый год", "Martin Luther King Jr. Day": "День Мартина Лютера Кинга", "Presidents' Day": "День президентов",
  "Good Friday": "Страстная пятница", "Memorial Day": "День памяти", Juneteenth: "Джунтинс", "Independence Day": "День независимости США",
  "Labor Day": "День труда", Thanksgiving: "День благодарения", "Day after Thanksgiving": "День после Дня благодарения", Christmas: "Рождество",
};

function localClock(tz: string, now: number, lang: Lang): string {
  try {
    return new Intl.DateTimeFormat(lang === "ru" ? "ru-RU" : "en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", weekday: "short" }).format(now);
  } catch {
    return "";
  }
}

export function Sessions() {
  const { t, lang } = useI18n();
  const sessions = useLoad(api.sessions, [], 60_000);
  const now = useNow(1000);
  const data = sessions.data;
  // a countdown that reached zero means the state changed: ask the server again (once per change)
  const due = data ? Math.min(...[...data.markets.map((m) => m.next_change_ms ?? Infinity), ...data.centres.map((c) => c.next_change_ms)]) : Infinity;
  const passed = now >= due + 1500;
  const reload = sessions.reload;
  useEffect(() => { if (passed) reload(); }, [passed]); // eslint-disable-line react-hooks/exhaustive-deps
  const name = (c: CentreSession) => (lang === "ru" ? RU_CENTRES[c.id] ?? c.name : c.name);
  const centres = useMemo(() => (data?.centres ?? []).map((c) => ({ id: c.id, name: lang === "ru" ? RU_CENTRES[c.id] ?? c.name : c.name, lat: c.lat, lon: c.lon, open: c.open })), [data, lang]);
  const openNames = centres.filter((c) => c.open).map((c) => c.name);
  const globeLabel = `${t("sesGlobe")}: ${openNames.length ? openNames.join(", ") : t("sesNoneOpen")}`;

  return (
    <>
      <PageTitle sub={t("sesSub")}>{t("nav_sessions")}</PageTitle>
      {sessions.error && !data && <ErrorBox error={sessions.error} onRetry={reload} />}
      {sessions.loading && !data && <Skeleton h={420} />}
      {data && (
        <div className="mb-4 grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
          <Card title={t("sesGlobe")} right={<span className="text-xs faint">{t("sesDragHint")}</span>}>
            <div className="globe-wrap">
              <Suspense fallback={<Skeleton h={360} />}><Globe centres={centres} nowMs={now} label={globeLabel} /></Suspense>
            </div>
            <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs muted">
              <span><span className="globe-key" style={{ background: "var(--up)" }} />{t("sesCentreOpen")}</span>
              <span><span className="globe-key" style={{ background: "var(--faint)" }} />{t("sesCentreClosed")}</span>
              <span><span className="globe-key" style={{ background: "#f0d68c" }} />{t("sesDay")}</span>
              <span><span className="globe-key" style={{ background: "#788caf" }} />{t("sesNight")}</span>
            </div>
          </Card>
          <div className="grid content-start gap-4">
            <Card title={t("sesMarkets")}>
              <div className="grid gap-3">{data.markets.map((m) => <MarketRow key={m.id} m={m} now={now} />)}</div>
            </Card>
            <Card title={t("sesCentres")}>
              <div className="grid gap-2">
                {data.centres.map((c) => (
                  <div key={c.id} className="session-row">
                    <span className={`dot ${c.open ? "on" : ""}`} aria-hidden="true" />
                    <span className="min-w-0">
                      <span className="block font-medium">{name(c)}</span>
                      <span className="num block whitespace-nowrap text-xs faint">{localClock(c.tz, now, lang)} · {c.open_local}–{c.close_local}</span>
                    </span>
                    <span className="ml-auto text-right text-xs">
                      <Chip tone={c.open ? "up" : ""}>{c.open ? t("sesCentreOpen") : t("sesCentreClosed")}</Chip>
                      <span className="num mt-1 block faint">{c.open ? t("sesClosesIn") : t("sesOpensIn")} {until(c.next_change_ms - now, lang)}</span>
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs faint">{t("sesCentresNote")}</p>
            </Card>
          </div>
        </div>
      )}
      <Heatmap now={now} />
    </>
  );
}

function MarketRow({ m, now }: { m: MarketSession; now: number }) {
  const { t, lang } = useI18n();
  const title = m.id === "btc" ? "BTC" : m.id === "gold" ? (lang === "ru" ? "Золото" : "Gold") : m.label;
  const holiday = (r: string) => (lang === "ru" ? RU_HOLIDAYS[r] ?? r : r);
  const stateLabel = { always_open: t("sesAlways"), open: t("sesOpen"), halt: t("sesHalt"), weekend: t("sesWeekend"), holiday: t("sesHoliday") }[m.state];
  return (
    <div className="session-row">
      <span className={`dot ${m.open ? "on" : ""}`} aria-hidden="true" />
      <span className="min-w-0">
        <span className="block font-semibold">{title}</span>
        <span className="block text-xs faint">{m.label}</span>
        {m.next_holiday && m.state !== "holiday" && (
          <span className="mt-1 block text-xs muted">{t("sesNextHoliday")}: {holiday(m.next_holiday.reason)}, {fmtTime(m.next_holiday.start_ms)}</span>
        )}
      </span>
      <span className="ml-auto text-right text-xs">
        <Chip tone={m.open ? "up" : m.state === "halt" ? "warn" : "down"}>{stateLabel}{m.reason ? ` · ${holiday(m.reason)}` : ""}</Chip>
        {m.next_change_ms !== null && (
          <span className="num mt-1 block faint">{m.open ? t("sesClosesIn") : t("sesOpensIn")} {until(m.next_change_ms - now, lang)}</span>
        )}
      </span>
    </div>
  );
}

function Heatmap({ now }: { now: number }) {
  const { t, lang } = useI18n();
  const act = useLoad(api.activity, [], 0);
  const [local, setLocal] = useState(true);
  const offH = local ? -Math.round(new Date(now).getTimezoneOffset() / 60) : 0;
  const days = t("sesDays").split(",");
  const a: Activity | null = act.data;
  // shift the UTC week by the viewer's whole-hour offset: slot k (Monday 00:00 UTC = 0) moves to k + offH
  const cells = useMemo(() => {
    const out: { v: number | null; n: number; utc: number }[] = Array.from({ length: 168 }, () => ({ v: null, n: 0, utc: 0 }));
    if (!a) return out;
    for (let k = 0; k < 168; k++) out[(((k + offH) % 168) + 168) % 168] = { v: a.mean_range_pct[Math.floor(k / 24)][k % 24], n: a.n[Math.floor(k / 24)][k % 24], utc: k };
    return out;
  }, [a, offH]);
  const values = cells.map((c) => c.v).filter((v): v is number => v !== null).sort((x, y) => x - y);
  const lo = values.length ? values[Math.floor(values.length * 0.05)] : 0, hi = values.length ? values[Math.floor(values.length * 0.95)] : 1;
  const nowSlot = (() => {
    const d = new Date(now + offH * 3_600_000);
    return ((d.getUTCDay() + 6) % 7) * 24 + d.getUTCHours();
  })();
  const top = cells.map((c, k) => ({ ...c, k })).filter((c) => c.v !== null).sort((x, y) => (y.v ?? 0) - (x.v ?? 0)).slice(0, 3);
  const slotName = (k: number) => `${days[Math.floor(k / 24)]} ${String(k % 24).padStart(2, "0")}:00`;
  const tz = local ? `UTC${offH >= 0 ? "+" : ""}${offH}` : "UTC";
  const market = getMarket() === "gold" ? (lang === "ru" ? "Золото" : "Gold") : "BTC";

  return (
    <Card
      title={`${t("sesHeat")} · ${market}`}
      right={
        <div className="seg" role="group" aria-label={t("sesTz")}>
          <button className={local ? "on" : ""} aria-pressed={local} onClick={() => setLocal(true)}>{t("sesTzLocal")}</button>
          <button className={!local ? "on" : ""} aria-pressed={!local} onClick={() => setLocal(false)}>UTC</button>
        </div>
      }
    >
      <p className="mb-3 max-w-3xl text-sm muted">{t("sesHeatHelp")}</p>
      {act.error && !a && <ErrorBox error={act.error} onRetry={act.reload} />}
      {act.loading && !a && <Skeleton h={220} />}
      {a && a.bars === 0 && <p className="text-sm muted">{t("sesNoBars")}</p>}
      {a && a.bars > 0 && (
        <>
          <div className="heat-scroll">
            <div className="heat" role="table" aria-label={`${t("sesHeat")} (${tz})`}>
              <div role="row" className="heat-row">
                <span className="heat-day" />
                {Array.from({ length: 24 }, (_, h) => <span key={h} className="heat-hour num" role="columnheader">{h % 3 === 0 ? String(h).padStart(2, "0") : ""}</span>)}
              </div>
              {days.map((dn, d) => (
                <div key={dn} role="row" className="heat-row">
                  <span className="heat-day" role="rowheader">{dn}</span>
                  {Array.from({ length: 24 }, (_, h) => {
                    const k = d * 24 + h, c = cells[k];
                    const x = c.v === null ? 0 : Math.max(0, Math.min(1, (c.v - lo) / (hi - lo || 1)));
                    const tip = c.v === null ? `${slotName(k)} · ${t("sesClosedCell")}` : `${slotName(k)} · ${c.v.toFixed(2)} % · ${c.n} ${t("sesBars")}`;
                    return (
                      <span key={h} role="cell" title={tip} aria-label={tip} className={`heat-cell ${c.v === null ? "none" : ""} ${k === nowSlot ? "now" : ""}`}
                        style={c.v === null ? undefined : { background: `color-mix(in srgb, var(--gold) ${Math.round(8 + 87 * x)}%, transparent)` }} />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs muted">
            <span className="flex items-center gap-2">
              {t("sesLess")}<span className="heat-legend" aria-hidden="true" />{t("sesMore")}
              <span className="heat-cell now inline-block" aria-hidden="true" style={{ width: 12, height: 12 }} /> {t("sesNow")} · {tz}
            </span>
            <span className="num">{t("sesTop")}: {top.map((c) => `${slotName(c.k)} (${(c.v ?? 0).toFixed(2)} %)`).join(", ")}</span>
          </div>
          <p className="mt-2 text-xs faint">
            {t("sesSource")}: {a.source}, {a.from_ms ? fmtTime(a.from_ms).slice(0, 10) : ""} – {a.to_ms ? fmtTime(a.to_ms).slice(0, 10) : ""}, {a.bars.toLocaleString("en-US")} {t("sesBars")}. {t("sesHeatNote")}
          </p>
        </>
      )}
    </Card>
  );
}
