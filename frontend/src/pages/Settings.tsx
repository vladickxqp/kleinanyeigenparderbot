import { useState, type ReactNode } from "react";
import { ErrorBox, Loading } from "../components/DataState";
import { ThemeToggle } from "../components/ThemeToggle";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-slate-100 py-3 last:border-0 dark:border-slate-800">
      <span className="text-sm text-slate-500 dark:text-slate-400">{label}</span>
      <span className="text-sm font-medium">{value}</span>
    </div>
  );
}

function Toggle({ on }: { on: boolean }) {
  return (
    <span
      className={`badge ${
        on
          ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
          : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
      }`}
    >
      {on ? "an" : "aus"}
    </span>
  );
}

export function Settings() {
  const { data, loading, error } = useApi(() => api.settings(), []);
  const health = useApi(() => api.health(), []);
  const [density, setDensity] = useState(
    () => localStorage.getItem("density") ?? "comfortable",
  );

  function changeDensity(value: string) {
    setDensity(value);
    localStorage.setItem("density", value);
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Einstellungen</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Betrieb, Darstellung und Plattformen
        </p>
      </div>

      {/* Appearance */}
      <div className="card">
        <h3 className="mb-2 text-sm font-medium text-slate-500 dark:text-slate-400">
          Darstellung
        </h3>
        <div className="flex items-center justify-between py-2">
          <span className="text-sm">Theme</span>
          <ThemeToggle />
        </div>
        <div className="flex items-center justify-between py-2">
          <span className="text-sm">Dichte</span>
          <select
            className="input w-auto py-1"
            value={density}
            onChange={(e) => changeDensity(e.target.value)}
          >
            <option value="comfortable">Komfortabel</option>
            <option value="compact">Kompakt</option>
          </select>
        </div>
      </div>

      {/* System */}
      {loading && <Loading />}
      {error && <ErrorBox message={error} />}
      {data && (
        <>
          <div className="card">
            <h3 className="mb-2 text-sm font-medium text-slate-500 dark:text-slate-400">
              System
            </h3>
            <Row label="Umgebung" value={data.environment} />
            <Row label="Version" value={health.data?.version ?? "…"} />
            <Row
              label="Status"
              value={
                <span className="text-emerald-600 dark:text-emerald-400">
                  ● {health.data?.status ?? "…"}
                </span>
              }
            />
            <Row label="Prometheus" value={<Toggle on={data.prometheus_enabled} />} />
          </div>

          <div className="card">
            <h3 className="mb-2 text-sm font-medium text-slate-500 dark:text-slate-400">
              Scraping
            </h3>
            <Row
              label="Standard-Intervall"
              value={`${data.default_interval_seconds}s`}
            />
            <Row
              label="Mindestpause / Seite"
              value={`${data.scraper_min_delay_seconds}s`}
            />
            <Row label="Parallelität" value={data.scraper_max_concurrency} />
          </div>

          <div className="card">
            <h3 className="mb-2 text-sm font-medium text-slate-500 dark:text-slate-400">
              KI-Bewertung
            </h3>
            <Row label="Aktiviert" value={<Toggle on={data.ai_enabled} />} />
            <Row label="Modell" value={<code>{data.ai_model}</code>} />
          </div>

          <div className="card">
            <h3 className="mb-3 text-sm font-medium text-slate-500 dark:text-slate-400">
              Verfügbare Plattformen ({data.available_sites.length})
            </h3>
            <div className="flex flex-wrap gap-2">
              {data.available_sites.map((s) => (
                <span
                  key={s}
                  className="badge bg-brand-50 text-brand-700 dark:bg-brand-600/15 dark:text-brand-400"
                >
                  🏪 {s}
                </span>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
