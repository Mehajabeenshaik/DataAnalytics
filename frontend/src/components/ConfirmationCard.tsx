import { ShieldAlert, Check, X } from 'lucide-react';
import type { AskResponse } from '@/types';

export function ConfirmationCard({
  response,
  onApprove,
  onReject,
}: {
  response: AskResponse;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <div className="rounded-xl border-2 border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/30 p-5 animate-slide-up">
      <div className="flex items-center gap-2 mb-3">
        <ShieldAlert className="h-5 w-5 text-amber-600 dark:text-amber-400" />
        <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-200">Confirmation required</h3>
      </div>

      {response.planSummary && (
        <p className="text-sm text-amber-800 dark:text-amber-300 leading-relaxed mb-4">
          {response.planSummary}
        </p>
      )}

      <div className="mb-4 space-y-1">
        <p className="text-xs font-medium text-amber-700 dark:text-amber-400">Plan type</p>
        <code className="text-xs font-mono rounded-md bg-amber-100 dark:bg-amber-900/50 px-2 py-1 text-amber-800 dark:text-amber-300">
          {response.plan_type}
        </code>
      </div>

      <div className="flex items-center gap-2">
        <button onClick={onApprove} className="btn-primary bg-green-600 hover:bg-green-700">
          <Check className="h-4 w-4" />
          Approve
        </button>
        <button onClick={onReject} className="btn-secondary border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/30">
          <X className="h-4 w-4" />
          Reject
        </button>
      </div>
    </div>
  );
}
