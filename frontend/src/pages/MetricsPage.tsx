import { useState, useMemo } from 'react';
import { Search, BarChart3, X, Check, Clock, ShieldCheck } from 'lucide-react';
import { metrics as initialMetrics } from '@/mock/data';
import { useApp } from '@/context/AppContext';
import type { Metric } from '@/types';

export function MetricsPage() {
  const { user } = useApp();
  const isAdmin = user?.role === 'admin';
  const [metrics, setMetrics] = useState(initialMetrics);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Metric | null>(null);

  const filtered = useMemo(() => {
    if (!search.trim()) return metrics;
    const q = search.toLowerCase();
    return metrics.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q) ||
        m.synonyms.some((s) => s.toLowerCase().includes(q))
    );
  }, [search, metrics]);

  const handleApprove = (id: string) => {
    setMetrics((prev) =>
      prev.map((m) => (m.id === id ? { ...m, status: 'Approved' as const } : m))
    );
    setSelected((prev) => (prev?.id === id ? { ...prev, status: 'Approved' as const } : prev));
  };

  const handleReject = (id: string) => {
    setMetrics((prev) => prev.filter((m) => m.id !== id));
    setSelected(null);
  };

  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200">Metrics Catalog</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Human-approved metrics the model can select from
        </p>
      </div>

      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="input-base pl-10"
          placeholder="Search metrics, synonyms, descriptions..."
        />
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
              <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Name</th>
              <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5 hidden md:table-cell">Description</th>
              <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5 hidden lg:table-cell">Synonyms</th>
              <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {filtered.map((metric) => (
              <tr
                key={metric.id}
                onClick={() => setSelected(metric)}
                className="hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer transition-colors"
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <BarChart3 className="h-4 w-4 text-brand-500 flex-shrink-0" />
                    <code className="font-mono text-xs font-medium text-slate-700 dark:text-slate-300">{metric.name}</code>
                  </div>
                </td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400 hidden md:table-cell max-w-xs truncate">
                  {metric.description}
                </td>
                <td className="px-4 py-3 hidden lg:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {metric.synonyms.slice(0, 3).map((s) => (
                      <span key={s} className="text-xs text-slate-400 bg-slate-100 dark:bg-slate-800 rounded px-1.5 py-0.5">
                        {s}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3">
                  {metric.status === 'Approved' ? (
                    <span className="badge-base bg-green-50 text-green-700 border border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800">
                      <Check className="h-3 w-3" /> Approved
                    </span>
                  ) : (
                    <span className="badge-base bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-950/50 dark:text-amber-400 dark:border-amber-800">
                      <Clock className="h-3 w-3" /> Pending
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Side drawer */}
      {selected && (
        <>
          <div
            className="fixed inset-0 bg-slate-900/40 z-40 backdrop-blur-sm animate-fade-in"
            onClick={() => setSelected(null)}
          />
          <div className="fixed right-0 top-0 bottom-0 w-full sm:w-96 bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 z-50 overflow-y-auto animate-slide-in-right">
            <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-800">
              <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Metric Details</h2>
              <button onClick={() => setSelected(null)} className="btn-ghost p-1">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-5 space-y-4">
              <div>
                <code className="text-sm font-mono font-semibold text-brand-600 dark:text-brand-400">{selected.name}</code>
              </div>

              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Description</p>
                <p className="text-sm text-slate-700 dark:text-slate-300">{selected.description}</p>
              </div>

              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Synonyms</p>
                <div className="flex flex-wrap gap-1.5">
                  {selected.synonyms.map((s) => (
                    <span key={s} className="badge-base bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400">
                      {s}
                    </span>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                  <p className="text-xs text-slate-500 dark:text-slate-400">Data type</p>
                  <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{selected.dataType}</p>
                </div>
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                  <p className="text-xs text-slate-500 dark:text-slate-400">Source</p>
                  <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{selected.sourceDataset}</p>
                </div>
              </div>

              {selected.formula && (
                <div>
                  <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Formula</p>
                  <code className="block text-xs font-mono rounded-lg bg-slate-100 dark:bg-slate-800 p-3 text-slate-700 dark:text-slate-300 overflow-x-auto">
                    {selected.formula}
                  </code>
                </div>
              )}

              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Status</p>
                {selected.status === 'Approved' ? (
                  <span className="badge-base bg-green-50 text-green-700 border border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800">
                    <ShieldCheck className="h-3 w-3" /> Approved
                  </span>
                ) : (
                  <span className="badge-base bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-950/50 dark:text-amber-400 dark:border-amber-800">
                    <Clock className="h-3 w-3" /> Pending approval
                  </span>
                )}
              </div>

              {isAdmin && selected.status === 'Pending' && (
                <div className="flex gap-2 pt-2 border-t border-slate-200 dark:border-slate-700">
                  <button onClick={() => handleApprove(selected.id)} className="btn-primary bg-green-600 hover:bg-green-700 flex-1">
                    <Check className="h-4 w-4" />
                    Approve
                  </button>
                  <button onClick={() => handleReject(selected.id)} className="btn-secondary text-red-600 border-red-300 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-950/30 flex-1">
                    <X className="h-4 w-4" />
                    Reject
                  </button>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
