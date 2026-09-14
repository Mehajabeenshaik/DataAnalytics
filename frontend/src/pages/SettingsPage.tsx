import { Sun, Moon, Building2, User as UserIcon, Mail, Check } from 'lucide-react';
import { useApp } from '@/context/AppContext';

export function SettingsPage() {
  const { user, tenant, tenants, setTenant, theme, setTheme } = useApp();

  if (!user) return null;

  return (
    <div className="p-4 sm:p-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200">Settings</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Manage your profile and preferences
        </p>
      </div>

      <div className="space-y-6">
        {/* Profile */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <UserIcon className="h-5 w-5 text-brand-600 dark:text-brand-400" />
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Profile</h2>
          </div>

          <div className="flex items-center gap-4 mb-4">
            <div
              className="flex h-16 w-16 items-center justify-center rounded-full text-white text-xl font-semibold"
              style={{ backgroundColor: user.avatarColor }}
            >
              {user.displayName.split(' ').map((n) => n[0]).join('')}
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{user.displayName}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">{user.email}</p>
              <span className="badge-base bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300 mt-1.5">
                {user.role}
              </span>
            </div>
          </div>

          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                Display name
              </label>
              <input className="input-base" defaultValue={user.displayName} />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                Email
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input className="input-base pl-10" defaultValue={user.email} readOnly />
              </div>
            </div>
          </div>
        </div>

        {/* Preferred tenant */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Building2 className="h-5 w-5 text-brand-600 dark:text-brand-400" />
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Preferred tenant</h2>
          </div>
          <div className="space-y-2">
            {tenants.map((t) => (
              <button
                key={t.id}
                onClick={() => setTenant(t.id)}
                className={`flex items-center justify-between w-full px-4 py-3 rounded-lg border transition-all ${
                  t.id === tenant.id
                    ? 'border-brand-300 bg-brand-50 dark:border-brand-700 dark:bg-brand-950/30'
                    : 'border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/50'
                }`}
              >
                <div className="flex items-center gap-3">
                  <Building2 className="h-4 w-4 text-slate-400" />
                  <div className="text-left">
                    <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{t.name}</p>
                    <p className="text-xs text-slate-400">{t.status} · {t.userCount} users</p>
                  </div>
                </div>
                {t.id === tenant.id && <Check className="h-4 w-4 text-brand-600" />}
              </button>
            ))}
          </div>
        </div>

        {/* Theme */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-4">Appearance</h2>
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => setTheme('light')}
              className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg border transition-all ${
                theme === 'light'
                  ? 'border-brand-300 bg-brand-50 dark:border-brand-700 dark:bg-brand-950/30 text-brand-700 dark:text-brand-300'
                  : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'
              }`}
            >
              <Sun className="h-4 w-4" />
              <span className="text-sm font-medium">Light</span>
            </button>
            <button
              onClick={() => setTheme('dark')}
              className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg border transition-all ${
                theme === 'dark'
                  ? 'border-brand-300 bg-brand-50 dark:border-brand-700 dark:bg-brand-950/30 text-brand-700 dark:text-brand-300'
                  : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'
              }`}
            >
              <Moon className="h-4 w-4" />
              <span className="text-sm font-medium">Dark</span>
            </button>
          </div>
        </div>

        <div className="flex justify-end">
          <button className="btn-primary">
            <Check className="h-4 w-4" />
            Save changes
          </button>
        </div>
      </div>
    </div>
  );
}
