const STYLES: Record<string, string> = {
  steal: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  great: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  good: "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300",
  fair: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  overpriced: "bg-slate-100 text-slate-600 dark:bg-slate-700/40 dark:text-slate-300",
  unknown: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

const LABELS: Record<string, string> = {
  steal: "🔥 Kracher",
  great: "💚 Top",
  good: "✅ Gut",
  fair: "⚖️ Fair",
  overpriced: "🔴 Teuer",
  unknown: "❔ ?",
};

export function VerdictBadge({ verdict }: { verdict: string }) {
  const style = STYLES[verdict] ?? STYLES.unknown;
  return <span className={`badge ${style}`}>{LABELS[verdict] ?? verdict}</span>;
}
