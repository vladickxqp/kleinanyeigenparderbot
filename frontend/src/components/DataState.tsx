import type { ReactNode } from "react";

export function Loading() {
  return (
    <div className="flex items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
      Lädt…
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="card border-rose-200 bg-rose-50 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
      ⚠️ {message}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="card text-center text-sm text-slate-500 dark:text-slate-400">
      {children}
    </div>
  );
}
