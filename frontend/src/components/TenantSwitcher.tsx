import { useState, useRef, useEffect } from 'react';
import { Building2, ChevronDown, Check } from 'lucide-react';
import type { Tenant } from '@/types';

export function TenantSwitcher({
  tenants,
  current,
  onSelect,
}: {
  tenants: Tenant[];
  current: Tenant;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 text-sm transition-all hover:bg-slate-50 dark:hover:bg-slate-800"
      >
        <Building2 className="h-4 w-4 text-slate-500" />
        <span className="font-medium text-slate-700 dark:text-slate-300 max-w-[140px] truncate">{current.name}</span>
        <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-1 w-56 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg z-50 animate-slide-up py-1">
          {tenants.map((t) => (
            <button
              key={t.id}
              onClick={() => {
                onSelect(t.id);
                setOpen(false);
              }}
              className="flex items-center justify-between w-full px-3 py-2 text-sm text-left hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              <div className="flex flex-col">
                <span className="font-medium text-slate-700 dark:text-slate-300">{t.name}</span>
                <span className="text-xs text-slate-400">{t.status} · {t.userCount} users</span>
              </div>
              {t.id === current.id && <Check className="h-4 w-4 text-brand-600" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
