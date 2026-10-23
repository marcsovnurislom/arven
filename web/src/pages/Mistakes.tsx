import { useMemo, useState } from "react";
import { api, type MistakeCell, type MistakeReport } from "../api";
import { useI18n, type Key, type Lang } from "../i18n";
import { useLoad } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, Skeleton, Stat } from "../ui";

const FEATURE_KEY: Record<string, Key> = {
  trend_4h: "msF_trend_4h", trend_1h: "msF_trend_1h", volatility: "msF_volatility", session: "msF_session",
  weekday: "msF_weekday", news: "msF_news", stop_atr: "msF_stop_atr", move_24h: "msF_move_24h",
};
const RU_VALUES: Record<string, string> = {
  "with the trade": "по направлению сделки", "against the trade": "против сделки", unknown: "нет данных",
  calm: "спокойно", normal: "обычно", stormy: "бурно",
  "00-07 Asia": "00-07 Азия", "07-13 Europe": "07-13 Европа", "13-21 US": "13-21 США", "21-24 late": "21-24 поздно",
  Mon: "Пн", Tue: "Вт", Wed: "Ср", Thu: "Чт", Fri: "Пт", Sat: "Сб", Sun: "Вс",
  "within 2 h before a release": "за 2 ч до новостей", "within 2 h after a release": "2 ч после новостей", "no release near": "новостей рядом нет",
  "tight (<1 ATR)": "узкий (<1 ATR)", "normal (1-2.5 ATR)": "обычный (1-2.5 ATR)", "wide (>2.5 ATR)": "широкий (>2.5 ATR)",
  "chasing (>+3 ATR)": "вдогонку (>+3 ATR)", "after a drop (<-3 ATR)": "после рывка против (<-3 ATR)", "quiet (+-3 ATR)": "спокойно (±3 ATR)",
};
const value = (v: string, lang: Lang) => (lang === "ru" ? RU_VALUES[v] ?? v : v);
const r = (x: number | null | undefined) => (x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}R`);

function Row({ name, c, scale, min, lang }: { name: string; c: MistakeCell; scale: number; min: number; lang: Lang }) {
  const { t } = useI18n();
  const small = c.trades < min;
  const w = Math.min(50, (Math.abs(c.mean_r) / scale) * 50);
  return (
    <tr className={small ? "faint" : ""}>
      <td>{value(name, lang)}</td>
      <td className="num">{c.trades}</td>
      <td className="num">{Math.round(c.win_rate * 100)} %</td>
      <td className="num">
        <span className="ms-bar" aria-hidden="true"><span className={c.mean_r >= 0 ? "pos" : "neg"} style={{ width: `${w}%` }} /></span>
        <span className={c.mean_r >= 0 ? "up" : "down"}>{r(c.mean_r)}</span>
      </td>
      <td className="num">{r(c.total_r)}</td>
      <td>{small ? <span className="text-xs">{t("msFew")}</span> : c.flag ? <Chip tone={c.flag === "worse" ? "down" : "up"}>{t(c.flag === "worse" ? "msWorse" : "msBetter")}</Chip> : <span className="text-xs faint" title={t("msNoDiff")} aria-label={t("msNoDiff")}>—</span>}</td>
    </tr>
  );
}

function Report({ rep, lang }: { rep: MistakeReport; lang: Lang }) {
  const { t } = useI18n();
  const scale = Math.max(0.1, ...Object.values(rep.features).flatMap((cs) => Object.values(cs).filter((c) => c.trades >= rep.min_trades).map((c) => Math.abs(c.mean_r))));
  return (
    <>
      <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label={t("msTrades")} value={rep.trades} />
        <Stat label={t("msMeanR")} value={<span className={(rep.mean_r ?? 0) >= 0 ? "up" : "down"}>{r(rep.mean_r)}</span>} sub={`${t("msTotal")} ${r(rep.total_r)}`} />
        <Stat label={t("msTested")} value={rep.tested} sub={t("msTestedSub").replace("{n}", String(rep.min_trades))} />
        <Stat label={t("msFlagged")} value={Object.values(rep.features).flatMap((cs) => Object.values(cs)).filter((c) => c.flag).length} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {Object.entries(rep.features).map(([f, cells]) => (
          <div key={f} className="overflow-x-auto">
            <h3 className="mb-1 text-sm font-medium muted">{t(FEATURE_KEY[f] ?? ("msF_trend_4h" as Key))}</h3>
            <table className="ms-table">
              <thead><tr><th>{t("msWhen")}</th><th>{t("msN")}</th><th>{t("msWin")}</th><th>{t("msMean")}</th><th>{t("msSum")}</th><th /></tr></thead>
              <tbody>{Object.entries(cells).sort((a, b) => b[1].trades - a[1].trades).map(([v, c]) => <Row key={v} name={v} c={c} scale={scale} min={rep.min_trades} lang={lang} />)}</tbody>
            </table>
          </div>
        ))}
      </div>
    </>
  );
}

export function Mistakes() {
  const { t, lang } = useI18n();
  const load = useLoad(api.mistakes, []);
  const d = load.data;
  const ids = useMemo(() => Object.keys(d?.strategies ?? {}), [d]);
  const [sid, setSid] = useState<string | null>(null);
  const [part, setPart] = useState<"history" | "forward">("history");
  const cur = sid ?? (ids.includes("all") ? "all" : ids[0]) ?? null;
  const s = cur && d ? d.strategies[cur] : null;
  const rep = s ? s[part] : null;
  const title = (id: string) => (id === "all" ? t("msAll") : d?.strategies[id]?.title ?? id);
  const ideas = (d?.proposals ?? []).filter((p) => p.part === part);

  return (
    <>
      <PageTitle sub={t("msSub")}>{t("nav_mistakes")}</PageTitle>
      {load.error && !d && <ErrorBox error={load.error} onRetry={load.reload} />}
      {load.loading && !d && <Skeleton h={300} />}
      {d && ids.length === 0 && <Empty>{t("msEmpty")}</Empty>}
      {ids.length > 0 && (
        <>
          <div className="seg mb-3 flex-wrap" role="group" aria-label={t("tmStrategy")}>
            {[...ids.filter((x) => x === "all"), ...ids.filter((x) => x !== "all")].map((x) => <button key={x} className={x === cur ? "on" : ""} aria-pressed={x === cur} onClick={() => setSid(x)}>{title(x)}</button>)}
          </div>
          <div className="seg mb-4" role="group" aria-label={t("stPeriod")}>
            <button className={part === "history" ? "on" : ""} aria-pressed={part === "history"} onClick={() => setPart("history")}>{t("msHistory")}</button>
            <button className={part === "forward" ? "on" : ""} aria-pressed={part === "forward"} onClick={() => setPart("forward")}>{t("msForward")}</button>
          </div>
          <Card className="mb-4" title={t("msIdeas")}>
            {ideas.length === 0 ? <p className="text-sm muted">{t("msNoIdeas")}</p> : (
              <ul className="grid gap-2 text-sm">
                {ideas.map((p, k) => (
                  <li key={k}>
                    <Chip tone={p.flag === "worse" ? "down" : "up"}>{t(p.flag === "worse" ? "msWorse" : "msBetter")}</Chip>{" "}
                    <b>{title(p.strategy)}</b>: {t(FEATURE_KEY[p.feature] ?? ("msF_trend_4h" as Key)).toLowerCase()} = {value(p.value, lang)} — {p.trades} {t("uvTrades")}, {r(p.mean_r)} {t("msVs")} {r(p.rest_mean_r)}.{" "}
                    <span className="muted">{t(p.flag === "worse" ? "msIdeaWorse" : "msIdeaBetter")}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title={`${title(cur!)} · ${t(part === "history" ? "msHistory" : "msForward")}`}>
            {rep ? <Report rep={rep} lang={lang} /> : <p className="text-sm muted">{t("msNoPart")}</p>}
          </Card>
          <p className="mt-4 text-xs faint">{t("msHow")}{d?.created_at ? ` ${t("msBuilt")}: ${d.created_at.slice(0, 16).replace("T", " ")} UTC.` : ""}</p>
        </>
      )}
    </>
  );
}
