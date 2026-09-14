import { useState, Fragment } from 'react';
import { ChevronDown, ChevronRight, AlertTriangle, ShieldCheck, Search } from 'lucide-react';
import { auditEntries } from '@/mock/data';
import { ConfidenceBadge } from '@/components/ConfidenceBadge';
import { FlagChips } from '@/components/FlagChips';

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

export function AuditPage() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [showMismatches, setShowMismatches] = useState(false);

  const filtered = auditEntries.filter((e) => {
    if (showMismatches && !e.hasMismatch) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return e.question.toLowerCase().includes(q) || e.tenant.toLowerCase().includes(q);
    }
    return true;
  });

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200">Audit Log</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Every query with claimed vs. observed tool verification
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input-base pl-10"
            placeholder="Search questions or tenants..."
          />
        </div>
        <button
          onClick={() => setShowMismatches((v) => !v)}
          className={showMismatches ? 'btn-primary' : 'btn-secondary'}
        >
          <AlertTriangle className="h-4 w-4" />
          {showMismatches ? 'Showing mismatches' : 'Show mismatches only'}
        </button>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
                <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5 w-8"></th>
                <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Time</th>
                <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Tenant</th>
                <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Question</th>
                <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5 hidden md:table-cell">Plan</th>
                <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Confidence</th>
                <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5 hidden lg:table-cell">Flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {filtered.map((entry) => (
                <Fragment key={entry.id}>
                  <tr
                    onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}
                    className={`hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer transition-colors ${
                      entry.hasMismatch ? 'bg-red-50/50 dark:bg-red-950/20' : ''
                    }`}
                  >
                    <td className="px-4 py-3">
                      {expanded === entry.id ? (
                        <ChevronDown className="h-4 w-4 text-slate-400" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-slate-400" />
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {timeAgo(entry.time)}
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400 whitespace-nowrap">{entry.tenant}</td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300 max-w-xs truncate">{entry.question}</td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      <code className="text-xs font-mono text-slate-500 dark:text-slate-400">{entry.planType}</code>
                    </td>
                    <td className="px-4 py-3">
                      <ConfidenceBadge confidence={entry.confidence} />
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      {entry.hasMismatch ? (
                        <span className="badge-base bg-red-50 text-red-700 border border-red-200 dark:bg-red-950/50 dark:text-red-400 dark:border-red-800">
                          <AlertTriangle className="h-3 w-3" />
                          Mismatch
                        </span>
                      ) : entry.flags.length === 0 ? (
                        <span className="badge-base bg-green-50 text-green-700 border border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800">
                          <ShieldCheck className="h-3 w-3" />
                          Clean
                        </span>
                      ) : (
                        <FlagChips flags={entry.flags} />
                      )}
                    </td>
                  </tr>
                  {expanded === entry.id && (
                    <tr className="bg-slate-50 dark:bg-slate-800/30">
                      <td colSpan={7} className="px-4 py-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 ml-8">
                          <div>
                            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2">
                              Claimed tools
                            </p>
                            <div className="flex flex-wrap gap-1.5">
                              {entry.claimedTools.length > 0 ? (
                                entry.claimedTools.map((t) => (
                                  <span key={t} className="badge-base bg-blue-50 text-blue-700 border border-blue-200 dark:bg-blue-950/50 dark:text-blue-400 dark:border-blue-800">
                                    {t}
                                  </span>
                                ))
                              ) : (
                                <span className="text-xs text-slate-400">None claimed</span>
                              )}
                            </div>
                          </div>
                          <div>
                            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2">
                              Observed tools
                            </p>
                            <div className="flex flex-wrap gap-1.5">
                              {entry.observedTools.length > 0 ? (
                                entry.observedTools.map((t) => (
                                  <span
                                    key={t}
                                    className={`badge-base border ${
                                      entry.hasMismatch && !entry.claimedTools.includes(t)
                                        ? 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-400 dark:border-red-800'
                                        : 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800'
                                    }`}
                                  >
                                    {t}
                                  </span>
                                ))
                              ) : (
                                <span className="text-xs text-slate-400">None observed</span>
                              )}
                            </div>
                          </div>
                          {entry.hasMismatch && (
                            <div className="md:col-span-2 flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 p-3">
                              <AlertTriangle className="h-4 w-4 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
                              <p className="text-xs text-red-800 dark:text-red-300">
                                Tool mismatch detected: observed tools do not match claimed tools. This may indicate a policy violation or an unresolved metric access.
                              </p>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
