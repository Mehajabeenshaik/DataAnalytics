import type { LucideIcon } from 'lucide-react';

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-4 animate-fade-in">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50 dark:bg-brand-950/50 mb-4">
        <Icon className="h-8 w-8 text-brand-500 dark:text-brand-400" />
      </div>
      <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200 mb-1">{title}</h3>
      <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">{description}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
