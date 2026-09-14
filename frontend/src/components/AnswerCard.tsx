import { useState } from 'react';
import { Copy, Check, HelpCircle, AlertTriangle } from 'lucide-react';
import type { AskResponse, ChartDatum } from '@/types';
import { ConfidenceBadge } from './ConfidenceBadge';

function BarChart({ data, title }: { data: ChartDatum[]; title: string }) {
  const max = Math.max(...data.map((d) => d.value));
  return (
    <div className="mt-4">
      <p className="mb-3 text-xs font-medium text-slate-500">{title}</p>
      <div className="flex items-end gap-3 h-40">
        {data.map((d, i) => (
          <div key={i} className="flex-1 flex flex-col items-center gap-1.5">
            <div className="w-full flex-1 flex items-end">
              <div
                className="w-full rounded-t-md bg-brand-500 dark:bg-brand-600 transition-all hover:bg-brand-600 dark:hover:bg-brand-500 animate-slide-up group relative"
                style={{ height: `${(d.value / max) * 100}%`, animationDelay: `${i * 80}ms` }}
              >
                <span className="absolute -top-6 left-1/2 -translate-x-1/2 text-xs font-medium text-slate-600 dark:text-slate-300 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
                  ${d.value.toLocaleString()}
                </span>
              </div>
            </div>
            <span className="text-xs text-slate-500 dark:text-slate-400 truncate w-full text-center">{d.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function LineChart({ data, title }: { data: ChartDatum[]; title: string }) {
  const max = Math.max(...data.map((d) => d.value));
  const min = Math.min(...data.map((d) => d.value));
  const range = max - min || 1;
  const width = 100;
  const height = 100;
  const points = data
    .map((d, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((d.value - min) / range) * height;
      return `${x},${y}`;
    })
    .join(' ');
  const areaPoints = `0,${height} ${points} ${width},${height}`;

  return (
    <div className="mt-4">
      <p className="mb-3 text-xs font-medium text-slate-500">{title}</p>
      <div className="relative h-40">
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="w-full h-full">
          <defs>
            <linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity="0.2" />
              <stop offset="100%" stopColor="#6366f1" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={areaPoints} fill="url(#lineGrad)" />
          <polyline
            points={points}
            fill="none"
            stroke="#6366f1"
            strokeWidth="1.5"
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
          {data.map((d, i) => {
            const x = (i / (data.length - 1)) * width;
            const y = height - ((d.value - min) / range) * height;
            return <circle key={i} cx={x} cy={y} r="1.2" fill="#6366f1" />;
          })}
        </svg>
      </div>
      <div className="flex justify-between mt-2">
        {data.map((d, i) => (
          <span key={i} className="text-xs text-slate-500 dark:text-slate-400">{d.label}</span>
        ))}
      </div>
    </div>
  );
}

export function AnswerCard({ response, onWhy }: { response: AskResponse; onWhy?: () => void }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(response.answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="card p-5 animate-slide-up">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex items-center gap-2">
          <ConfidenceBadge confidence={response.confidence} size="md" />
          <span className="text-xs text-slate-400 font-mono">{response.plan_type}</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={handleCopy} className="btn-ghost text-xs" title="Copy answer">
            {copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? 'Copied' : 'Copy'}
          </button>
          {onWhy && (
            <button onClick={onWhy} className="btn-ghost text-xs" title="Why this answer?">
              <HelpCircle className="h-3.5 w-3.5" />
              Why this answer?
            </button>
          )}
        </div>
      </div>

      <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-300">{response.answer}</p>

      {response.chart && (
        <div className="mt-2">
          {response.chart.type === 'bar' ? (
            <BarChart data={response.chart.data} title={response.chart.title} />
          ) : (
            <LineChart data={response.chart.data} title={response.chart.title} />
          )}
        </div>
      )}

      {response.keyNumbers && response.keyNumbers.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {response.keyNumbers.map((kn, i) => (
            <div
              key={i}
              className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 px-3 py-2"
            >
              <p className="text-xs text-slate-500 dark:text-slate-400">{kn.label}</p>
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{kn.value}</p>
            </div>
          ))}
        </div>
      )}

      {response.caveat && (
        <div className="mt-4 flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 px-3 py-2">
          <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-amber-800 dark:text-amber-300">{response.caveat}</p>
        </div>
      )}
    </div>
  );
}


