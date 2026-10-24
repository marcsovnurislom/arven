import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useThemeName } from "./hooks";

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => (typeof window !== "undefined" ? window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false : false));
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

/** Fades and lifts its children into view once they scroll into the viewport (instant when motion is reduced). */
export function Reveal({ children, delay = 0, className = "", as: Tag = "div" }: { children: ReactNode; delay?: number; className?: string; as?: "div" | "section" | "li" }) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(false);
  const reduced = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    if (!el || reduced || typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShown(true);
          io.disconnect();
        }
      },
      { threshold: 0.12 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reduced]);
  const style: CSSProperties = { transitionDelay: `${delay}ms` };
  return (
    <Tag ref={ref as never} className={`reveal ${shown ? "in" : ""} ${className}`} style={style}>
      {children}
    </Tag>
  );
}

/** A soft light that follows the pointer over cards and buttons: one passive listener sets --mx / --my on the element
 * under the pointer (the CSS draws the glow). Off with reduced motion. */
export function useSpotlight(): void {
  const reduced = useReducedMotion();
  useEffect(() => {
    if (reduced) return;
    let raf = 0;
    let last: PointerEvent | null = null;
    const paint = () => {
      raf = 0;
      const e = last;
      if (!e) return;
      const el = (e.target as Element | null)?.closest?.(".glass, .strategy-card, .btn, .session-row") as HTMLElement | null;
      if (!el) return;
      const r = el.getBoundingClientRect();
      el.style.setProperty("--mx", `${e.clientX - r.left}px`);
      el.style.setProperty("--my", `${e.clientY - r.top}px`);
    };
    const onMove = (e: PointerEvent) => {
      last = e;
      if (!raf) raf = requestAnimationFrame(paint);
    };
    document.addEventListener("pointermove", onMove, { passive: true });
    return () => { document.removeEventListener("pointermove", onMove); cancelAnimationFrame(raf); };
  }, [reduced]);
}

/** Counts from the previous value to `value` with an ease-out curve. */
export function CountUp({ value, decimals = 0, duration = 1100, prefix = "", suffix = "" }: { value: number; decimals?: number; duration?: number; prefix?: string; suffix?: string }) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (reduced || !Number.isFinite(value)) {
      setShown(value);
      from.current = value;
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      const e = 1 - Math.pow(1 - p, 3);
      setShown(a + (value - a) * e);
      if (p < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration, reduced]);
  return (
    <span className="num">
      {prefix}
      {shown.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
      {suffix}
    </span>
  );
}

/** Card that leans toward the pointer and lights a soft spotlight under it. */
export function Tilt({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const move = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el || reduced || e.pointerType === "touch") return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    el.style.setProperty("--rx", `${((0.5 - y) * 6).toFixed(2)}deg`);
    el.style.setProperty("--ry", `${((x - 0.5) * 8).toFixed(2)}deg`);
    el.style.setProperty("--mx", `${(x * 100).toFixed(1)}%`);
    el.style.setProperty("--my", `${(y * 100).toFixed(1)}%`);
  };
  const leave = () => {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  };
  return (
    <div ref={ref} className={`tilt ${className}`} onPointerMove={move} onPointerLeave={leave}>
      {children}
    </div>
  );
}

/** Slow drifting colour fields behind everything (pure CSS transforms - cheap on the GPU). */
export function Aurora() {
  return (
    <div className="aurora" aria-hidden="true">
      <span className="blob b1" />
      <span className="blob b2" />
      <span className="blob b3" />
      <span className="grain" />
    </div>
  );
}

/** A constellation of drifting points joined by faint lines; pauses when hidden and is skipped for reduced motion. */
export function ParticleField({ className = "" }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const reduced = useReducedMotion();
  const theme = useThemeName();  // the points take the theme's gold: redraw on a switch
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || reduced) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let w = 0, h = 0, raf = 0, last = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const pts = Array.from({ length: window.innerWidth < 700 ? 34 : 64 }, () => ({ x: Math.random(), y: Math.random(), vx: (Math.random() - 0.5) * 0.00006, vy: (Math.random() - 0.5) * 0.00006, r: 0.8 + Math.random() * 1.6 }));
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = rect.width;
      h = rect.height;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    const gold = getComputedStyle(document.documentElement).getPropertyValue("--gold").trim() || "#d9b256";
    const draw = (t: number) => {
      raf = requestAnimationFrame(draw);
      if (document.hidden || t - last < 33) return; // ~30 fps is plenty for a background
      const dt = Math.min(64, t - last || 33);
      last = t;
      ctx.clearRect(0, 0, w, h);
      for (const p of pts) {
        p.x = (p.x + p.vx * dt + 1) % 1;
        p.y = (p.y + p.vy * dt + 1) % 1;
      }
      const maxD = Math.min(170, w * 0.25);
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i];
        for (let j = i + 1; j < pts.length; j++) {
          const b = pts[j];
          const d = Math.hypot((a.x - b.x) * w, (a.y - b.y) * h);
          if (d < maxD) {
            ctx.strokeStyle = `color-mix(in srgb, ${gold} ${Math.round((1 - d / maxD) * 38)}%, transparent)`;
            ctx.lineWidth = 0.8;
            ctx.beginPath();
            ctx.moveTo(a.x * w, a.y * h);
            ctx.lineTo(b.x * w, b.y * h);
            ctx.stroke();
          }
        }
        ctx.fillStyle = gold;
        ctx.globalAlpha = 0.55;
        ctx.beginPath();
        ctx.arc(a.x * w, a.y * h, a.r, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [reduced, theme]);
  return <canvas ref={ref} className={className} aria-hidden="true" />;
}

/** Rotates through phrases with a typing and deleting effect. */
export function Typewriter({ phrases, className = "" }: { phrases: string[]; className?: string }) {
  const reduced = useReducedMotion();
  const [i, setI] = useState(0);
  const [n, setN] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const joined = phrases.join("|");
  useEffect(() => {
    setI(0);
    setN(0);
    setDeleting(false);
  }, [joined]);
  useEffect(() => {
    if (reduced) return;
    const full = phrases[i % phrases.length] ?? "";
    const delay = !deleting && n === full.length ? 1600 : deleting ? 24 : 55;
    const id = window.setTimeout(() => {
      if (!deleting && n === full.length) setDeleting(true);
      else if (deleting && n === 0) {
        setDeleting(false);
        setI((x) => (x + 1) % phrases.length);
      } else setN((x) => x + (deleting ? -1 : 1));
    }, delay);
    return () => window.clearTimeout(id);
  }, [n, deleting, i, phrases, reduced]);
  const text = reduced ? phrases[0] ?? "" : (phrases[i % phrases.length] ?? "").slice(0, n);
  return (
    <span className={className} aria-label={phrases[0]}>
      {text}
      {!reduced && <span className="caret" aria-hidden="true" />}
    </span>
  );
}
