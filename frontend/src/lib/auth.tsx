import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getToken, login as apiLogin, setToken } from "./api";

interface AuthCtx {
  isAuthed: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState<boolean>(() => !!getToken());

  const login = useCallback(async (username: string, password: string) => {
    const token = await apiLogin(username, password);
    setToken(token);
    setAuthed(true);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setAuthed(false);
  }, []);

  const value = useMemo<AuthCtx>(
    () => ({ isAuthed: authed, login, logout }),
    [authed, login, logout],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
