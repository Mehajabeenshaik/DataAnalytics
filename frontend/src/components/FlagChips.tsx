import { AlertTriangle, ShieldAlert, Flag, ClockAlert } from 'lucide-react';
import type { Flag as FlagType } from '@/types';

const iconMap = {
  pii_risk: ShieldAlert,
  metric_pending: Flag,
  unknown_metric: ShieldAlert,
  quota_warning: ClockAlert,
  rate_limit: AlertTriangle,
};

const styleMap = {
  warning: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-400 dark:border-amber-800',
  critical: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-400 dark:border-red-800',
};

export function FlagChips({ flags }: { flags: FlagType[] }) {
  if (!flags || flags.length === 0) {
    return (
      <span className="badge-base bg-green-50 text-green-700 border border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800">
        No safety flags
      </span>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {flags.map((flag, i) => {
        const Icon = iconMap[flag.type] ?? AlertTriangle;
        return (
          <span
            key={i}
            className={`badge-base ${styleMap[flag.severity]} border`}
          >
            <Icon className="h-3 w-3" />
            {flag.label}
          </span>
        );
      })}
    </div>
  );
}
