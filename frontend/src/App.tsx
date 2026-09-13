import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useAuth } from "./lib/auth";
import { Dashboard } from "./pages/Dashboard";
import { Listings } from "./pages/Listings";
import { Login } from "./pages/Login";
import { MiniApp } from "./pages/MiniApp";
import { Parsers } from "./pages/Parsers";
import { Rules } from "./pages/Rules";
import { Settings } from "./pages/Settings";
import { Users } from "./pages/Users";

export default function App() {
  const { isAuthed } = useAuth();
  const { pathname } = useLocation();

  // The Telegram Mini App authenticates with Telegram's initData, not with
  // the admin login — it lives outside the JWT-protected area.
  if (pathname === "/app" || pathname.startsWith("/app/")) {
    return <MiniApp />;
  }

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
