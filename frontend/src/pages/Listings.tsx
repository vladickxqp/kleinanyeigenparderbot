import { useState } from "react";
import { Empty, ErrorBox, Loading } from "../components/DataState";
import { VerdictBadge } from "../components/VerdictBadge";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";

export function Listings() {
  const [minScore, setMinScore] = useState(0);
  const [site, setSite] = useState("");
  const parsers = useApi(() => api.parsers(), []);
  const { data, loading, error } = useApi(
    () => api.listings(minScore, site || undefined),
    [minScore, site],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-2xl font-semibold">Angebote</h2>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            🏪 Plattform:
            <select
              className="input w-auto py-1"
              value={site}
              onChange={(e) => setSite(e.target.value)}
            >
              <option value="">Alle</option>
              {parsers.data?.map((p) => (
                <option key={p.site} value={p.site}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            Min. Score:{" "}
            <b className="tabular-nums text-slate-800 dark:text-slate-200">
              {minScore}
            </b>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              className="accent-brand-600"
            />
          </label>
        </div>
      </div>

      {loading && <Loading />}
      {error && <ErrorBox message={error} />}
      {!loading && !error && (!data || data.length === 0) && (
        <Empty>Keine Angebote über diesem Score.</Empty>
      )}

      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((l) => (
            <a
              key={l.id}
              href={l.url}
              target="_blank"
              rel="noreferrer"
              className="card flex flex-col gap-2 transition hover:-translate-y-0.5 hover:shadow-lg"
            >
              <div className="flex items-center justify-between">
                <span className="badge bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {l.site}
                </span>
                <VerdictBadge verdict={l.deal_verdict} />
              </div>
              <div className="line-clamp-2 font-medium">{l.title}</div>
              <div className="mt-auto flex items-center justify-between">
                <span className="text-lg font-semibold tabular-nums">
                  {l.price != null ? `${l.price.toLocaleString("de-DE")} €` : "—"}
                </span>
                <span className="text-sm text-slate-500 dark:text-slate-400">
                  Score <b className="tabular-nums">{l.deal_score}</b>
                </span>
              </div>
              {l.location && (
                <div className="text-xs text-slate-400">📍 {l.location}</div>
              )}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
