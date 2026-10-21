import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { api, type S7Label, type S7Setup } from "../api";
import type { ChartLine, ChartMarker, ChartOverlay } from "../CandleChart";
import { useI18n } from "../i18n";
import { useLoad } from "../hooks";
import { Card, Chip, Empty, ErrorBox, PageTitle, SidePill, Skeleton, fmt, fmtTime } from "../ui";

const CandleChart = lazy(() => import("../CandleChart").then((m) => ({ default: m.CandleChart })));
const FIB_COLORS: Record<string, string> = { "0.0": "#9aa3b2", "0.5": "#d9b256", "0.618": "#d9b256", "1.0": "#eceff4", "1.272": "#34d399", "1.618": "#34d399", "2.0": "#34d399" };
const KIND_LABEL: Record<string, string> = { order_block: "Order block", fvg: "FVG", ifvg: "iFVG", level: "Level (SnR)" };

function Chart({ s }: { s: S7Setup }) {
  const lines = useMemo<ChartLine[]>(
    () => Object.entries(s.fib).map(([r, price]) => ({ price, color: FIB_COLORS[r] ?? "#9aa3b2", title: `fib ${r}`, dashed: r !== "0.5" && r !== "0.618" })),
    [s],
  );
  const overlays = useMemo<ChartOverlay[]>(() => {
    const o: ChartOverlay[] = [{ points: s.line.points, color: "#f5d061", width: 2 }];
    if (s.range) {
      o.push({ points: [{ timeMs: s.range.start_ms, price: s.range.top }, { timeMs: s.range.end_ms, price: s.range.top }], color: "#6aa8ff", dashed: true });
      o.push({ points: [{ timeMs: s.range.start_ms, price: s.range.bottom }, { timeMs: s.range.end_ms, price: s.range.bottom }], color: "#6aa8ff", dashed: true });
    }
    return o;
  }, [s]);
  const markers = useMemo<ChartMarker[]>(
    () => [
      ...s.touches.map((p) => ({ timeMs: p.timeMs, side: s.side, text: "touch", shape: "circle" as const, color: "#ff9f43", position: s.side === 1 ? ("aboveBar" as const) : ("belowBar" as const) })),
      { timeMs: s.break_time_ms, side: s.side, text: "break" },
      { timeMs: s.level0.timeMs, side: s.side, text: "0", shape: "square" as const, color: "#9aa3b2", position: s.side === 1 ? ("belowBar" as const) : ("aboveBar" as const) },
      { timeMs: s.level1.timeMs, side: s.side, text: "1", shape: "square" as const, color: "#eceff4", position: s.side === 1 ? ("aboveBar" as const) : ("belowBar" as const) },
    ],
    [s],
  );
  return (
    <Suspense fallback={<Skeleton h={460} />}>
      <CandleChart key={s.id} candles={s.candles} lines={lines} overlays={overlays} markers={markers} height={460} focusTimeMs={s.line.points[0].timeMs} />
    </Suspense>
  );
}

export function S7Review() {
  const { t } = useI18n();
  const [tf, setTf] = useState("1h");
  const review = useLoad(() => api.s7Review(tf), [tf]);
  const labelsLoad = useLoad(() => api.s7Labels(tf), [tf]);
  const [labels, setLabels] = useState<Record<string, S7Label>>({});
  const [i, setI] = useState(0);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => setLabels(labelsLoad.data?.labels ?? {}), [labelsLoad.data]);
  const setups = review.data?.setups ?? [];
  const s = setups[Math.min(i, Math.max(0, setups.length - 1))];
  useEffect(() => setNote(s ? labels[s.id]?.note ?? "" : ""), [s?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useCallback(async (verdict: "yes" | "no" | "unsure") => {
    if (!s || saving) return;
    setSaving(true);
    try {
      await api.s7Label(s.id, verdict, note);
      setLabels((l) => ({ ...l, [s.id]: { verdict, note, at_ms: Date.now() } }));
      setI((x) => Math.min(setups.length - 1, x + 1));
    } finally {
      setSaving(false);
    }
  }, [s, note, saving, setups.length]);

  // layout effect: the handler is swapped before the browser paints the next setup, so a key pressed right after a save
  // never reaches the previous render's handler (its `saving` and setup are stale)
  useLayoutEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "TEXTAREA") return;
      const k = e.key.toLowerCase();
      if (k === "y") void save("yes");
      else if (k === "n") void save("no");
      else if (k === "u") void save("unsure");
      else if (e.key === "ArrowRight") setI((x) => Math.min(setups.length - 1, x + 1));
      else if (e.key === "ArrowLeft") setI((x) => Math.max(0, x - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, setups.length]);

  const done = setups.filter((x) => labels[x.id]).length;
  const counts = { yes: 0, no: 0, unsure: 0 };
  for (const x of setups) if (labels[x.id]) counts[labels[x.id].verdict] += 1;

  return (
    <>
      <PageTitle sub={t("s7Help")}>{t("nav_s7review")}</PageTitle>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex gap-1" role="group" aria-label={t("chartTf")}>
          {["15m", "1h", "4h"].map((x) => <button key={x} className={`btn ${x === tf ? "primary" : ""}`} aria-pressed={x === tf} onClick={() => { setTf(x); setI(0); }}>{x}</button>)}
        </div>
        <Chip tone="gold">{done} / {setups.length} {t("s7Reviewed")}</Chip>
        <Chip tone="up">{t("s7Yes")}: {counts.yes}</Chip>
        <Chip tone="down">{t("s7No")}: {counts.no}</Chip>
        <Chip>{t("s7Unsure")}: {counts.unsure}</Chip>
        {review.data && <span className="text-xs faint">{t("s7Found")} {review.data.total_setups}</span>}
      </div>
      {review.error && !review.data && <ErrorBox error={review.error} onRetry={review.reload} />}
      {review.loading && !review.data && <Skeleton h={460} />}
      {review.data && setups.length === 0 && <Empty>{t("s7Empty")}</Empty>}
      {s && (
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <Card
            title={<span className="flex items-center gap-2"><SidePill side={s.side} /><span className="num">{fmtTime(s.arm_time_ms)}</span><span className="faint num">#{i + 1}</span></span>}
            right={labels[s.id] && <Chip tone={labels[s.id].verdict === "yes" ? "up" : labels[s.id].verdict === "no" ? "down" : ""}>{labels[s.id].verdict}</Chip>}
          >
            <Chart s={s} />
            <p className="mt-2 text-xs faint">{t("s7Legend")}</p>
          </Card>
          <div className="grid content-start gap-4">
            <Card title={t("s7Verdict")}>
              <div className="grid grid-cols-3 gap-2">
                <button className="btn" style={{ borderColor: "var(--up)" }} onClick={() => save("yes")} disabled={saving}>{t("s7Yes")} (Y)</button>
                <button className="btn" style={{ borderColor: "var(--down)" }} onClick={() => save("no")} disabled={saving}>{t("s7No")} (N)</button>
                <button className="btn" onClick={() => save("unsure")} disabled={saving}>{t("s7Unsure")} (U)</button>
              </div>
              <label className="mt-3 grid gap-1 text-sm">{t("notes")}<textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("s7NotePh")} /></label>
              <div className="mt-3 flex justify-between">
                <button className="btn" onClick={() => setI((x) => Math.max(0, x - 1))} disabled={i === 0}>← {t("tourPrev")}</button>
                <button className="btn" onClick={() => setI((x) => Math.min(setups.length - 1, x + 1))} disabled={i >= setups.length - 1}>{t("tourNext")} →</button>
              </div>
            </Card>
            <Card title={t("s7Details")}>
              <dl className="grid grid-cols-2 gap-1 text-sm">
                <dt className="muted">{t("s7Touches")}</dt><dd className="num text-right">{s.touches.length}</dd>
                <dt className="muted">{t("s7Range")}</dt><dd className="num text-right">{s.range ? `${fmt(s.range.bottom, 0)}–${fmt(s.range.top, 0)}` : "—"}</dd>
                <dt className="muted">fib 0</dt><dd className="num text-right">{fmt(s.level0.price, 0)}</dd>
                <dt className="muted">fib 1</dt><dd className="num text-right">{fmt(s.level1.price, 0)}</dd>
                <dt className="muted">{t("s7Zone")}</dt><dd className="num text-right">{fmt(s.zone.low, 0)}–{fmt(s.zone.high, 0)}</dd>
                <dt className="muted">{t("s7Confluence")}</dt><dd className="num text-right">{s.confluence_score}</dd>
              </dl>
              <ul className="mt-2 grid gap-1 text-xs muted">
                {s.confluence.map((z, k) => <li key={k} className="num">{KIND_LABEL[z.kind] ?? z.kind}: {fmt(z.low, 0)}{z.high !== z.low ? `–${fmt(z.high, 0)}` : ""}</li>)}
              </ul>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
