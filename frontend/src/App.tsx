import { useState } from 'react';
import { AppProvider, useApp } from '@/context/AppContext';
import { Sidebar } from '@/components/Sidebar';
import { TopBar } from '@/components/TopBar';
import { LoginPage } from '@/pages/LoginPage';
import { AskPage } from '@/pages/AskPage';
import { HistoryPage } from '@/pages/HistoryPage';
import { MetricsPage } from '@/pages/MetricsPage';
import { DatasetsPage } from '@/pages/DatasetsPage';
import { AuditPage } from '@/pages/AuditPage';
import { AdminPage } from '@/pages/AdminPage';
import { SettingsPage } from '@/pages/SettingsPage';

function AppShell() {
  const { user, page } = useApp();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (!user) {
    return <LoginPage />;
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50 dark:bg-slate-950">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <TopBar onMenuClick={() => setSidebarOpen(true)} />
        <main className="flex-1 overflow-y-auto">
          {page === 'ask' && <AskPage />}
          {page === 'history' && <HistoryPage />}
          {page === 'metrics' && <MetricsPage />}
          {page === 'datasets' && <DatasetsPage />}
          {page === 'audit' && <AuditPage />}
          {page === 'admin' && <AdminPage />}
          {page === 'settings' && <SettingsPage />}
        </main>
      </div>
    </div>
  );
}

function App() {
  return (
    <AppProvider>
      <AppShell />
    </AppProvider>
  );
}

export default App;
