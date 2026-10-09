import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export type Loadable<T> = { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };

/** Fetch now and then every `intervalMs` (0 = once). Keeps the last good data while a refresh fails. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = [], intervalMs = 0): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async () => {
    try {
      setData(await fnRef.current());
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
    const es = new EventSource("/api/stream?interval=10");
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
