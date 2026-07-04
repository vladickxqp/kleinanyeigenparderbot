import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { StatCard } from "../components/StatCard";
import { ErrorBox, Loading } from "../components/DataState";
import { api } from "../lib/api";
import { useApi } from "../lib/useApi";

export function Dashboard() {
  const { data, loading, error } = useApi(() => api.dashboard(), []);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const chartData = [
    { name: "Nutzer", value: data.users },
    { name: "Regeln", value: data.total_rules },
    { name: "Aktiv", value: data.active_rules },
    { name: "Angebote", value: data.listings },
    { name: "Gesendet", value: data.notified },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Übersicht</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Live-Kennzahlen deines Deal-Bots
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard label="Nutzer" value={data.users} icon="👤" accent="bg-brand-500" />
        <StatCard
          label="Aktive Suchen"
          value={`${data.active_rules} / ${data.total_rules}`}
          icon="📋"
          accent="bg-emerald-500"
        />
        <StatCard label="Angebote gefunden" value={data.listings} icon="🛒" accent="bg-sky-500" />
        <StatCard label="Deals gesendet" value={data.notified} icon="📨" accent="bg-amber-500" />
        <StatCard label="Aktive Parser" value={data.parsers} icon="🔌" accent="bg-fuchsia-500" />
      </div>

      <div className="card">
        <h3 className="mb-4 text-sm font-medium text-slate-500 dark:text-slate-400">
          Kennzahlen
        </h3>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.15} />
              <XAxis dataKey="name" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip
                cursor={{ fillOpacity: 0.08 }}
                contentStyle={{
                  borderRadius: 12,
                  border: "none",
                  boxShadow: "0 4px 20px rgba(0,0,0,0.15)",
                }}
              />
              <Bar dataKey="value" fill="#6366f1" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
