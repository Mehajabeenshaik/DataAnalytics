import { Database, Upload, Table, Hash, ShieldCheck, RefreshCw, AlertCircle } from 'lucide-react';
import { datasets } from '@/mock/data';

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

const statusConfig = {
  Active: 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800',
  Syncing: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/50 dark:text-blue-400 dark:border-blue-800',
  Error: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-400 dark:border-red-800',
};

export function DatasetsPage() {
  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200">Datasets</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Registered data sources available to approved metrics
          </p>
        </div>
        <button className="btn-primary">
          <Upload className="h-4 w-4" />
          <span className="hidden sm:inline">Upload</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {datasets.map((ds) => (
          <div key={ds.id} className="card card-hover p-5 animate-fade-in">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 dark:bg-brand-950/50">
                  <Database className="h-5 w-5 text-brand-600 dark:text-brand-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">{ds.name}</h3>
                  <span className={`badge-base border ${statusConfig[ds.status]}`}>
                    {ds.status === 'Syncing' && <RefreshCw className="h-3 w-3 animate-spin" />}
                    {ds.status === 'Error' && <AlertCircle className="h-3 w-3" />}
                    {ds.status}
                  </span>
                </div>
              </div>
              {ds.piiMasked && (
                <span className="badge-base bg-teal-50 text-teal-700 border border-teal-200 dark:bg-teal-950/50 dark:text-teal-400 dark:border-teal-800">
                  <ShieldCheck className="h-3 w-3" />
                  PII masked
                </span>
              )}
            </div>

            <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">{ds.description}</p>

            <div className="grid grid-cols-2 gap-3 mb-3">
              <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 mb-1">
                  <Table className="h-3.5 w-3.5" />
                  Columns
                </div>
                <p className="text-lg font-semibold text-slate-800 dark:text-slate-200">{ds.columns}</p>
              </div>
              <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 mb-1">
                  <Hash className="h-3.5 w-3.5" />
                  Rows
                </div>
                <p className="text-lg font-semibold text-slate-800 dark:text-slate-200">
                  {ds.rows.toLocaleString()}
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="flex flex-wrap gap-1">
                {ds.tags.map((tag) => (
                  <span key={tag} className="text-xs text-slate-400 bg-slate-100 dark:bg-slate-800 rounded px-1.5 py-0.5">
                    {tag}
                  </span>
                ))}
              </div>
              <span className="text-xs text-slate-400">Updated {timeAgo(ds.lastUpdated)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
