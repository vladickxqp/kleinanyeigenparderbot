import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { to: "/", label: "Dashboard", icon: "📊", end: true },
  { to: "/rules", label: "Suchregeln", icon: "📋" },
  { to: "/listings", label: "Angebote", icon: "🛒" },
  { to: "/users", label: "Nutzer", icon: "👤" },
  { to: "/parsers", label: "Parser", icon: "🔌" },
  { to: "/settings", label: "Einstellungen", icon: "⚙️" },
];

export function Layout() {
  const { logout } = useAuth();
  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 md:flex">
        <div className="mb-6 flex items-center gap-2 px-2">
          <span className="text-2xl">🛒</span>
          <span className="text-lg font-semibold">Deal Hunter</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-brand-50 text-brand-700 dark:bg-brand-600/15 dark:text-brand-400"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`
              }
            >
              <span>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <button className="btn-ghost justify-start" onClick={logout}>
          🚪 Abmelden
        </button>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white/70 px-6 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-900/70">
          <h1 className="text-sm font-medium text-slate-500 dark:text-slate-400">
            Admin-Panel
          </h1>
          <ThemeToggle />
        </header>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
