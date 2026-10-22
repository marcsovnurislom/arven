import { useEffect, useRef } from "react";
import { LAND_BITS, LAND_STEP } from "./landmask";

export type GlobeCentre = { id: string; name: string; lat: number; lon: number; open: boolean };

const RAD = Math.PI / 180;
const TILT = 20 * RAD; // the view looks slightly down onto the northern hemisphere, where three of the four centres are
const SPIN = 4 * RAD; // auto-rotation per second, eastward like the Earth (the surface moves left to right)
const RESUME_MS = 2500; // after a drag, the globe starts turning again

/** Land dots as unit vectors, decoded exactly as scripts/web_land_mask.py encoded them. */
type Land = { cosLat: Float32Array; sinLat: Float32Array; cosLon: Float32Array; sinLon: Float32Array; n: number };
let landCache: Land | null = null;
function land(): Land {
  if (landCache) return landCache;
  const bytes = Uint8Array.from(atob(LAND_BITS), (c) => c.charCodeAt(0));
  const lat: number[] = [], lon: number[] = [];
  let k = 0;
  for (let i = 0; i < Math.round(180 / LAND_STEP); i++) {
    const la = -90 + LAND_STEP * (i + 0.5);
    const n = Math.max(1, Math.round((360 / LAND_STEP) * Math.cos(la * RAD)));
    for (let j = 0; j < n; j++, k++) {
      if ((bytes[k >> 3] >> (k & 7)) & 1) {
        lat.push(la * RAD);
        lon.push((-180 + ((j + 0.5) * 360) / n) * RAD);
      }
    }
  }
  const f = (xs: number[], fn: (x: number) => number) => Float32Array.from(xs, fn);
  landCache = { cosLat: f(lat, Math.cos), sinLat: f(lat, Math.sin), cosLon: f(lon, Math.cos), sinLon: f(lon, Math.sin), n: lat.length };
  return landCache;
}

/** Where the sun is overhead at ``ms`` (declination and equation of time, a few-minute approximation - display only). */
export function subsolar(ms: number): { lat: number; lon: number } {
  const d = new Date(ms);
  const start = Date.UTC(d.getUTCFullYear(), 0, 1);
  const day = (ms - start) / 86_400_000; // fractional day of the year, 0-based
  const g = (2 * Math.PI * day) / 365.25;
  const decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g) + 0.000907 * Math.sin(2 * g);
  const eot = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g) - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g)); // minutes
  const utcMin = (ms % 86_400_000) / 60_000;
  let lon = -(utcMin + eot - 720) / 4;
  lon = ((lon + 540) % 360) - 180;
  return { lat: decl / RAD, lon };
}

function readColors() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string, fb: string) => s.getPropertyValue(n).trim() || fb;
  return { gold: v("--gold", "#d9b256"), text: v("--text", "#eceff4"), faint: v("--faint", "#6b7381"), up: v("--up", "#34d399"), light: document.documentElement.dataset.theme === "light" };
}

/** A dotted Earth on a canvas: day and night from the real sun position, the trading centres glowing while they work.
 * Turns by itself (not with reduced motion), can be dragged; draws nothing while off screen. */
export function Globe({ centres, nowMs, label, size = 440 }: { centres: GlobeCentre[]; nowMs: number; label: string; size?: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const centresRef = useRef(centres);
  centresRef.current = centres;
  const nowRef = useRef(nowMs);
  nowRef.current = nowMs;
  const redraw = useRef<() => void>(() => {});

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const L = land();
    const day = new Float32Array(L.n);
    let sunAt = -Infinity, sun = subsolar(nowRef.current);
    let lon0 = sun.lon * RAD, lat0 = TILT;
    let colors = readColors();
    const themeObs = new MutationObserver(() => { colors = readColors(); });
    themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    let visible = true, raf = 0, last = performance.now(), dragAt = -Infinity;
    let drag: { x: number; y: number; lon0: number; lat0: number } | null = null;

    const resize = () => {
      const w = Math.min(size, el.parentElement?.clientWidth ?? size);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      el.style.width = el.style.height = `${w}px`;
      el.width = el.height = Math.round(w * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    if (el.parentElement) ro.observe(el.parentElement);
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) loop(performance.now()); });
    io.observe(el);

    const draw = (t: number) => {
      const w = el.width / Math.min(2, window.devicePixelRatio || 1);
      const R = w / 2 - 14, cx = w / 2, cy = w / 2;
      if (nowRef.current - sunAt > 30_000) {
        sun = subsolar(nowRef.current);
        sunAt = nowRef.current;
        const sl = sun.lat * RAD, sn = sun.lon * RAD;
        const sx = Math.cos(sl) * Math.cos(sn), sy = Math.cos(sl) * Math.sin(sn), sz = Math.sin(sl);
        for (let i = 0; i < L.n; i++) day[i] = L.cosLat[i] * (L.cosLon[i] * sx + L.sinLon[i] * sy) + L.sinLat[i] * sz;
      }
      ctx.clearRect(0, 0, w, w);
      // atmosphere and ocean
      const halo = ctx.createRadialGradient(cx, cy, R * 0.9, cx, cy, R * 1.12);
      halo.addColorStop(0, colors.light ? "rgba(138,101,18,0.18)" : "rgba(217,178,86,0.22)");
      halo.addColorStop(1, "rgba(217,178,86,0)");
      ctx.fillStyle = halo;
      ctx.beginPath(); ctx.arc(cx, cy, R * 1.12, 0, 2 * Math.PI); ctx.fill();
      const ocean = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R);
      ocean.addColorStop(0, colors.light ? "#e9e3d4" : "#1a1f29");
      ocean.addColorStop(1, colors.light ? "#d6cdb8" : "#0b0d12");
      ctx.fillStyle = ocean;
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.fill();

      // land dots in a few batches: lit / twilight / night, nearer dots brighter
      const sinT = Math.sin(lat0), cosT = Math.cos(lat0), cl = Math.cos(lon0), sl = Math.sin(lon0);
      const r = Math.max(0.8, R * 0.0085);
      const paths = [new Path2D(), new Path2D(), new Path2D(), new Path2D(), new Path2D(), new Path2D()];
      for (let i = 0; i < L.n; i++) {
        const cosD = L.cosLon[i] * cl + L.sinLon[i] * sl; // cos(lon - lon0)
        const depth = sinT * L.sinLat[i] + cosT * L.cosLat[i] * cosD;
        if (depth <= 0) continue;
        const sinD = L.sinLon[i] * cl - L.cosLon[i] * sl;
        const x = cx + R * L.cosLat[i] * sinD;
        const y = cy - R * (cosT * L.sinLat[i] - sinT * L.cosLat[i] * cosD);
        const lit = day[i] > 0.08 ? 0 : day[i] > -0.08 ? 1 : 2;
        const p = paths[lit * 2 + (depth > 0.45 ? 0 : 1)];
        p.moveTo(x + r, y);
        p.arc(x, y, r, 0, 2 * Math.PI);
      }
      const fills = colors.light
        ? ["rgba(138,101,18,0.95)", "rgba(138,101,18,0.55)", "rgba(110,90,40,0.6)", "rgba(110,90,40,0.35)", "rgba(40,48,62,0.45)", "rgba(40,48,62,0.25)"]
        : ["rgba(240,214,140,0.95)", "rgba(240,214,140,0.5)", "rgba(200,170,110,0.6)", "rgba(200,170,110,0.3)", "rgba(120,140,175,0.42)", "rgba(120,140,175,0.2)"];
      paths.forEach((p, k) => { ctx.fillStyle = fills[k]; ctx.fill(p); });

      // the sun, when it is on this side
      const ss = sun.lat * RAD, sd = sun.lon * RAD - lon0;
      const sDepth = sinT * Math.sin(ss) + cosT * Math.cos(ss) * Math.cos(sd);
      if (sDepth > 0) {
        const x = cx + R * Math.cos(ss) * Math.sin(sd), y = cy - R * (cosT * Math.sin(ss) - sinT * Math.cos(ss) * Math.cos(sd));
        const g = ctx.createRadialGradient(x, y, 0, x, y, R * 0.22);
        g.addColorStop(0, "rgba(255,226,140,0.35)");
        g.addColorStop(1, "rgba(255,226,140,0)");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, R * 0.22, 0, 2 * Math.PI); ctx.fill();
      }

      // trading centres
      ctx.font = "600 12px Inter, system-ui, sans-serif";
      ctx.textBaseline = "middle";
      for (const c of centresRef.current) {
        const la = c.lat * RAD, d = c.lon * RAD - lon0;
        const depth = sinT * Math.sin(la) + cosT * Math.cos(la) * Math.cos(d);
        if (depth <= 0.05) continue;
        const x = cx + R * Math.cos(la) * Math.sin(d), y = cy - R * (cosT * Math.sin(la) - sinT * Math.cos(la) * Math.cos(d));
        if (c.open) {
          const pulse = reduced ? 0.5 : (Math.sin(t / 450) + 1) / 2;
          const g = ctx.createRadialGradient(x, y, 0, x, y, 16 + 6 * pulse);
          g.addColorStop(0, "rgba(52,211,153,0.55)");
          g.addColorStop(1, "rgba(52,211,153,0)");
          ctx.fillStyle = g;
          ctx.beginPath(); ctx.arc(x, y, 16 + 6 * pulse, 0, 2 * Math.PI); ctx.fill();
          ctx.fillStyle = colors.up;
        } else ctx.fillStyle = colors.faint;
        ctx.beginPath(); ctx.arc(x, y, c.open ? 4.5 : 3.5, 0, 2 * Math.PI); ctx.fill();
        ctx.fillStyle = c.open ? colors.text : colors.faint;
        const right = x < cx + R * 0.55;
        ctx.textAlign = right ? "left" : "right";
        ctx.fillText(c.name, x + (right ? 9 : -9), y);
      }
    };

    function loop(t: number) {
      cancelAnimationFrame(raf);
      const dt = Math.min(100, t - last);
      last = t;
      if (!reduced && !drag && performance.now() - dragAt > RESUME_MS) lon0 -= (SPIN * dt) / 1000;
      draw(t);
      if (visible && (!reduced || drag)) raf = requestAnimationFrame(loop);
    }
    loop(performance.now());
    redraw.current = () => loop(performance.now());

    const down = (e: PointerEvent) => {
      drag = { x: e.clientX, y: e.clientY, lon0, lat0 };
      el.setPointerCapture(e.pointerId);
      if (reduced) loop(performance.now());
    };
    const move = (e: PointerEvent) => {
      if (!drag) return;
      const R = el.clientWidth / 2;
      lon0 = drag.lon0 - (e.clientX - drag.x) / R;
      lat0 = Math.max(-60 * RAD, Math.min(60 * RAD, drag.lat0 + (e.clientY - drag.y) / R));
    };
    const up = () => { drag = null; dragAt = performance.now(); };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect(); io.disconnect(); themeObs.disconnect();
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
  }, [size]);

  useEffect(() => redraw.current(), [centres, nowMs]); // a still globe (reduced motion) still shows the latest state

  return <canvas ref={canvas} role="img" aria-label={label} className="globe" style={{ touchAction: "none", cursor: "grab", display: "block", margin: "0 auto" }} />;
}
