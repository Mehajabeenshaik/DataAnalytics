import { ShieldCheck, Info } from 'lucide-react';
import type { AskResponse } from '@/types';
import { ConfidenceBadge } from './ConfidenceBadge';
import { FlagChips } from './FlagChips';
import { LineageList } from './LineageList';

export function TrustPanel({ response }: { response: AskResponse }) {
  return (
    <div className="card p-5 sticky top-4 animate-slide-in-right">
      <div className="flex items-center gap-2 mb-4">
        <ShieldCheck className="h-5 w-5 text-brand-600 dark:text-brand-400" />
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Trust & Safety</h3>
      </div>

      <div className="space-y-4">
        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5">Confidence</p>
          <ConfidenceBadge confidence={response.confidence} size="md" />
        </div>

        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5">Plan type</p>
          <code className="text-xs font-mono rounded-md bg-slate-100 dark:bg-slate-800 px-2 py-1 text-brand-700 dark:text-brand-300">
            {response.plan_type}
          </code>
        </div>

        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-2">Lineage</p>
          <LineageList items={response.lineage} />
        </div>

        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-2">Safety flags</p>
          <FlagChips flags={response.flags} />
        </div>
      </div>

      <div className="mt-5 pt-4 border-t border-slate-200 dark:border-slate-700">
        <div className="flex items-start gap-2">
          <Info className="h-4 w-4 text-slate-400 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed italic">
            {response.invariant}
          </p>
        </div>
      </div>
    </div>
  );
}
