export function QuotaMeter({
  used,
  total,
  label,
}: {
  used: number;
  total: number;
  label: string;
}) {
  const pct = Math.min((used / total) * 100, 100);
  const color = pct > 85 ? 'bg-red-500' : pct > 60 ? 'bg-amber-500' : 'bg-brand-500';

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-300">{label}</span>
        <span className="text-xs text-slate-500 dark:text-slate-400 font-mono">{used} / {total}</span>
      </div>
      <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-slate-400 mt-1">{Math.round(pct)}% used</p>
    </div>
  );
}
