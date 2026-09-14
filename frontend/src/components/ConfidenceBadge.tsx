import type { Confidence } from '@/types';

const config: Record<Confidence, { bg: string; text: string; border: string; dot: string; label: string }> = {
  high: {
    bg: 'bg-conf-highBg dark:bg-green-950/50',
    text: 'text-conf-high dark:text-green-400',
    border: 'border-conf-highBorder dark:border-green-800',
    dot: 'bg-conf-high',
    label: 'High',
  },
  medium: {
    bg: 'bg-conf-medBg dark:bg-amber-950/50',
    text: 'text-conf-med dark:text-amber-400',
    border: 'border-conf-medBorder dark:border-amber-800',
    dot: 'bg-conf-med',
    label: 'Medium',
  },
  low: {
    bg: 'bg-conf-lowBg dark:bg-red-950/50',
    text: 'text-conf-low dark:text-red-400',
    border: 'border-conf-lowBorder dark:border-red-800',
    dot: 'bg-conf-low',
    label: 'Low',
  },
};

export function ConfidenceBadge({
  confidence,
  size = 'sm',
}: {
  confidence: Confidence;
  size?: 'sm' | 'md';
}) {
  const c = config[confidence];
  return (
    <span
      className={`badge-base ${c.bg} ${c.text} ${c.border} border ${size === 'md' ? 'px-3 py-1 text-sm' : ''}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
      {c.label} confidence
    </span>
  );
}
