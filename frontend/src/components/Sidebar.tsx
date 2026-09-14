import {
  MessageCircle,
  History,
  BarChart3,
  Database,
  ShieldCheck,
  Settings2,
  Cog,
  Shield,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { PageId } from '@/types';
import { useApp } from '@/context/AppContext';

interface NavItem {
  id: PageId;
  label: string;
  icon: LucideIcon;
  adminOnly?: boolean;
}

const navItems: NavItem[] = [
  { id: 'ask', label: 'Ask', icon: MessageCircle },
  { id: 'history', label: 'History', icon: History },
  { id: 'metrics', label: 'Metrics', icon: BarChart3 },
  { id: 'datasets', label: 'Datasets', icon: Database },
  { id: 'audit', label: 'Audit', icon: ShieldCheck, adminOnly: true },
  { id: 'admin', label: 'Admin', icon: Cog, adminOnly: true },
  { id: 'settings', label: 'Settings', icon: Settings2 },
];

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { page, setPage, user } = useApp();
  const isAdmin = user?.role === 'admin';

  const visibleItems = navItems.filter((item) => !item.adminOnly || isAdmin);

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 bg-slate-900/40 z-30 lg:hidden backdrop-blur-sm animate-fade-in"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed lg:sticky top-0 left-0 z-40 h-screen w-60 flex flex-col border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 transition-transform duration-200 ${
          open ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="flex items-center justify-between px-4 h-14 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
              <Shield className="h-5 w-5" />
            </div>
            <span className="text-lg font-bold tracking-tight text-slate-800 dark:text-slate-200">
              DaAna
            </span>
          </div>
          <button onClick={onClose} className="lg:hidden btn-ghost p-1">
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {visibleItems.map((item) => {
            const Icon = item.icon;
            const isActive = page === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  setPage(item.id);
                  onClose();
                }}
                className={`nav-item w-full ${isActive ? 'nav-item-active' : ''}`}
              >
                <Icon className="h-4 w-4 flex-shrink-0" />
                <span>{item.label}</span>
                {item.adminOnly && (
                  <Shield className="h-3 w-3 ml-auto text-slate-400" />
                )}
              </button>
            );
          })}
        </nav>

        <div className="px-3 py-4 border-t border-slate-200 dark:border-slate-800">
          <div className="rounded-lg bg-slate-50 dark:bg-slate-800/50 p-3">
            <div className="flex items-center gap-2 mb-1">
              <ShieldCheck className="h-4 w-4 text-green-600" />
              <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">Governed Mode</span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
              No SQL execution by the model
            </p>
          </div>
        </div>
      </aside>
    </>
  );
}
