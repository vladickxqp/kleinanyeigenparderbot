import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

export function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      nav("/");
    } catch {
      setError("Login fehlgeschlagen — Zugangsdaten prüfen.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-4">
      <div className="card w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="text-4xl">🛒</div>
          <h1 className="mt-2 text-xl font-semibold">Deal Hunter Admin</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Bitte anmelden
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium">Benutzername</label>
            <input
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Passwort</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          {error && <p className="text-sm text-rose-600">{error}</p>}
          <button className="btn-primary w-full" disabled={busy}>
            {busy ? "…" : "Anmelden"}
          </button>
        </form>
      </div>
    </div>
  );
}
