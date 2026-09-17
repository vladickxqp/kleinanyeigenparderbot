import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useAuth } from "./lib/auth";
import { Dashboard } from "./pages/Dashboard";
import { Listings } from "./pages/Listings";
import { Login } from "./pages/Login";
import { Parsers } from "./pages/Parsers";
import { Rules } from "./pages/Rules";
import { Settings } from "./pages/Settings";
import { Users } from "./pages/Users";

/**
 * The admin panel — everything behind the JWT login.
 *
 * Split out of App so it can be loaded on demand: the dashboard's chart
 * library alone is most of the bundle, and the Telegram Mini App used to
 * download all of it over mobile data without ever rendering a chart.
 */
export default function AdminApp() {
  const { isAuthed } = useAuth();

  if (!isAuthed) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="rules" element={<Rules />} />
        <Route path="listings" element={<Listings />} />
        <Route path="users" element={<Users />} />
        <Route path="parsers" element={<Parsers />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
