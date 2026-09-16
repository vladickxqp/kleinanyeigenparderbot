// Client for the Telegram Mini App API. Authentication is Telegram's own
// signed initData, sent with every request — no login screen, no JWT.

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData: string;
        ready: () => void;
        expand: () => void;
        close: () => void;
        colorScheme?: "light" | "dark";
        themeParams?: Record<string, string>;
        openTelegramLink?: (url: string) => void;
        openLink?: (url: string) => void;
        HapticFeedback?: { impactOccurred: (style: string) => void };
      };
    };
  }
}

export const SDK_URL = "https://telegram.org/js/telegram-web-app.js";

export function tg() {
  return window.Telegram?.WebApp;
}

export function initData(): string {
  return tg()?.initData ?? "";
}

export class WebAppError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function wa<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Telegram-Init-Data", initData());
  if (init.body) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api/webapp${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new WebAppError(res.status, detail);
  }
  return (await res.json()) as T;
}

/** One metered quota. `limit`/`remaining` carry -1 when the level has no cap. */
export interface WaQuota {
  kind: string;
  label: string;
  used: number;
  limit: number;
  remaining: number;
  unlimited: boolean;
  exhausted: boolean;
  window: string;
}

/** One level of the ladder, with every figure resolved on the server. */
export interface WaLevel {
  tier: string;
  label: string;
  price_stars: number;
  price_eur: number;
  purchasable: boolean;
  note: string | null;
  max_rules: number;
  base_interval_seconds: number;
  min_interval_seconds: number;
  fast_slots: number;
  daily_notifications: number;
  photo_evals_per_month: number;
  quick_searches_per_day: number;
  negotiations_per_month: number;
  history_days: number;
  features: string[];
}

/** Which cancellation the account screen may offer, decided on the server. */
export type CancelKind = "renewal" | "premium";

export interface Me {
  telegram_id: number;
  name: string;
  role: string;
  tier: string;
  is_paid: boolean;
  premium_until: string | null;
  renews: boolean;
  last_charge_at: string | null;
  next_charge_at: string | null;
  flip_min_net: number | null;
  price_stars: number;
  price_eur: number;
  can_cancel: boolean;
  cancel_kind: CancelKind | null;
  entitlements: WaLevel;
  usage: WaQuota[];
  levels: WaLevel[];
}

/** What a cancellation did: stopped the renewal, or ended premium outright. */
export interface WaCancel {
  outcome: "cancel_at_period_end" | "ended";
  detail: string;
  active_until: string | null;
  tier: string;
  label: string;
  is_paid: boolean;
  renews: boolean;
}

export interface WaRule {
  id: number;
  name: string;
  keywords: string;
  is_active: boolean;
  interval_seconds: number;
  min_price: number | null;
  max_price: number | null;
  location: string | null;
  max_distance_km: number | null;
  category: string | null;
}

export interface WaListing {
  id: number;
  site: string;
  title: string;
  url: string;
  image_url: string | null;
  price: number | null;
  estimated_market_price: number | null;
  deal_score: number;
  deal_verdict: string;
  location: string | null;
  is_favorite: boolean;
  created_at: string;
  discount_percent: number | null;
  is_negotiable: boolean;
  shipping_cost: number | null;
}

export interface WaFlip {
  id: number;
  title: string;
  buy_price: number;
  sell_price: number | null;
  net_profit: number | null;
  status: string;
  bought_at: string;
  sold_at: string | null;
}

export interface WaFlips {
  stats: {
    open_count: number;
    invested_open: number;
    sold_count: number;
    revenue: number;
    fees: number;
    net_profit: number;
    net_last_30d: number;
    avg_margin_pct: number | null;
    best_title: string | null;
    best_net: number | null;
  };
  open: WaFlip[];
}

export interface WaPayment {
  id: number;
  provider: string;
  amount_stars: number;
  amount_eur: number;
  status: string;
  refunded: boolean;
  is_renewal: boolean;
  coupon_code: string | null;
  created_at: string;
}

export interface RuleInput {
  name: string;
  keywords: string;
  min_price: number | null;
  max_price: number | null;
  location: string | null;
  max_distance_km: number | null;
  interval_seconds: number;
  exclude_keywords: string[];
}

async function waVoid(path: string, init: RequestInit = {}): Promise<void> {
  const headers = new Headers(init.headers);
  headers.set("X-Telegram-Init-Data", initData());
  const res = await fetch(`/api/webapp${path}`, { ...init, headers });
  if (!res.ok) throw new WebAppError(res.status, res.statusText);
}

export const webapp = {
  me: () => wa<Me>("/me"),
  rules: () => wa<WaRule[]>("/rules"),
  toggleRule: (id: number) => wa<WaRule>(`/rules/${id}/toggle`, { method: "POST" }),
  createRule: (body: RuleInput) =>
    wa<WaRule>("/rules", { method: "POST", body: JSON.stringify(body) }),
  updateRule: (id: number, body: RuleInput) =>
    wa<WaRule>(`/rules/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteRule: (id: number) => waVoid(`/rules/${id}`, { method: "DELETE" }),
  listings: (favorites = false) =>
    wa<WaListing[]>(`/listings?limit=40${favorites ? "&favorites=true" : ""}`),
  flips: () => wa<WaFlips>("/flips"),
  payments: () => wa<WaPayment[]>("/payments"),
  /** Cancels the caller's own subscription — no id, nothing to address. */
  cancelSubscription: () => wa<WaCancel>("/subscription/cancel", { method: "POST" }),
};

export const eur = (v: number | null | undefined) =>
  v == null ? "—" : `${Math.round(v).toLocaleString("de-DE")} €`;

export const dateDE = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("de-DE") : "—";

/** Mirrors entitlements.fmt_quota: -1 is a cap that does not exist. */
export const quotaText = (value: number, unit = "") =>
  value < 0 ? "unbegrenzt" : `${value.toLocaleString("de-DE")}${unit}`;

/** How full a capped quota is, as a 0…1 share for the usage bars. */
export const quotaShare = (q: WaQuota) =>
  q.unlimited ? 0 : q.limit <= 0 ? 1 : Math.min(1, q.used / q.limit);

export const everyMinutes = (seconds: number) =>
  seconds < 3600
    ? `${Math.max(1, Math.round(seconds / 60))} Min`
    : `${Math.round(seconds / 3600)} Std`;
