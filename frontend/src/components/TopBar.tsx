import { useState, useRef, useEffect } from 'react';
import { Menu, Sun, Moon, User, Settings, LogOut, ChevronDown } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { TenantSwitcher } from './TenantSwitcher';
import { EnvBadge } from './EnvBadge';

export function TopBar({ onMenuClick }: { onMenuClick: () => void }) {
  const { user, tenant, tenants, setTenant, logout, setPage, theme, toggleTheme } = useApp();
  const [menuOpen, setMenuOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (!user) return null;

  return (
    <header className="sticky top-0 z-20 h-14 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm flex items-center justify-between px-4">
      <div className="flex items-center gap-3">
        <button onClick={onMenuClick} className="lg:hidden btn-ghost p-1.5">
          <Menu className="h-5 w-5" />
        </button>

        <div className="hidden sm:flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-800 dark:text-slate-200">DaAna</span>
          <span className="text-slate-300 dark:text-slate-600">/</span>
          <span className="text-sm text-slate-500 dark:text-slate-400">Console</span>
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3">
        <EnvBadge env="Development" />

        <TenantSwitcher tenants={tenants} current={tenant} onSelect={setTenant} />

        <button
          onClick={toggleTheme}
          className="btn-ghost p-1.5"
          title="Toggle theme"
        >
          {theme === 'light' ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
        </button>

        <div className="relative" ref={ref}>
          <button
            onClick={() => setMenuOpen((o) => !o)}
            className="flex items-center gap-2 rounded-lg pl-1.5 pr-2 py-1 transition-all hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <div
              className="flex h-7 w-7 items-center justify-center rounded-full text-white text-xs font-semibold"
              style={{ backgroundColor: user.avatarColor }}
            >
              {user.displayName.split(' ').map((n) => n[0]).join('')}
            </div>
            <span className="hidden sm:block text-sm font-medium text-slate-700 dark:text-slate-300 max-w-[100px] truncate">
              {user.displayName}
            </span>
            <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform ${menuOpen ? 'rotate-180' : ''}`} />
          </button>

          {menuOpen && (
            <div className="absolute top-full right-0 mt-1 w-52 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg z-50 animate-slide-up py-1">
              <div className="px-3 py-2 border-b border-slate-200 dark:border-slate-700">
                <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{user.displayName}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400">{user.email}</p>
                <span className="badge-base bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300 mt-1.5">
                  {user.role}
                </span>
              </div>
              <button
                onClick={() => { setPage('settings'); setMenuOpen(false); }}
                className="flex items-center gap-2 w-full px-3 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors text-left"
              >
                <User className="h-4 w-4 text-slate-400" />
                Profile
              </button>
              <button
                onClick={() => { setPage('settings'); setMenuOpen(false); }}
                className="flex items-center gap-2 w-full px-3 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors text-left"
              >
                <Settings className="h-4 w-4 text-slate-400" />
                Settings
              </button>
              <div className="border-t border-slate-200 dark:border-slate-700 my-1" />
              <button
                onClick={logout}
                className="flex items-center gap-2 w-full px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors text-left"
              >
                <LogOut className="h-4 w-4" />
                Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
