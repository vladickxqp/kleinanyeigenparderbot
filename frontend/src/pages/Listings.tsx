import { useState } from "react";
import { Empty, ErrorBox } from "../components/DataState";
import { DealRow, DealRowSkeleton, type DealLike } from "../components/DealCard";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";

/** Split a list into `size`-long chunks, so wide screens get two columns. */
function chunk<T>(items: T[], size: number): T[][] {
  if (size <= 0) return [items];
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

/** Admin view of the same finds the users receive — same row, two columns. */
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
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Angebote</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Was der Bot gefunden und bewertet hat
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            Plattform
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
            Min. Score
            <b className="tabular-nums text-slate-800 dark:text-slate-200">{minScore}</b>
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

      {loading && (
        <div className="dh-group">
          <DealRowSkeleton />
          <DealRowSkeleton />
          <DealRowSkeleton />
        </div>
      )}
      {error && <ErrorBox message={error} />}
      {!loading && !error && (!data || data.length === 0) && (
        <Empty>Keine Angebote über diesem Score.</Empty>
      )}

      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {chunk(data as unknown as DealLike[], Math.ceil(data.length / 2)).map((column, i) => (
            <div key={i} className="dh-group">
              {column.map((l) => (
                <DealRow key={l.id} deal={l} />
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
