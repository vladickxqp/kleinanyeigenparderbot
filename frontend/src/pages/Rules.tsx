import { Empty, ErrorBox, Loading } from "../components/DataState";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";

export function Rules() {
  const { data, loading, error } = useApi(() => api.rules(), []);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data || data.length === 0) return <Empty>Noch keine Suchregeln angelegt.</Empty>;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">Suchregeln</h2>
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 text-left text-slate-500 dark:border-slate-800 dark:text-slate-400">
            <tr>
              <th className="px-4 py-3 font-medium">Name</th>
              <th className="px-4 py-3 font-medium">Suchbegriffe</th>
              <th className="px-4 py-3 font-medium">Max €</th>
              <th className="px-4 py-3 font-medium">Intervall</th>
              <th className="px-4 py-3 font-medium">Min-Score</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td className="px-4 py-3 font-medium">{r.name}</td>
                <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                  <code>{r.keywords}</code>
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {r.max_price ? `${r.max_price} €` : "—"}
                </td>
                <td className="px-4 py-3 tabular-nums">{r.interval_seconds}s</td>
                <td className="px-4 py-3 tabular-nums">{r.min_deal_score}</td>
                <td className="px-4 py-3">
                  <span
                    className={`badge ${
                      r.is_active
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                        : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                    }`}
                  >
                    {r.is_active ? "🟢 aktiv" : "⚪️ pausiert"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
