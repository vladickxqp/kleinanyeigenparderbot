interface Props {
  label: string;
  value: number | string;
  icon: string;
  accent?: string;
}

export function StatCard({ label, value, icon, accent = "bg-brand-500" }: Props) {
  return (
    <div className="card flex items-center gap-4">
      <div
        className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-xl text-white ${accent}`}
      >
        {icon}
      </div>
      <div>
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
        <div className="text-sm text-slate-500 dark:text-slate-400">{label}</div>
      </div>
    </div>
  );
}
