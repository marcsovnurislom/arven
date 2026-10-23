export type Candle = { t: number; o: number; h: number; l: number; c: number; v: number; complete: boolean };

export type SignalUpdate = { signal_id: string; time_ms: number; kind: string; detail: string };

export type Signal = {
  signal_id: string;
  symbol: string;
  side: 1 | -1;
  strategy_id: string;
  strategy_version: string;
  grade: string;
  event_time_ms: number;
  entry_reference: number;
  stop: number;
  tp_ladder: [number, number, number][]; // [r_multiple, close_fraction, price]
  risk_fraction: number;
  confidence: number;
  regime: string;
  reasons: string[];
  risk_checks: string[];
  status: "pending" | "open" | "partial" | "closed" | "cancelled";
  entry_type?: "market" | "limit";
  valid_until_ms?: number | null;
  max_holding_minutes?: number | null;
  updates: SignalUpdate[];
};

export type StrategyStats = {
  title?: string;
  signals: number;
  closed: number;
  open: number;
  pending?: number;
  cancelled?: number;
  error?: string | null;
  signals_per_week: number | null;
  total_r: number;
  mean_r: number | null;
  win_rate: number | null;
  review?: ForwardReview;
};

export type ForwardReview = {
  n: number;
  min_closed: number;
  mean_r: number | null;
  ci_low: number | null;
  ci_high: number | null;
  profit_factor: number | null;
  max_dd_r: number | null;
  verdict: "too_few" | "losing" | "inconclusive" | "positive";
};

export type Group = { n: number; mean_r: number | null; win_rate: number | null };

export type ForwardSummary = {
  generated_at: string;
  forward_start_ms: number;
  data_through_ms: number;
  cost_profile: string;
  strategies: Record<string, StrategyStats>;
  agreement_hypothesis: { alone: Group; agreed_by_another_strategy: Group };
  trades?: { t: number; strategy: string; side: number; r: number }[];
  note: string;
};

export type Overview = {
  now_ms: number;
  market?: string;
  market_open?: boolean;
  symbol: string;
  last_1m_bar_open_ms: number | null;
  data_age_seconds: number | null;
  data_stale: boolean;
  runtime: { present: boolean; stale: boolean; heartbeat: Record<string, unknown> | null };
  signals_total: number;
  signals_last_24h: number;
  signals_open: number;
  strategies: string[];
  strategies_summary: ForwardSummary | null;
  note: string;
};

export type ScreenerRow = {
  symbol: string; price: number; change_24h_pct: number | null; quote_volume_24h: number; as_of_ms: number; sparkline: number[];
  market?: string; label?: string;
};

export type ResearchRun = {
  kind: string;
  run_id: string;
  created_at: string | null;
  period: string | null;
  provider: string | null;
  touched_test_set: boolean | null;
  stress: boolean | null;
  result_hash: string | null;
  git_commit: string | null;
  git_dirty: boolean | null;
  total_return: number | null;
  max_drawdown: number | null;
  n_trades: number | null;
  win_rate: number | null;
  sharpe: number | null;
};

export type JournalEntry = {
  id: string;
  symbol: string;
  side: 1 | -1;
  entry: number;
  stop: number | null;
  exit: number | null;
  size: number | null;
  fees: number;
  opened_at: string | null;
  notes: string;
  tags: string[];
  r_multiple: number | null;
  created_at: string;
};

export type JournalStats = { trades: number; with_r: number; total_r: number; expectancy_r: number | null; win_rate: number | null };

export type TelegramStatus = { dry_run: boolean; token_configured: boolean; allowed_chats: number; outbox: Record<string, number> };

export type S7Point = { timeMs: number; price: number };
export type S7Zone = { kind: string; low: number; high: number; index: number; timeMs: number };
export type S7Setup = {
  id: string;
  timeframe: string;
  side: 1 | -1;
  arm_time_ms: number;
  line: { points: S7Point[] };
  touches: S7Point[];
  h_last: number;
  cross_time_ms: number;
  break_time_ms: number;
  range: { start_ms: number; end_ms: number; top: number; bottom: number } | null;
  level0: S7Point;
  level1: S7Point;
  fib: Record<string, number>;
  zone: { low: number; high: number };
  confluence: S7Zone[];
  confluence_score: number;
  candles: Candle[];
};
export type S7Review = { timeframe: string; total_setups: number; setups: S7Setup[]; note?: string; git_commit?: string | null };
export type S7Label = { verdict: "yes" | "no" | "unsure"; note: string; at_ms: number };
export type S7Trade = {
  n: number;
  id: string;
  side: 1 | -1;
  arm_time_ms: number;
  entry_time_ms: number;
  exit_time_ms: number;
  entry: number;
  stop: number;
  targets: number[];
  exit_reasons: string[];
  net_r: number;
  size_btc?: number;
  size?: number;
  size_unit?: string;
  risk_usd: number;
  pnl_usd: number;
  equity_after: number;
  skipped: string | null;
  line: { points: S7Point[] };
  touches: S7Point[];
  level0: S7Point;
  level1: S7Point;
  zone: { low: number; high: number };
  smc_zones?: { kind: string; low: number; high: number; timeMs: number }[];
  candles: Candle[];
};
/** One backtested/forward trade of any strategy (scripts/strategy_trades_export.py); the S7 drawing fields are optional. */
export type TradeRec = {
  n: number; id: string; side: 1 | -1; entry_time_ms: number; exit_time_ms: number; entry: number; stop: number; targets: number[];
  exit_reasons: string[]; net_r: number; size_btc?: number; size?: number; size_unit?: string; risk_usd: number; pnl_usd: number;
  equity_after: number; skipped: string | null;
  candles: Candle[];
  line?: { points: S7Point[] }; level0?: S7Point; level1?: S7Point; zone?: { low: number; high: number };
  smc_zones?: { kind: string; low: number; high: number; timeMs: number }[];
};
export type StrategyTradesSummary = { trades: number; win_rate: number; total_r: number; account: S7AccountSummary };
export type StrategyTradesEntry = { strategy: string; title: string; period: string; period_label: string; summary: StrategyTradesSummary };
export type StrategyTradesFile = StrategyTradesEntry & { costs: string; trades: TradeRec[] };
export type S7TradeLabel = { verdict: "ok" | "wrong" | "unsure"; note: string; at_ms: number };
export type S7AccountSummary = {
  start_equity: number; final_equity: number; return: number; trades: number; skipped: number; wins: number; losses: number;
  max_drawdown: number; best_trade_usd: number; worst_trade_usd: number;
};
export type S7Trades = {
  period: string;
  window_ms?: [number, number];
  account_rules?: { start_equity: number; risk_fraction: number; min_lot: number; lot_step: number; max_loss_fraction: number };
  summary: { trades: number; win_rate: number; total_r: number; account: S7AccountSummary } | null;
  trades: S7Trade[];
};

export type MarketSession = {
  id: string;
  label: string;
  session: string;
  state: "always_open" | "open" | "halt" | "weekend" | "holiday";
  open: boolean;
  next_change_ms: number | null;
  reason: string | null;
  closure_ends_ms: number | null;
  next_holiday: { start_ms: number; end_ms: number; reason: string } | null;
};

export type CentreSession = { id: string; name: string; tz: string; lat: number; lon: number; open_local: string; close_local: string; open: boolean; next_change_ms: number };

export type Sessions = { now_ms: number; markets: MarketSession[]; centres: CentreSession[]; note: string };

export type MistakeCell = { trades: number; win_rate: number; mean_r: number; total_r: number; diff_low: number | null; diff_high: number | null; flag: "worse" | "better" | null };
export type MistakeReport = { trades: number; mean_r: number | null; total_r: number; tested: number; level: number; min_trades: number; features: Record<string, Record<string, MistakeCell>> };
export type Mistakes = {
  market?: string;
  created_at?: string;
  features?: string[];
  strategies: Record<string, { title: string; history: MistakeReport | null; forward: MistakeReport | null }>;
  proposals: { strategy: string; part: string; feature: string; value: string; flag: "worse" | "better"; trades: number; mean_r: number; rest_mean_r: number }[];
};

export type TMItem = {
  kind: "setup" | "fill" | "tp" | "stop_moved" | "close" | "result";
  t: number;
  strategy: string;
  trade: number;
  side: 1 | -1;
  price?: number;
  stop?: number;
  targets?: number[];
  level?: string;
  fraction?: number;
  weight?: number;
  reason?: string;
  net_r?: number;
  pnl_usd?: number;
  equity_after?: number;
  line?: { timeMs: number; price: number }[];
  level0?: { timeMs: number; price: number };
  level1?: { timeMs: number; price: number };
  zone?: { low: number; high: number };
};
export type TMStrategy = { title: string; trades: number; final_equity: number; total_r: number };
export type TMScenarioEntry = { id: string; market: string; title: { en: string; ru: string }; about: { en: string; ru: string }; start_ms: number; end_ms: number; strategies: Record<string, TMStrategy> };
export type TMScenario = TMScenarioEntry & {
  tf_ms: number;
  context_until_ms: number;
  unit: string;
  candles: [number, number, number, number, number][];
  account_rules: { start_equity: number; risk_fraction: number };
  timelines: Record<string, TMStrategy & { start_equity: number; items: TMItem[] }>;
  note: string;
};

export type UniverseVerdict ="luck" | "skill_candidate" | "too_few";
export type UniverseEntry = { strategy: string; title: string; period: string; period_label: string; trades: number; percentile: number; verdict: UniverseVerdict; draws: number; final_equity: number; final_p50: number };
export type Universes = UniverseEntry & {
  market: string;
  seed: number[];
  git_commit: string | null;
  created_at: string;
  templates: number;
  random_trades_mean: number;
  strategy_result: { final_equity: number; total_r: number; mean_r: number; curve: number[] };
  universes: { final_p05: number; final_p50: number; final_p95: number; share_above_start: number; total_r_p50: number; mean_r_p50: number; mean_r_p95: number };
  percentile_total_r: number;
  skill_percentile: number;
  min_trades: number;
  account_rules: { start_equity: number; risk_fraction: number };
  finals: number[];
  curves: number[][];
};

export type EventType = "FOMC" | "CPI" | "NFP";
export type EventHorizonStats = {
  n: number;
  median_range?: number;
  mean_range?: number;
  max_range?: number;
  max_time_ms?: number;
  median_move?: number;
  median_baseline?: number | null;
  median_ratio?: number | null;
  share_above_baseline?: number | null;
  n_baseline?: number;
};
export type EventRow = { time_ms: number; type: EventType; note: string; horizons: Record<string, { range: number; move: number; baseline: number | null }> };
export type Events = {
  now_ms: number;
  market: string;
  horizons_min: number[];
  baseline_days: number;
  upcoming: { time_ms: number; type: EventType; note: string }[];
  known_until: Record<EventType, number | null>;
  summary: Record<EventType, Record<string, EventHorizonStats>>;
  recent: EventRow[];
  measured: number;
  note: string;
};

export type Activity = {
  market: string;
  source: string;
  days: number;
  mean_range_pct: (number | null)[][]; // [weekday Monday=0][UTC hour]
  n: number[][];
  bars: number;
  from_ms: number | null;
  to_ms: number | null;
  note: string;
};

export type Market = { id: string; label: string; symbol: string; history_symbol: string | null; session: string; enabled: boolean };

/** The market every market-aware request is about ("btc" or e.g. "gold"); remembered per browser. */
let currentMarket = (() => {
  try {
    return localStorage.getItem("arven.market") || "btc";
  } catch {
    return "btc";
  }
})();

export function getMarket(): string {
  return currentMarket;
}

export function setMarketId(id: string): void {
  currentMarket = id;
  try {
    localStorage.setItem("arven.market", id);
  } catch {
    /* ignore */
  }
}

/** Adds `market=` for a non-default market (BTC requests stay exactly as before). */
export function withMarket(path: string): string {
  if (currentMarket === "btc") return path;
  return `${path}${path.includes("?") ? "&" : "?"}market=${encodeURIComponent(currentMarket)}`;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "offline");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep status text */
    }
    throw new ApiError(res.status, String(detail));
  }
  return (await res.json()) as T;
}

export const api = {
  markets: () => request<{ markets: Market[]; default: string }>("/api/markets"),
  overview: () => request<Overview>(withMarket("/api/overview")),
  candles: (tf: string, limit = 400, before?: number) =>
    request<{ candles: Candle[]; source?: string }>(withMarket(`/api/candles?tf=${tf}&limit=${limit}${before ? `&before=${before}` : ""}`)),
  signals: (strategy?: string, limit = 200) =>
    request<{ signals: Signal[] }>(withMarket(`/api/signals?limit=${limit}${strategy ? `&strategy=${strategy}` : ""}`)),
  strategies: () => request<{ forward_summary: ForwardSummary | null; strategies: string[] }>(withMarket("/api/strategies")),
  sessions: () => request<Sessions>("/api/sessions"),
  activity: () => request<Activity>(withMarket("/api/activity")),
  events: () => request<Events>(withMarket("/api/events")),
  mistakes: () => request<Mistakes>(withMarket("/api/mistakes")),
  timeMachineIndex: () => request<{ scenarios: TMScenarioEntry[] }>(withMarket("/api/time_machine/index")),
  timeMachine: (id: string) => request<TMScenario>(withMarket(`/api/time_machine?id=${id}`)),
  universesIndex: () => request<{ entries: UniverseEntry[] }>(withMarket("/api/universes/index")),
  universes: (strategy: string, period: string) => request<Universes>(withMarket(`/api/universes?strategy=${strategy}&period=${period}`)),
  screener: () => request<{ supported_symbols: string[]; rows: ScreenerRow[]; note: string }>("/api/screener"),
  research: () => request<{ runs: ResearchRun[] }>(withMarket("/api/research")),
  journal: () => request<{ entries: JournalEntry[]; stats: JournalStats }>("/api/journal"),
  addJournal: (body: Record<string, unknown>) =>
    request<JournalEntry>("/api/journal", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  deleteJournal: (id: string) => request<{ deleted: string }>(`/api/journal/${id}`, { method: "DELETE" }),
  telegram: () => request<TelegramStatus>("/api/telegram"),
  s7Review: (tf: string) => request<S7Review>(withMarket(`/api/s7/review?tf=${tf}`)),
  s7Trades: (period: string) => request<S7Trades>(withMarket(`/api/s7/trades?period=${period}`)),
  strategyTradesIndex: () => request<{ entries: StrategyTradesEntry[] }>(withMarket("/api/strategy_trades/index")),
  strategyTrades: (strategy: string, period: string) => request<StrategyTradesFile>(withMarket(`/api/strategy_trades?strategy=${strategy}&period=${period}`)),
  s7TradeLabels: () => request<{ labels: Record<string, S7TradeLabel> }>("/api/s7/trade_labels"),
  s7TradeLabel: (trade_id: string, verdict: string, note: string) =>
    request<{ saved: string; count: number }>("/api/s7/trade_labels", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ trade_id, verdict, note }) }),
  s7Labels: (tf: string) => request<{ labels: Record<string, S7Label> }>(withMarket(`/api/s7/labels?tf=${tf}`)),
  s7Label: (setup_id: string, verdict: string, note: string) =>
    request<{ saved: string; count: number }>(withMarket("/api/s7/labels"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ setup_id, verdict, note }) }),
};

/** "0.05 BTC" / "3 oz": a trade's position size in its market's unit (BTC exports carry size_btc only). */
export function tradeSize(tr: { size_btc?: number; size?: number; size_unit?: string }): string {
  if (tr.size !== undefined) return `${tr.size.toFixed(2)} ${tr.size_unit ?? ""}`.trim();
  return `${(tr.size_btc ?? 0).toFixed(2)} BTC`;
}

/** Subtitle naming the current market and where its prices come from. */
export function marketSubtitle(): string {
  return currentMarket === "gold" ? "Gold · XAUUSD (live: Binance XAUUSDT, history: Dukascopy)" : currentMarket === "btc" ? "BTC/USDT" : currentMarket;
}
