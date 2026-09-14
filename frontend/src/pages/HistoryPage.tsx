import { useState, useMemo } from 'react';
import { Search, History as HistoryIcon, ArrowRight } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { historyEntries } from '@/mock/data';
import { ConfidenceBadge } from '@/components/ConfidenceBadge';
import { EmptyState } from '@/components/EmptyState';

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

export function HistoryPage() {
  const { setPage, restoreQuestion } = useApp();
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search.trim()) return historyEntries;
    const q = search.toLowerCase();
    return historyEntries.filter(
      (e) => e.question.toLowerCase().includes(q) || e.tenant.toLowerCase().includes(q)
    );
  }, [search]);

  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200">History</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Past questions across your tenant
        </p>
      </div>

      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="input-base pl-10"
          placeholder="Search past questions..."
        />
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={HistoryIcon}
          title="No results found"
          description="Try a different search term, or ask a new question."
          action={
            <button onClick={() => setPage('ask')} className="btn-primary">
              Go to Ask
              <ArrowRight className="h-4 w-4" />
            </button>
          }
        />
      ) : (
        <div className="card divide-y divide-slate-200 dark:divide-slate-800 overflow-hidden">
          {filtered.map((entry) => (
            <button
              key={entry.id}
              onClick={() => { restoreQuestion(entry.question); setPage('ask'); }}
              className="flex items-center justify-between w-full px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors text-left group"
            >
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800 flex-shrink-0">
                  <HistoryIcon className="h-4 w-4 text-slate-500" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">
                    {entry.question}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {entry.tenant} · {timeAgo(entry.timestamp)} · {entry.planType}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                {entry.confidence && <ConfidenceBadge confidence={entry.confidence} />}
                <ArrowRight className="h-4 w-4 text-slate-300 group-hover:text-brand-500 transition-colors" />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
