// Tiny typed API client for the admin backend.
// Token is kept in localStorage and attached as a Bearer header.

const TOKEN_KEY = "auth_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`/api${path}`, { ...init, headers });
  if (res.status === 401) {
    setToken(null);
    throw new ApiError(401, "Nicht authentifiziert");
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, detail || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username, password });
  const res = await fetch("/api/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) {
    throw new ApiError(res.status, "Login fehlgeschlagen");
  }
  const data = (await res.json()) as { access_token: string };
  return data.access_token;
}

// --- Typed models mirroring app/api/schemas.py --------------------------------
export interface DashboardStats {
  users: number;
  active_rules: number;
  total_rules: number;
  listings: number;
  notified: number;
  parsers: number;
}

export interface Rule {
  id: number;
  name: string;
  keywords: string;
  max_price: number | null;
  is_active: boolean;
  interval_seconds: number;
  min_deal_score: number;
  created_at: string;
}

export interface Listing {
  id: number;
  site: string;
  title: string;
  url: string;
  price: number | null;
  deal_score: number;
  deal_verdict: string;
  location: string | null;
  created_at: string;
}

export interface ParserInfo {
  site: string;
  label: string;
  requires_browser: boolean;
}

export interface SafeSettings {
  environment: string;
  default_interval_seconds: number;
  scraper_min_delay_seconds: number;
  scraper_max_concurrency: number;
  ai_enabled: boolean;
  ai_model: string;
  prometheus_enabled: boolean;
  available_sites: string[];
}

export const api = {
  health: () =>
    request<{ status: string; version: string; parsers: number }>("/health"),
  dashboard: () => request<DashboardStats>("/stats/dashboard"),
  rules: () => request<Rule[]>("/rules"),
  listings: (minScore = 0, site?: string) => {
    const params = new URLSearchParams({ min_score: String(minScore) });
    if (site) params.set("site", site);
    return request<Listing[]>(`/listings?${params.toString()}`);
  },
  parsers: () => request<ParserInfo[]>("/parsers"),
  settings: () => request<SafeSettings>("/settings"),
};
