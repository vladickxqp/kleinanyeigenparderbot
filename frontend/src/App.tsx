import { Suspense, lazy } from "react";
import { useLocation } from "react-router-dom";
import { MiniApp } from "./pages/MiniApp";

/**
 * The admin panel is fetched only when someone actually opens it.
 *
 * The split is deliberately asymmetric. The Mini App stays eager, so it still
 * arrives in a single request on a phone; the admin panel takes the extra
 * round trip, because it runs on a desktop and has one user. Before this, /app
 * downloaded the whole dashboard — chart library included — to render a list
 * of deals.
 */
const AdminApp = lazy(() => import("./AdminApp"));

export default function App() {
  const { pathname } = useLocation();

  // The Telegram Mini App authenticates with Telegram's initData, not with
  // the admin login — it lives outside the JWT-protected area.
  if (pathname === "/app" || pathname.startsWith("/app/")) {
    return <MiniApp />;
  }

  return (
    <Suspense fallback={<div className="p-8 text-slate-500">Lädt…</div>}>
      <AdminApp />
    </Suspense>
  );
}
