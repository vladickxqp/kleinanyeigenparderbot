import { Empty, ErrorBox, Loading } from "../components/DataState";
import { api, type UserInfo } from "../lib/api";
import { useApi } from "../lib/useApi";

const TIER_STYLES: Record<string, string> = {
  free: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  pro: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  unlimited: "bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-500/15 dark:text-fuchsia-300",
  // legacy values written by older versions
  premium: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  ultimate: "bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-500/15 dark:text-fuchsia-300",
};

const ROLE_STYLES: Record<string, string> = {
  admin: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  moderator: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  user: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
};

function displayName(u: UserInfo): string {
  if (u.username) return `@${u.username}`;
  const parts = [u.first_name, u.last_name].filter(Boolean);
  return parts.length ? parts.join(" ") : String(u.telegram_id);
}

export function Users() {
  const { data, loading, error } = useApi(() => api.users(), []);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data || data.length === 0)
    return <Empty>Noch keine Nutzer — starte den Bot in Telegram mit /start.</Empty>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Nutzer</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {data.length} registrierte Bot-Nutzer
        </p>
      </div>
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 text-left text-slate-500 dark:border-slate-800 dark:text-slate-400">
            <tr>
              <th className="px-4 py-3 font-medium">Nutzer</th>
              <th className="px-4 py-3 font-medium">Telegram-ID</th>
              <th className="px-4 py-3 font-medium">Sprache</th>
              <th className="px-4 py-3 font-medium">Rolle</th>
              <th className="px-4 py-3 font-medium">Abo</th>
              <th className="px-4 py-3 font-medium">Suchen</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Seit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.map((u) => (
              <tr key={u.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td className="px-4 py-3 font-medium">{displayName(u)}</td>
                <td className="px-4 py-3 tabular-nums text-slate-500 dark:text-slate-400">
                  {u.telegram_id}
                </td>
                <td className="px-4 py-3 uppercase">{u.language_code}</td>
                <td className="px-4 py-3">
                  <span className={`badge ${ROLE_STYLES[u.role] ?? ROLE_STYLES.user}`}>
                    {u.role}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={`badge ${TIER_STYLES[u.subscription] ?? TIER_STYLES.free}`}>
                    {u.subscription}
                  </span>
                </td>
                <td className="px-4 py-3 tabular-nums">{u.rules_count}</td>
                <td className="px-4 py-3">
                  {u.is_blocked ? (
                    <span className="badge bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300">
                      ⛔ blockiert
                    </span>
                  ) : u.is_active ? (
                    <span className="badge bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                      🟢 aktiv
                    </span>
                  ) : (
                    <span className="badge bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                      ⚪️ inaktiv
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                  {new Date(u.created_at).toLocaleDateString("de-DE")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
