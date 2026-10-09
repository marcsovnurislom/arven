import { useEffect, useState, type ReactNode } from "react";
import { useReducedMotion } from "./fx";
import { useI18n, type Key } from "./i18n";

const icon = (d: ReactNode) => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {d}
  </svg>
);

const NODES: { t: Key; b: Key; glyph: ReactNode }[] = [
  { t: "n1T", b: "n1B", glyph: icon(<><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6" /><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></>) },
  { t: "n2T", b: "n2B", glyph: icon(<><path d="M3 17l5-6 4 4 8-10" /><path d="M3 21h18" /></>) },
  { t: "n3T", b: "n3B", glyph: icon(<><circle cx="12" cy="12" r="9" /><path d="M12 3v9l6 4" /></>) },
  { t: "n4T", b: "n4B", glyph: icon(<><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="8" cy="6" r="1.5" fill="currentColor" /><circle cx="15" cy="12" r="1.5" fill="currentColor" /><circle cx="10" cy="18" r="1.5" fill="currentColor" /></>) },
  { t: "n5T", b: "n5B", glyph: icon(<><circle cx="12" cy="12" r="9" /><path d="M5.6 5.6l12.8 12.8" /></>) },
  { t: "n6T", b: "n6B", glyph: icon(<path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6z" />) },
  { t: "n7T", b: "n7B", glyph: icon(<><path d="M5 12l5 5L20 6" /></>) },
];

/** The signal path as seven cards; a glow travels left to right so the order of the steps reads at a glance. */
export function Pipeline() {
  const { t } = useI18n();
  const reduced = useReducedMotion();
  const [active, setActive] = useState(0);
  useEffect(() => {
    if (reduced) return;
    const id = window.setInterval(() => setActive((a) => (a + 1) % NODES.length), 1300);
    return () => window.clearInterval(id);
  }, [reduced]);
  return (
    <ol className="pipe" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {NODES.map((n, i) => (
        <li key={n.t} className={`node ${!reduced && i === active ? "active" : ""}`}>
          <div className="glyph">{n.glyph}</div>
          <div>
            <div className="text-sm font-semibold">
              <span className="faint num mr-1">{i + 1}</span>
              {t(n.t)}
            </div>
            <div className="mt-1 text-xs muted">{t(n.b)}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}
