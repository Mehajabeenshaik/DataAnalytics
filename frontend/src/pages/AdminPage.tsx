import { useState } from 'react';
import {
  Building2,
  Gauge,
  KeyRound,
  Activity,
  Plus,
  Check,
  X,
  Copy,
  CheckCheck,
  Heart,
  Zap,
} from 'lucide-react';
import { tenants as initialTenants, apiKeys, systemHealth } from '@/mock/data';
import { QuotaMeter } from '@/components/QuotaMeter';

type Tab = 'tenants' | 'quotas' | 'apikeys' | 'health';

const tabs: { id: Tab; label: string; icon: typeof Building2 }[] = [
  { id: 'tenants', label: 'Tenants', icon: Building2 },
  { id: 'quotas', label: 'Quotas', icon: Gauge },
  { id: 'apikeys', label: 'API Keys', icon: KeyRound },
  { id: 'health', label: 'System Health', icon: Activity },
];

export function AdminPage() {
  const [tab, setTab] = useState<Tab>('tenants');
  const [tenants, setTenants] = useState(initialTenants);
  const [showCreateTenant, setShowCreateTenant] = useState(false);
  const [newTenantName, setNewTenantName] = useState('');
  const [showCreateKey, setShowCreateKey] = useState(false);
  const [newKeyLabel, setNewKeyLabel] = useState('');
  const [newKeySecret, setNewKeySecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleCreateTenant = () => {
    if (!newTenantName.trim()) return;
    setTenants((prev) => [
      ...prev,
      {
        id: `t${Date.now()}`,
        name: newTenantName,
        status: 'Provisioning',
        userCount: 0,
        createdAt: Date.now(),
      },
    ]);
    setNewTenantName('');
    setShowCreateTenant(false);
  };

  const handleCreateKey = () => {
    if (!newKeyLabel.trim()) return;
    const secret = `daana_live_${Math.random().toString(36).substring(2, 10)}${Math.random().toString(36).substring(2, 10)}`;
    setNewKeySecret(secret);
    setNewKeyLabel('');
    setShowCreateKey(false);
  };

  const handleCopySecret = () => {
    if (newKeySecret) {
      navigator.clipboard.writeText(newKeySecret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200">Admin</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Manage tenants, quotas, API keys, and system health
        </p>
      </div>

      <div className="flex gap-1 mb-6 border-b border-slate-200 dark:border-slate-800 overflow-x-auto">
        {tabs.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all whitespace-nowrap ${
                tab === t.id
                  ? 'border-brand-600 text-brand-700 dark:text-brand-400'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
              }`}
            >
              <Icon className="h-4 w-4" />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tenants */}
      {tab === 'tenants' && (
        <div className="animate-fade-in">
          <div className="flex justify-end mb-4">
            <button onClick={() => setShowCreateTenant(true)} className="btn-primary">
              <Plus className="h-4 w-4" />
              New tenant
            </button>
          </div>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
                  <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Name</th>
                  <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Status</th>
                  <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5 hidden sm:table-cell">Users</th>
                  <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5 hidden md:table-cell">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {tenants.map((t) => (
                  <tr key={t.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Building2 className="h-4 w-4 text-slate-400" />
                        <span className="font-medium text-slate-700 dark:text-slate-300">{t.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`badge-base border ${
                          t.status === 'Active'
                            ? 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800'
                            : t.status === 'Provisioning'
                            ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/50 dark:text-blue-400 dark:border-blue-800'
                            : 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-400 dark:border-red-800'
                        }`}
                      >
                        {t.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400 hidden sm:table-cell">{t.userCount}</td>
                    <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400 hidden md:table-cell">
                      {new Date(t.createdAt).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Quotas */}
      {tab === 'quotas' && (
        <div className="animate-fade-in space-y-4">
          <div className="card p-5">
            <div className="flex items-center gap-2 mb-4">
              <Gauge className="h-5 w-5 text-brand-600 dark:text-brand-400" />
              <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Tenant Quotas</h2>
            </div>
            <div className="space-y-5">
              <QuotaMeter used={42} total={100} label="Acme Analytics — daily queries" />
              <QuotaMeter used={15} total={50} label="Demo Tenant — daily queries" />
              <QuotaMeter used={0} total={25} label="Staging Corp — daily queries" />
            </div>
          </div>

          <div className="card p-5">
            <div className="flex items-center gap-2 mb-4">
              <Zap className="h-5 w-5 text-brand-600 dark:text-brand-400" />
              <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">System Quotas</h2>
            </div>
            <div className="space-y-5">
              <QuotaMeter used={8432} total={10000} label="Monthly API calls" />
              <QuotaMeter used={57} total={100} label="Concurrent sessions" />
              <QuotaMeter used={128} total={500} label="Stored metrics" />
            </div>
          </div>
        </div>
      )}

      {/* API Keys */}
      {tab === 'apikeys' && (
        <div className="animate-fade-in">
          <div className="flex justify-end mb-4">
            <button onClick={() => setShowCreateKey(true)} className="btn-primary">
              <Plus className="h-4 w-4" />
              New API key
            </button>
          </div>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
                  <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Label</th>
                  <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Prefix</th>
                  <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5 hidden sm:table-cell">Created</th>
                  <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5 hidden md:table-cell">Last used</th>
                  <th className="text-left font-medium text-slate-500 dark:text-slate-400 px-4 py-2.5">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {apiKeys.map((key) => (
                  <tr key={key.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-slate-700 dark:text-slate-300">{key.label}</td>
                    <td className="px-4 py-3">
                      <code className="text-xs font-mono text-slate-500 dark:text-slate-400">{key.prefix}••••••••</code>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400 hidden sm:table-cell">
                      {new Date(key.createdAt).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400 hidden md:table-cell">
                      {key.lastUsed ? new Date(key.lastUsed).toLocaleDateString() : 'Never'}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`badge-base border ${
                          key.status === 'Active'
                            ? 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800'
                            : 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-400 dark:border-red-800'
                        }`}
                      >
                        {key.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* System Health */}
      {tab === 'health' && (
        <div className="animate-fade-in space-y-4">
          {systemHealth.map((h) => (
            <div key={h.endpoint} className="card p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-50 dark:bg-green-950/50">
                    <Heart className="h-5 w-5 text-green-600 dark:text-green-400" />
                  </div>
                  <div>
                    <code className="text-sm font-mono font-semibold text-slate-800 dark:text-slate-200">{h.endpoint}</code>
                    <p className="text-xs text-slate-500 dark:text-slate-400">{h.detail}</p>
                  </div>
                </div>
                <span className="badge-base bg-green-50 text-green-700 border border-green-200 dark:bg-green-950/50 dark:text-green-400 dark:border-green-800 text-sm px-3 py-1">
                  <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse-soft" />
                  {h.status}
                </span>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                  <p className="text-xs text-slate-500 dark:text-slate-400">Phase</p>
                  <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">{h.phase}</p>
                </div>
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                  <p className="text-xs text-slate-500 dark:text-slate-400">Isolation</p>
                  <p className="text-sm font-semibold text-green-600 dark:text-green-400">
                    {h.isolation ? 'Enabled' : 'Disabled'}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 col-span-2 md:col-span-1">
                  <p className="text-xs text-slate-500 dark:text-slate-400">Invariant</p>
                  <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">{h.invariantSnippet}</p>
                </div>
              </div>
            </div>
          ))}

          <div className="card p-5 bg-brand-50 dark:bg-brand-950/30 border-brand-200 dark:border-brand-800">
            <p className="text-xs font-mono text-brand-700 dark:text-brand-300 leading-relaxed">
              invariant: LLM executes 0 SQL, 0 Python — only metric/tool dispatch
            </p>
          </div>
        </div>
      )}

      {/* Create tenant modal */}
      {showCreateTenant && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fade-in" onClick={() => setShowCreateTenant(false)}>
          <div className="card p-6 w-full max-w-sm animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-4">Create new tenant</h3>
            <input
              value={newTenantName}
              onChange={(e) => setNewTenantName(e.target.value)}
              className="input-base mb-4"
              placeholder="Tenant name"
              autoFocus
            />
            <div className="flex gap-2">
              <button onClick={handleCreateTenant} className="btn-primary flex-1">Create</button>
              <button onClick={() => setShowCreateTenant(false)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Create API key modal */}
      {showCreateKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fade-in" onClick={() => setShowCreateKey(false)}>
          <div className="card p-6 w-full max-w-sm animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-4">Create API key</h3>
            <input
              value={newKeyLabel}
              onChange={(e) => setNewKeyLabel(e.target.value)}
              className="input-base mb-4"
              placeholder="Key label (e.g. Production API)"
              autoFocus
            />
            <div className="flex gap-2">
              <button onClick={handleCreateKey} className="btn-primary flex-1">Generate</button>
              <button onClick={() => setShowCreateKey(false)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Show secret modal */}
      {newKeySecret && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fade-in" onClick={() => setNewKeySecret(null)}>
          <div className="card p-6 w-full max-w-md animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-3">
              <CheckCheck className="h-5 w-5 text-green-600" />
              <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">API key created</h3>
            </div>
            <p className="text-xs text-amber-600 dark:text-amber-400 mb-3">
              Copy this secret now — it won't be shown again.
            </p>
            <div className="flex items-center gap-2 rounded-lg bg-slate-100 dark:bg-slate-800 p-3 mb-4">
              <code className="flex-1 text-xs font-mono text-slate-700 dark:text-slate-300 break-all">{newKeySecret}</code>
              <button onClick={handleCopySecret} className="btn-ghost p-1.5 flex-shrink-0">
                {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
              </button>
            </div>
            <button onClick={() => setNewKeySecret(null)} className="btn-primary w-full">Done</button>
          </div>
        </div>
      )}
    </div>
  );
}
