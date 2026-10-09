import { Suspense, lazy, useEffect, useState } from "react";
import { I18nProvider, useI18n, type Key } from "./i18n";


const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const Signals = lazy(() => import("./pages/Signals").then((m) => ({ default: m.Signals })));
const Screener = lazy(() => import("./pages/Screener").then((m) => ({ default: m.Screener })));
const Charts = lazy(() => import("./pages/Charts").then((m) => ({ default: m.Charts })));
const Strategies = lazy(() => import("./pages/Strategies").then((m) => ({ default: m.Strategies })));
const Journal = lazy(() => import("./pages/Journal").then((m) => ({ default: m.Journal })));
const Lab = lazy(() => import("./pages/Lab").then((m) => ({ default: m.Lab })));
const Settings = lazy(() => import("./pages/Settings").then((m) => ({ default: m.Settings })));

const PAGES = ["overview", "signals", "screener", "charts", "strategies", "journal", "lab", "settings"] as const;
type Page = (typeof PAGES)[number];

function pageFromHash(): Page {
  const h = window.location.hash.replace(/^#\/?/, "");
  return (PAGES as readonly string[]).includes(h) ? (h as Page) : "overview";
}

function storedTheme(): "dark" | "light" {
  try {
    const v = localStorage.getItem("arven.theme");
    if (v === "light" || v === "dark") return v;
  } catch {
    /* ignore */
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function Shell() {
  const { t, lang, setLang } = useI18n();
  const [page, setPage] = useState<Page>(pageFromHash);
  const [theme, setThemeState] = useState<"dark" | "light">(storedTheme);

  const setTheme = (v: "dark" | "light") => {
    setThemeState(v);
    try {
      localStorage.setItem("arven.theme", v);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)) return;
      const n = Number(e.key);
      if (n >= 1 && n <= PAGES.length) window.location.hash = `/${PAGES[n - 1]}`;
      else if (e.key.toLowerCase() === "t") setTheme(theme === "dark" ? "light" : "dark");
      else if (e.key.toLowerCase() === "l") setLang(lang === "en" ? "ru" : "en");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const view = {
    overview: <Overview />, signals: <Signals />, screener: <Screener />, charts: <Charts />,
    strategies: <Strategies />, journal: <Journal />, lab: <Lab />, settings: <Settings theme={theme} setTheme={setTheme} />,
  }[page];

  const nav = (p: Page) => (
    <a
      key={p}
      href={`#/${p}`}
      aria-current={p === page ? "page" : undefined}
      className="rounded-lg px-3 py-2 text-sm"
      style={{ color: p === page ? "var(--gold)" : "var(--muted)", background: p === page ? "var(--gold-soft)" : "transparent", textDecoration: "none" }}
    >
      {t(`nav_${p}` as Key)}
    </a>
  );

  return (
    <>
      <a className="skip-link" href="#main">{t("skip")}</a>
      <header className="sticky top-0 z-20 border-b backdrop-blur" style={{ borderColor: "var(--border)", background: "color-mix(in srgb, var(--bg) 80%, transparent)" }}>
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <a href="#/overview" className="flex items-center gap-2" style={{ textDecoration: "none", color: "var(--text)" }} aria-label="ARVEN home">
            <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="var(--card-solid)" stroke="var(--border)" /><path d="M6 24 16 6l10 18h-5l-5-9-5 9z" fill="var(--gold)" /></svg>
            <span className="text-lg font-semibold tracking-wide">ARVEN</span>
          </a>
          <nav className="ml-4 hidden gap-1 lg:flex" aria-label="Main">{PAGES.map(nav)}</nav>
          <div className="ml-auto flex items-center gap-2">
            <button className="btn" onClick={() => setLang(lang === "en" ? "ru" : "en")} aria-label={t("language")}>{lang.toUpperCase()}</button>
            <button className="btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={t("theme")}>{theme === "dark" ? "☾" : "☀"}</button>
          </div>
        </div>
        <div className="px-4 pb-2 text-center text-xs" style={{ color: "var(--warn)" }}>{t("honesty")}</div>
      </header>
      <main id="main" className="mx-auto max-w-7xl px-4 pb-28 pt-6 lg:pb-10">
        <div key={page} className="rise">
            <Suspense fallback={<div className="skeleton" style={{ height: 160 }} aria-hidden="true" />}>{view}</Suspense>
        </div>
      </main>
      <nav className="fixed inset-x-0 bottom-0 z-20 flex justify-around overflow-x-auto border-t px-1 py-2 backdrop-blur lg:hidden" style={{ borderColor: "var(--border)", background: "color-mix(in srgb, var(--bg) 88%, transparent)" }} aria-label="Pages">
        {PAGES.map(nav)}
      </nav>
    </>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <Shell />
    </I18nProvider>
  );
}
