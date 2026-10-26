import { Suspense, lazy, useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { api, getMarket, setMarketId, setMarketList, type Market } from "./api";
import { Aurora, useSpotlight } from "./fx";
import { useLoad } from "./hooks";
import { I18nProvider, useI18n, type Key } from "./i18n";

const Home = lazy(() => import("./pages/Home").then((m) => ({ default: m.Home })));
const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const Signals = lazy(() => import("./pages/Signals").then((m) => ({ default: m.Signals })));
const Screener = lazy(() => import("./pages/Screener").then((m) => ({ default: m.Screener })));
const Charts = lazy(() => import("./pages/Charts").then((m) => ({ default: m.Charts })));
const Strategies = lazy(() => import("./pages/Strategies").then((m) => ({ default: m.Strategies })));
const Journal = lazy(() => import("./pages/Journal").then((m) => ({ default: m.Journal })));
const Lab = lazy(() => import("./pages/Lab").then((m) => ({ default: m.Lab })));
const Settings = lazy(() => import("./pages/Settings").then((m) => ({ default: m.Settings })));
const S7Review = lazy(() => import("./pages/S7Review").then((m) => ({ default: m.S7Review })));
const Mistakes = lazy(() => import("./pages/Mistakes").then((m) => ({ default: m.Mistakes })));
const Replay = lazy(() => import("./pages/Replay").then((m) => ({ default: m.Replay })));
const Universes = lazy(() => import("./pages/Universes").then((m) => ({ default: m.Universes })));
const Events = lazy(() => import("./pages/Events").then((m) => ({ default: m.Events })));
const Sessions = lazy(() => import("./pages/Sessions").then((m) => ({ default: m.Sessions })));
const S7Trades = lazy(() => import("./pages/S7Trades").then((m) => ({ default: m.S7Trades })));
const Tour = lazy(() => import("./Tour").then((m) => ({ default: m.Tour })));

const PAGES = ["home", "overview", "signals", "screener", "charts", "strategies", "journal", "lab", "s7review", "s7trades", "settings", "sessions", "events", "universes", "replay", "mistakes"] as const;
type Page = (typeof PAGES)[number];

/** Every page's key after G (physical keys, e.code, so they work on any keyboard layout - Russian included). */
const SHORTCUTS: Record<Page, string> = {
  home: "KeyH", overview: "KeyO", sessions: "KeyW", events: "KeyN", charts: "KeyC", screener: "KeyF", signals: "KeyS",
  s7trades: "KeyT", s7review: "KeyR", strategies: "KeyA", universes: "KeyU", replay: "KeyP", mistakes: "KeyE", lab: "KeyL",
  journal: "KeyJ", settings: "Comma",
};
const CHORD_MS = 1500;
export const keyLabel = (code: string) => (code === "Comma" ? "," : code.replace(/^Key/, ""));

function pageFromHash(): Page {
  const h = window.location.hash.replace(/^#\/?/, "");
  return (PAGES as readonly string[]).includes(h) ? (h as Page) : "home";
}

function storedTheme(): "dark" | "light" {
  try {
    const v = localStorage.getItem("arven.theme");
    if (v === "light" || v === "dark") return v;
  } catch {
    /* ignore */
  }
  return "dark"; // the brand look is dark; light is an explicit choice (button or T)
}

function Shell() {
  const { t, lang, setLang } = useI18n();
  const [page, setPage] = useState<Page>(pageFromHash);
  const [theme, setThemeState] = useState<"dark" | "light">(storedTheme);
  const [tour, setTour] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const [market, setMarketState] = useState(getMarket);
  const marketsLoad = useLoad(api.markets, []);
  const markets: Market[] = marketsLoad.data?.markets ?? [];
  if (marketsLoad.data) setMarketList(marketsLoad.data.markets);
  const setMarket = useCallback((id: string) => {
    setMarketId(id);
    setMarketState(id);
  }, []);
  useEffect(() => {
    // a remembered market that no longer exists falls back to the default
    if (marketsLoad.data && !marketsLoad.data.markets.some((m) => m.id === market)) setMarket(marketsLoad.data.default);
  }, [marketsLoad.data, market, setMarket]);

  const setTheme = (v: "dark" | "light") => {
    setThemeState(v);
    try {
      localStorage.setItem("arven.theme", v);
    } catch {
      /* ignore */
    }
  };
  const go = useCallback((p: string) => {
    window.location.hash = `/${p}`;
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const onHash = () => {
      setPage(pageFromHash());
      setDrawer(false);
      window.scrollTo({ top: 0, behavior: "auto" });
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // the active menu item stays in view when the page changes (the menu scrolls on short screens)
  useEffect(() => {
    document.querySelector(".sidebar .side-link.on")?.scrollIntoView({ block: "nearest" });
  }, [page]);

  useSpotlight();
  const [help, setHelp] = useState(false);
  const [chord, setChord] = useState(false);
  const chordAt = useRef(0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if ((e.ctrlKey || e.metaKey) && e.code === "KeyK") {
        e.preventDefault();
        setPalette((v) => !v);
        return;
      }
      if (e.key === "Escape") { setHelp(false); setChord(false); chordAt.current = 0; }
      if (palette || drawer || tour) return;
      if (e.metaKey || e.ctrlKey || e.altKey || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable) return;
      if (chordAt.current && Date.now() - chordAt.current < CHORD_MS) {  // the second key of "G then a letter"
        chordAt.current = 0;
        setChord(false);
        const target = PAGES.find((p) => SHORTCUTS[p] === e.code);
        if (target) {
          e.preventDefault();
          setHelp(false);
          go(target);
        }
        return;
      }
      if (e.code === "KeyG") {
        chordAt.current = Date.now();
        setChord(true);
        window.setTimeout(() => { if (Date.now() - chordAt.current >= CHORD_MS) setChord(false); }, CHORD_MS + 50);
        return;
      }
      if (e.key === "?" || (e.code === "Slash" && e.shiftKey)) {
        e.preventDefault();
        setHelp((v) => !v);
        return;
      }
      if (help) return;
      if (e.code === "BracketLeft" || e.code === "BracketRight") {
        const order = GROUPS.flatMap((g) => g.pages);
        const i = order.indexOf(page);
        go(order[(i + (e.code === "BracketRight" ? 1 : -1) + order.length) % order.length]);
      } else if (e.code === "KeyT") setTheme(theme === "dark" ? "light" : "dark");
      else if (e.code === "KeyM" && markets.length > 1) {
        const i = markets.findIndex((m) => m.id === market);
        setMarket(markets[(i + 1) % markets.length].id);
      } else if (e.code === "KeyL") setLang(lang === "en" ? "ru" : "en");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const view = {
    home: <Home go={go} startTour={() => setTour(true)} />, overview: <Overview />, signals: <Signals />, screener: <Screener />, charts: <Charts />,
    strategies: <Strategies />, journal: <Journal />, lab: <Lab />, s7review: <S7Review />, s7trades: <S7Trades />, sessions: <Sessions />, events: <Events />, universes: <Universes />, replay: <Replay />, mistakes: <Mistakes />, settings: <Settings theme={theme} setTheme={setTheme} />,
  }[page];

  const label = (p: Page) => t(`nav_${p}` as Key);
  const link = (p: Page, onClick?: () => void) => (
    <a key={p} href={`#/${p}`} aria-current={p === page ? "page" : undefined} className={`side-link ${p === page ? "on" : ""}`} onClick={onClick}>
      <Icon name={p} />
      <span className="truncate">{label(p)}</span>
      <kbd className="side-kbd ml-auto hidden lg:inline" title={t("kbChord")}>G {keyLabel(SHORTCUTS[p])}</kbd>
    </a>
  );
  const groups = (onClick?: () => void) =>
    GROUPS.map((g) => (
      <div key={g.key} className="side-group">
        {g.key !== "main" && <div className="side-group-label">{t(g.key as Key)}</div>}
        {g.pages.map((p) => link(p, onClick))}
      </div>
    ));
  const group = GROUPS.find((g) => g.pages.includes(page));

  return (
    <>
      <Aurora />
      <a className="skip-link" href="#main">{t("skip")}</a>
      <aside className="sidebar" aria-label="Main">
        <a href="#/home" className="brand" aria-label="ARVEN home">
          <Logo />
          <span>
            <span className="brand-name shine">ARVEN</span>
            <span className="brand-sub">{markets.length > 2 ? `${markets.length} ${t("mkCount")}` : markets.length > 1 ? "BTC · Gold" : "BTC"} · decision support</span>
          </span>
        </a>
        <nav className="side-nav" aria-label="Pages">{groups()}</nav>
      </aside>
      <div className="app-col">
        <header className="topbar">
          <div className="topbar-row">
            <button className="btn icon lg:hidden" onClick={() => setDrawer(true)} aria-label={t("menu")}>☰</button>
            <div className="crumbs min-w-0">
              {group && group.key !== "main" && <span className="faint hidden sm:inline">{t(group.key as Key)} /</span>}
              <span className="truncate">{label(page)}</span>
            </div>
            <div className="ml-auto flex items-center gap-2">
              {markets.length > 1 && <MarketSwitch markets={markets} value={market} onChange={setMarket} label={t("market")} />}
              <button className="btn search-btn" onClick={() => setPalette(true)} aria-label={t("search")}>
                <span aria-hidden="true">⌕</span><span className="hidden md:inline">{t("search")}</span><kbd className="hidden md:inline">Ctrl K</kbd>
              </button>
              <button className="btn hidden lg:inline-flex" onClick={() => setHelp(true)} aria-label={t("kbTitle")} title={`${t("kbTitle")} (?)`}>⌨</button>
              <button className="btn" onClick={() => setTour(true)} aria-label={t("tourTitle")}><span aria-hidden="true">✦</span><span className="hidden md:inline"> {t("tourTitle")}</span></button>
              <button className="btn" onClick={() => setLang(lang === "en" ? "ru" : "en")} aria-label={t("language")}>{lang.toUpperCase()}</button>
              <button className="btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={t("theme")}>{theme === "dark" ? "☾" : "☀"}</button>
            </div>
          </div>
          <div className="honesty">{t("honesty")}</div>
          <div key={page} className="route-bar" aria-hidden="true" />
        </header>
        <main id="main" className="mx-auto max-w-7xl px-4 pb-28 pt-6 lg:pb-12">
          <div key={`${page}:${market}`} className="page-in">
            <Suspense fallback={<div className="skeleton" style={{ height: 160 }} aria-hidden="true" />}>{view}</Suspense>
          </div>
        </main>
      </div>
      <nav className="bottombar lg:hidden" aria-label="Quick">
        {QUICK.map((p) => (
          <a key={p} href={`#/${p}`} aria-current={p === page ? "page" : undefined} className={`bottom-link ${p === page ? "on" : ""}`}>
            <Icon name={p} /><span>{label(p)}</span>
          </a>
        ))}
        <button className="bottom-link" onClick={() => setDrawer(true)} aria-label={t("menu")}><span className="text-lg leading-none" aria-hidden="true">☰</span><span>{t("menu")}</span></button>
      </nav>
      {drawer && (
        <div className="drawer-backdrop lg:hidden" onClick={() => setDrawer(false)}>
          <div className="drawer" role="dialog" aria-label={t("menu")} onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <span className="brand-name shine">ARVEN</span>
              <button className="btn icon" onClick={() => setDrawer(false)} aria-label={t("chartExit")}>✕</button>
            </div>
            {groups(() => setDrawer(false))}
          </div>
        </div>
      )}
      {palette && <Palette pages={GROUPS.flatMap((g) => g.pages)} label={label} onGo={(p) => { go(p); setPalette(false); }} onClose={() => setPalette(false)} placeholder={t("searchPh")} empty={t("searchNone")} title={t("search")} />}
      {tour && <Suspense fallback={null}><Tour onClose={() => setTour(false)} /></Suspense>}
      {help && <ShortcutHelp label={label} onClose={() => setHelp(false)} />}
      {chord && <div className="chord-hint" role="status"><kbd>G</kbd> → {t("kbChordWait")}</div>}
    </>
  );
}

const GROUPS: { key: string; pages: Page[] }[] = [
  { key: "main", pages: ["home"] },
  { key: "grp_market", pages: ["overview", "sessions", "events", "charts", "screener", "signals"] },
  { key: "grp_s7", pages: ["s7trades", "s7review"] },
  { key: "grp_research", pages: ["strategies", "universes", "replay", "mistakes", "lab"] },
  { key: "grp_me", pages: ["journal", "settings"] },
];
const QUICK: Page[] = ["home", "charts", "signals", "s7trades"];

const ICONS: Record<Page, string> = {
  home: "M3 11 12 3l9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  overview: "M4 19h16M7 16V9m5 7V5m5 11v-4",
  charts: "M7 3v4m0 10v4M5 7h4v10H5zM17 5v3m0 9v3m-2-12h4v9h-4z",
  screener: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm9 16-4-4",
  signals: "M13 2 4 14h7l-1 8 9-12h-7z",
  strategies: "m12 3 9 5-9 5-9-5zm-9 9 9 5 9-5M3 16l9 5 9-5",
  lab: "M9 3h6m-5 0v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3",
  journal: "M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zm0 13a3 3 0 0 1 3-3h11",
  s7review: "M4 4h16v16H4zm4 8 3 3 5-6",
  s7trades: "M4 18 9 12l4 3 7-9M15 6h5v5",
  sessions: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3.6 9h16.8M3.6 15h16.8M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9s1.3-6.5 3.8-9z",
  events: "M12 8v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9 1h6",
  universes: "M3 20c3-1 5-6 9-8s6-6 9-9M3 20c4-3 6-4 9-4s5-3 9-5M3 20c3 0 6-2 9-2s6 1 9 0",
  replay: "M12 7v5l3 2M3 12a9 9 0 1 0 3-6.7M3 4v4h4",
  mistakes: "M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9",
  settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm0-6v3m0 14v3M2 12h3m14 0h3M4.9 4.9 7 7m10 10 2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1",
};

function Icon({ name }: { name: Page }) {
  return (
    <svg className="side-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}

function Logo() {
  return (
    <svg className="logo" width="34" height="34" viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id="lg-gold" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#f6dd94" /><stop offset="100%" stopColor="#b8862b" /></linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="var(--card-solid)" stroke="var(--border)" />
      <path d="M6 24 16 6l10 18h-5l-5-9-5 9z" fill="url(#lg-gold)" />
    </svg>
  );
}

/** A market's short name: BTC, ETH, XAU, EUR/USD ... */
export function marketShort(m: Market): string {
  if (m.session === "fx") return `${m.symbol.slice(0, 3)}/${m.symbol.slice(3, 6)}`;
  return m.symbol.replace(/USDT$/, "");
}

/** The picker: every market-aware page re-loads for the chosen market (the page is re-mounted by its key). Up to three
 * markets are a segmented switch; more open a panel grouped into crypto, metals and forex. */
function MarketSwitch({ markets, value, onChange, label }: { markets: Market[]; value: string; onChange: (id: string) => void; label: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); window.removeEventListener("keydown", esc); };
  }, [open]);
  if (markets.length <= 3)
    return (
      <div className="market-switch" role="radiogroup" aria-label={label}>
        {markets.map((m) => (
          <button key={m.id} role="radio" aria-checked={m.id === value} className={`market-opt ${m.id === value ? "on" : ""}`}
            onClick={() => onChange(m.id)} title={m.label}>
            {marketShort(m)}
          </button>
        ))}
      </div>
    );
  const cur = markets.find((m) => m.id === value) ?? markets[0];
  const groups: [string, Market[]][] = [
    [t("mkCrypto"), markets.filter((m) => m.session === "24x7")],
    [t("mkMetals"), markets.filter((m) => m.session === "cme_metals")],
    [t("mkFx"), markets.filter((m) => m.session === "fx")],
  ];
  return (
    <div className="mk-pick" ref={box}>
      <button className="btn mk-btn" aria-haspopup="true" aria-expanded={open} aria-label={`${label}: ${cur.label}`} onClick={() => setOpen((o) => !o)} title={cur.label}>
        <span className={`mk-dot s-${cur.session}`} aria-hidden="true" />
        <b>{marketShort(cur)}</b>
        <span className="mk-chev" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="mk-panel glass" role="dialog" aria-label={t("mkPick")}>
          {groups.filter(([, ms]) => ms.length).map(([name, ms]) => (
            <div key={name} className="mk-group">
              <div className="mk-group-label">{name}</div>
              <div className="mk-grid" role="radiogroup" aria-label={name}>
                {ms.map((m) => (
                  <button key={m.id} role="radio" aria-checked={m.id === value} className={`mk-opt ${m.id === value ? "on" : ""}`}
                    onClick={() => { onChange(m.id); setOpen(false); }} title={m.label}>
                    <span className={`mk-dot s-${m.session}`} aria-hidden="true" />
                    <b>{marketShort(m)}</b>
                    <small>{m.label.replace(/\s*\(.*\)$/, "")}</small>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Ctrl+K page switcher: type to filter, arrows to move, Enter to open, Escape to close. */
function Palette({ pages, label, onGo, onClose, placeholder, empty, title }: { pages: readonly Page[]; label: (p: Page) => string; onGo: (p: Page) => void; onClose: () => void; placeholder: string; empty: string; title: string }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const needle = q.trim().toLowerCase();
  const hits = pages.filter((p) => label(p).toLowerCase().includes(needle) || p.includes(needle));
  useEffect(() => setSel(0), [q]);
  const onKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") { e.preventDefault(); setSel((x) => Math.min(hits.length - 1, x + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((x) => Math.max(0, x - 1)); }
    else if (e.key === "Enter" && hits[sel]) onGo(hits[sel]);
  };
  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette glass" role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} placeholder={placeholder} aria-label={placeholder} />
        <div className="palette-list" role="listbox" aria-label={title}>
          {hits.length === 0 && <div className="faint px-3 py-4 text-sm">{empty}</div>}
          {hits.map((p, k) => (
            <button key={p} role="option" aria-selected={k === sel} className={`palette-item ${k === sel ? "on" : ""}`} onMouseEnter={() => setSel(k)} onClick={() => onGo(p)}>
              <Icon name={p} /><span>{label(p)}</span><kbd className="ml-auto">G {keyLabel(SHORTCUTS[p])}</kbd>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/** "?" - every keyboard shortcut in one place: pages (G then a letter), global keys, and the keys of single pages. */
function ShortcutHelp({ label, onClose }: { label: (p: Page) => string; onClose: () => void }) {
  const { t } = useI18n();
  const global: [string, Key][] = [["Ctrl K", "kbSearch"], ["?", "kbHelp"], ["[  ]", "kbPrevNext"], ["T", "kbTheme"], ["L", "kbLang"], ["M", "kbMarket"], ["Esc", "kbClose"]];
  const perPage: [Key, [string, Key][]][] = [
    ["nav_s7review", [["Y / N / U", "kbVerdict"], ["← →", "kbPrevNextItem"]]],
    ["nav_s7trades", [["Y / N / U", "kbVerdict"], ["← →", "kbPrevNextItem"]]],
    ["nav_replay", [["Space", "kbPlay"], ["→", "kbNextEvent"], ["Home", "kbRestart"], ["1-4", "kbSpeed"]]],
  ];
  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette glass kb-help" role="dialog" aria-label={t("kbTitle")} onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t("kbTitle")}</h2>
          <button className="btn icon" onClick={onClose} aria-label={t("chartExit")}>✕</button>
        </div>
        <p className="mb-3 text-sm muted">{t("kbChord")}</p>
        <div className="kb-grid">
          {GROUPS.map((g) => (
            <div key={g.key}>
              <div className="side-group-label">{g.key === "main" ? t("nav_home") : t(g.key as Key)}</div>
              {g.pages.map((p) => <div key={p} className="kb-row"><span>{label(p)}</span><kbd>G {keyLabel(SHORTCUTS[p])}</kbd></div>)}
            </div>
          ))}
          <div>
            <div className="side-group-label">{t("kbGlobal")}</div>
            {global.map(([k, d]) => <div key={k} className="kb-row"><span>{t(d)}</span><kbd>{k}</kbd></div>)}
          </div>
          {perPage.map(([pg, rows]) => (
            <div key={pg}>
              <div className="side-group-label">{t(pg)}</div>
              {rows.map(([k, d]) => <div key={k} className="kb-row"><span>{t(d)}</span><kbd>{k}</kbd></div>)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <Shell />
    </I18nProvider>
  );
}
