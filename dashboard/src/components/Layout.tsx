import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { useDashboard } from '@/contexts/DashboardContext';

export function Layout() {
  const { state } = useDashboard();

  return (
    <div className="flex min-h-screen bg-terminal-bg">
      <Sidebar />
      <main className="flex-1 overflow-x-hidden">
        {/* Error banner */}
        {state.error && (
          <div className="mx-4 mt-3 px-4 py-2 bg-red-500/10 border border-red-500/25 rounded-lg flex items-center justify-between animate-fade-in">
            <span className="text-sm text-red-400 font-mono">{state.error}</span>
            <button
              onClick={() => window.location.reload()}
              className="text-xs text-red-400 hover:text-red-300 ml-4"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Connection warning */}
        {!state.wsConnected && state.wsReconnectAttempt > 0 && (
          <div className="mx-4 mt-3 px-4 py-2 bg-amber-500/10 border border-amber-500/25 rounded-lg animate-fade-in">
            <span className="text-sm text-amber-400 font-mono">
              WebSocket disconnected — retrying ({state.wsReconnectAttempt}/20). Data may be stale.
            </span>
          </div>
        )}

        <Outlet />
      </main>
    </div>
  );
}
