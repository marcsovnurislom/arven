import { Suspense, lazy } from "react";
import { api } from "../api";
import { EquityCurve } from "../Charts2";
import { CountUp, Reveal, Tilt, Typewriter } from "../fx";
import { useLoad } from "../hooks";
import { useI18n, type Key } from "../i18n";
import { Pipeline } from "../Pipeline";
import { fmtR, signClass } from "../ui";

const Particles = lazy(() => import("../fx").then((m) => ({ default: m.ParticleField })));

const PILLARS: [Key, Key, string][] = [
  ["pillar1T", "pillar1B", "M3 17l5-6 4 4 8-10M3 21h18"],
  ["pillar2T", "pillar2B", "M12 3v18M5 8l7-5 7 5M5 16l7 5 7-5"],
  ["pillar3T", "pillar3B", "M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6z"],
];
const HONEST: [Key, Key][] = [["h1T", "h1B"], ["h2T", "h2B"], ["h3T", "h3B"], ["h4T", "h4B"], ["h5T", "h5B"]];

export function Home({ go, startTour }: { go: (p: string) => void; startTour: () => void }) {
  const { t } = useI18n();
  const ov = useLoad(api.overview, [], 30000);
  const sum = ov.data?.strategies_summary ?? null;
  const trades = (sum as unknown as { trades?: { t: number; strategy: string; side: number; r: number }[] } | null)?.trades ?? [];
  const sys = useLoad(api.system, [], 60000).data;
  const totalR = trades.reduce((a, x) => a + x.r, 0);

  return (
    <div className="grid gap-14">
      <section className="hero px-5 py-14 sm:px-12 sm:py-20" aria-label="ARVEN">
        <Suspense fallback={null}><Particles /></Suspense>
        <div className="relative">
          <div className="fade-in num text-xs tracking-[0.25em] gold sm:text-sm">{t("heroKicker")}</div>
          <h1 className="hero-title shine mt-3">ARVEN</h1>
          <p className="mt-5 min-h-[2.6em] max-w-3xl text-xl font-medium sm:text-3xl" style={{ lineHeight: 1.25 }}>
            <Typewriter phrases={[t("heroT1"), t("heroT2"), t("heroT3")]} />
          </p>
          <p className="mt-5 max-w-2xl text-sm leading-relaxed muted sm:text-base">{t("heroSub")}</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <button className="btn primary" style={{ padding: "12px 22px", fontSize: 15 }} onClick={() => go("overview")}>{t("ctaOpen")}</button>
            <button className="btn" style={{ padding: "12px 22px", fontSize: 15 }} onClick={startTour}>{t("ctaTour")}</button>
          </div>
        </div>
      </section>

      <Reveal>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {[  /* every number is counted by the server (/api/system), nothing is typed in by hand */
            { v: sys?.markets ?? 0, s: "", l: t("statMarkets") },
            { v: sys?.timeframes.length ?? 0, s: "", l: t("statTf") },
            { v: sys?.strategies.length ?? 0, s: "", l: t("statStrategies") },
            { v: sys?.signals_total ?? 0, s: "", l: t("statSignals") },
            { v: sys?.test_functions ?? 0, s: "", l: t("statTests") },
            { v: 0, s: "", l: t("statOrders") },
          ].map((x) => (
            <Tilt key={x.l} className="glass p-4 text-center sm:p-5">
              <div className="text-3xl font-bold gold sm:text-4xl"><CountUp value={x.v} suffix={x.s} /></div>
              <div className="mt-1 text-xs uppercase tracking-wider faint">{x.l}</div>
            </Tilt>
          ))}
        </div>
      </Reveal>

      <Reveal>
        <div className="grid gap-4 md:grid-cols-3">
          {PILLARS.map(([a, b, d], i) => (
            <Tilt key={a} className="glass p-6">
              <div className="grid h-12 w-12 place-items-center rounded-2xl" style={{ background: "var(--gold-soft)", color: "var(--gold)" }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
              </div>
              <h2 className="mt-4 text-xl font-semibold"><span className="faint num mr-2">0{i + 1}</span>{t(a)}</h2>
              <p className="mt-2 text-sm leading-relaxed muted">{t(b)}</p>
            </Tilt>
          ))}
        </div>
      </Reveal>

      <Reveal>
        <h2 className="text-2xl font-semibold sm:text-3xl">{t("pipeTitle")}</h2>
        <p className="mb-5 mt-1 max-w-3xl text-sm muted">{t("pipeSub")}</p>
        <Pipeline />
      </Reveal>

      <Reveal>
        <h2 className="text-2xl font-semibold sm:text-3xl">{t("honestTitle")}</h2>
        <p className="mb-5 mt-1 max-w-3xl text-sm muted">{t("honestSub")}</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {HONEST.map(([a, b], i) => (
            <Reveal key={a} delay={i * 70}>
              <Tilt className="glass h-full p-5">
                <div className="flex items-center gap-2"><span className="dot up" style={{ color: "var(--up)" }} /><h3 className="font-semibold">{t(a)}</h3></div>
                <p className="mt-2 text-sm leading-relaxed muted">{t(b)}</p>
              </Tilt>
            </Reveal>
          ))}
        </div>
      </Reveal>

      <Reveal>
        <div className="glass p-5 sm:p-7">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-2xl font-semibold sm:text-3xl">{t("resultsTitle")}</h2>
              <p className="mt-1 max-w-2xl text-sm muted">{t("resultsBody")}</p>
            </div>
            {trades.length > 0 && <div className={`num text-3xl font-bold ${signClass(totalR)}`}>{fmtR(totalR)}</div>}
          </div>
          <div className="mt-5"><EquityCurve trades={trades} /></div>
          <p className="mt-3 text-xs faint">{t("equityHelp")}</p>
          <div className="mt-4"><button className="btn" onClick={() => go("strategies")}>{t("nav_strategies")} →</button></div>
        </div>
      </Reveal>
    </div>
  );
}
