import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, withMarket, type Candle } from "./api";

export type Loadable<T> = { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };

/** The current theme ("dark" / "light"); components that paint with theme colours once (canvas, charts) redraw on a change. */
export function useThemeName(): string {
  const read = () => document.documentElement.dataset.theme ?? "dark";
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    const o = new MutationObserver(() => setTheme(read()));
    o.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => o.disconnect();
  }, []);
  return theme;
}

/** ``fn`` again (up to ``tries`` times, ``delayMs`` apart) while the server says the database is busy (503 - the live
 * process writes for a few seconds every 15 minutes) or the network blinked; any other error is returned at once. */
export async function withRetry<T>(fn: () => Promise<T>, tries = 5, delayMs = 1500): Promise<T> {
  for (let k = 1; ; k++) {
    try {
      return await fn();
    } catch (e) {
      const busy = e instanceof ApiError && e.status === 503;
      const blink = e instanceof ApiError && e.status === 0;  // no answer at all: one quick retry, then say so
      if (!(busy || (blink && k < 2)) || k >= tries) throw e;
      await new Promise((r) => window.setTimeout(r, delayMs));
    }
  }
}

/** Fetch now and then every `intervalMs` (0 = once). Keeps the last good data while a refresh fails; a busy database is retried. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = [], intervalMs = 0): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async () => {
    try {
      setData(await withRetry(() => fnRef.current()));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void run();
    if (!intervalMs) return;
    const id = window.setInterval(() => void run(), intervalMs);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, intervalMs, run]);

  return { data, error, loading, reload: () => void run() };
}

/** Server-Sent Events from /api/stream; `connected` is false when the stream is down (the UI then says so). */
export function useOverviewStream<T>(onEvent: (payload: T) => void): boolean {
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;
  useEffect(() => {
    if (typeof EventSource === "undefined" || window.location.search.includes("nosse")) return; // ?nosse: polling only (used by automated screenshots)
    const es = new EventSource(withMarket("/api/stream?interval=10"));
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.addEventListener("overview", (ev) => cb.current(JSON.parse((ev as MessageEvent).data) as T));
    return () => es.close();
  }, []);
  return connected;
}

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** Candles of one timeframe that grow to the left on demand (`loadOlder`), optionally until `coverFromMs` is on screen, and refresh at the right. */
export function useCandleFeed(tf: string, coverFromMs?: number, pageSize = 500) {
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [exhausted, setExhausted] = useState(false);
  const busy = useRef(false);
  const ref = useRef<Candle[]>([]);
  ref.current = candles;

  useEffect(() => {
    let cancelled = false;
    setCandles([]);
    setExhausted(false);
    setLoading(true);
    withRetry(() => api.candles(tf, pageSize))
      .then((r) => { if (!cancelled) { setCandles(r.candles); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e : new ApiError(0, String(e))); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tf, pageSize]);

  const loadOlder = useCallback(async () => {
    if (busy.current || exhausted || ref.current.length === 0) return;
    busy.current = true;
    try {
      const r = await withRetry(() => api.candles(tf, pageSize, ref.current[0].t));
      if (r.candles.length === 0) setExhausted(true);
      else setCandles((cur) => [...r.candles, ...cur]);
      if (r.candles.length < pageSize) setExhausted(true);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      busy.current = false;
    }
  }, [tf, pageSize, exhausted]);

  useEffect(() => {
    if (coverFromMs && candles.length && candles[0].t > coverFromMs && !exhausted) void loadOlder();
  }, [candles, coverFromMs, exhausted, loadOlder]);

  useEffect(() => {
    const id = window.setInterval(async () => {
      try {
        const r = await api.candles(tf, 8);
        setCandles((cur) => {
          if (!cur.length) return cur;
          const lastOld = cur[cur.length - 1].t;
          const merged = cur.filter((c) => c.t < r.candles[0].t);
          return merged.length === cur.length && r.candles[r.candles.length - 1].t <= lastOld ? cur : [...merged, ...r.candles];
        });
      } catch {
        /* keep the last good data */
      }
    }, 30000);
    return () => window.clearInterval(id);
  }, [tf]);

  return { candles, error, loading, loadOlder, exhausted };
}
