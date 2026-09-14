import { Database, Wrench, BarChart3 } from 'lucide-react';
import type { LineageItem } from '@/types';

const kindConfig = {
  metric: { icon: BarChart3, label: 'Metric', color: 'text-brand-600 dark:text-brand-400' },
  tool: { icon: Wrench, label: 'Tool', color: 'text-slate-600 dark:text-slate-400' },
  dataset: { icon: Database, label: 'Dataset', color: 'text-teal-600 dark:text-teal-400' },
};

export function LineageList({ items }: { items: LineageItem[] }) {
  if (!items || items.length === 0) {
    return <p className="text-sm text-slate-400">No lineage recorded</p>;
  }

  return (
    <ul className="space-y-2">
      {items.map((item, i) => {
        const cfg = kindConfig[item.kind];
        const Icon = cfg.icon;
        return (
          <li key={i} className="flex items-center gap-2.5 text-sm animate-fade-in" style={{ animationDelay: `${i * 60}ms` }}>
            <span className={`flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800 ${cfg.color}`}>
              <Icon className="h-3.5 w-3.5" />
            </span>
            <div className="flex flex-col">
              <span className="font-medium text-slate-800 dark:text-slate-200">{item.name}</span>
              <span className="text-xs text-slate-400">{cfg.label}</span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
