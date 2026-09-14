import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { User, Tenant, PageId } from '@/types';
import { users, tenants } from '@/mock/data';

interface AppContextValue {
  user: User | null;
  tenant: Tenant;
  tenants: Tenant[];
  page: PageId;
  theme: 'light' | 'dark';
  setTheme: (t: 'light' | 'dark') => void;
  toggleTheme: () => void;
  login: (email: string) => boolean;
  logout: () => void;
  setTenant: (id: string) => void;
  setPage: (p: PageId) => void;
  restoreQuestion: (question: string) => void;
  restoredQuestion: string | null;
  clearRestoredQuestion: () => void;
  isDark: boolean;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [tenant, setTenantState] = useState<Tenant>(tenants[0]);
  const [page, setPage] = useState<PageId>('ask');
  const [theme, setThemeState] = useState<'light' | 'dark'>('light');
  const [restoredQuestion, setRestoredQuestion] = useState<string | null>(null);

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  const login = (email: string): boolean => {
    const found = users.find((u) => u.email === email) ?? users[0];
    setUser(found);
    const userTenant = tenants.find((t) => t.id === found.tenantId) ?? tenants[0];
    setTenantState(userTenant);
    setPage('ask');
    return true;
  };

  const logout = () => {
    setUser(null);
    setPage('ask');
  };

  const setTenant = (id: string) => {
    const t = tenants.find((t) => t.id === id);
    if (t) setTenantState(t);
  };

  const setTheme = (t: 'light' | 'dark') => setThemeState(t);
  const toggleTheme = () => setThemeState((p) => (p === 'light' ? 'dark' : 'light'));
  const restoreQuestion = (question: string) => setRestoredQuestion(question);
  const clearRestoredQuestion = () => setRestoredQuestion(null);


  return (
    <AppContext.Provider
      value={{
        user,
        tenant,
        tenants,
        page,
        theme,
        setTheme,
        toggleTheme,
        login,
        logout,
        setTenant,
        setPage,
        restoreQuestion,
        restoredQuestion,
        clearRestoredQuestion,
        isDark: theme === 'dark',
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}


