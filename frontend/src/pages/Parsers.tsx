import { Empty, ErrorBox, Loading } from "../components/DataState";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";

export function Parsers() {
  const { data, loading, error } = useApi(() => api.parsers(), []);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data || data.length === 0) return <Empty>Keine Parser registriert.</Empty>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Parser</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Registrierte Marktplatz-Module ({data.length})
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {data.map((p) => (
          <div key={p.site} className="card flex items-center gap-4">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-lg dark:bg-brand-600/15">
              🔌
            </div>
            <div className="flex-1">
              <div className="font-medium">{p.label}</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">{p.site}</div>
            </div>
            {p.requires_browser ? (
              <span className="badge bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
                🎭 Browser
              </span>
            ) : (
              <span className="badge bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                ⚡ HTTP
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
