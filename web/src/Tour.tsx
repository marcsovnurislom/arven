import { useEffect, useRef, useState } from "react";
import { useI18n, type Key } from "./i18n";

const STEPS: { page: string; title: Key; body: Key }[] = [
  { page: "home", title: "nav_home", body: "tour1" },
  { page: "overview", title: "nav_overview", body: "tour2" },
  { page: "signals", title: "nav_signals", body: "tour3" },
  { page: "charts", title: "nav_charts", body: "tour4" },
  { page: "strategies", title: "nav_strategies", body: "tour5" },
  { page: "journal", title: "nav_journal", body: "tour6" },
  { page: "lab", title: "nav_lab", body: "tour7" },
];

/** A guided walk through the app for a first-time viewer: each step opens its page and explains it in two sentences. */
export function Tour({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [i, setI] = useState(0);
  const step = STEPS[i];
  const next = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    window.location.hash = `/${step.page}`;
  }, [step.page]);

  useEffect(() => {
    next.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setI((x) => Math.min(STEPS.length - 1, x + 1));
      if (e.key === "ArrowLeft") setI((x) => Math.max(0, x - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const last = i === STEPS.length - 1;
  return (
    <div className="tour-backdrop" role="dialog" aria-modal="true" aria-label={t("tourTitle")}>
      <div className="glass tour-card fade-in p-5 sm:p-6" style={{ background: "var(--card-solid)" }}>
        <div className="flex items-center justify-between">
          <span className="num text-xs gold">{t("tourStep")} {i + 1} / {STEPS.length}</span>
          <button className="btn" onClick={onClose} style={{ padding: "4px 10px" }}>{t("tourClose")}</button>
        </div>
        <h2 className="mt-2 text-2xl font-semibold">{t(step.title)}</h2>
        <p className="mt-2 text-sm leading-relaxed muted">{t(step.body)}</p>
        <div className="mt-4 flex gap-1" aria-hidden="true">
          {STEPS.map((_, k) => <span key={k} style={{ height: 4, flex: 1, borderRadius: 4, background: k <= i ? "var(--gold)" : "var(--border)", transition: "background .3s" }} />)}
        </div>
        <div className="mt-5 flex justify-between gap-2">
          <button className="btn" disabled={i === 0} onClick={() => setI(i - 1)} style={{ opacity: i === 0 ? 0.4 : 1 }}>{t("tourPrev")}</button>
          <button ref={next} className="btn primary" onClick={() => (last ? onClose() : setI(i + 1))}>{last ? t("tourDone") : t("tourNext")}</button>
        </div>
      </div>
    </div>
  );
}
