import { Check, Loader2, Circle } from 'lucide-react';

interface Step {
  label: string;
  status: 'done' | 'active' | 'pending';
}

export function StatusStepper({ steps }: { steps: Step[] }) {
  return (
    <div className="card p-5 animate-fade-in">
      <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-4">Processing your question</p>
      <div className="space-y-0">
        {steps.map((step, i) => (
          <div key={i} className="flex items-center gap-3 relative">
            <div className="flex flex-col items-center">
              <div className="flex h-7 w-7 items-center justify-center rounded-full transition-all">
                {step.status === 'done' && (
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-green-100 dark:bg-green-950/50">
                    <Check className="h-4 w-4 text-green-600 dark:text-green-400" />
                  </span>
                )}
                {step.status === 'active' && (
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-100 dark:bg-brand-950/50">
                    <Loader2 className="h-4 w-4 text-brand-600 dark:text-brand-400 animate-spin" />
                  </span>
                )}
                {step.status === 'pending' && (
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-100 dark:bg-slate-800">
                    <Circle className="h-3 w-3 text-slate-400" />
                  </span>
                )}
              </div>
              {i < steps.length - 1 && (
                <div
                  className={`w-0.5 h-8 ${
                    step.status === 'done' ? 'bg-green-300 dark:bg-green-800' : 'bg-slate-200 dark:bg-slate-700'
                  }`}
                />
              )}
            </div>
            <span
              className={`text-sm pb-8 ${
                step.status === 'active'
                  ? 'font-medium text-brand-700 dark:text-brand-300'
                  : step.status === 'done'
                  ? 'text-slate-600 dark:text-slate-400'
                  : 'text-slate-400 dark:text-slate-600'
              }`}
            >
              {step.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
