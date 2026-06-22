import { NavLink } from 'react-router-dom';
import { StatusBadge } from './StatusBadge';
import { useDashboard } from '@/contexts/DashboardContext';

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/agents', label: 'Agents', icon: '🤖' },
  { to: '/trades', label: 'Trades', icon: '📈' },
  { to: '/risk', label: 'Risk', icon: '🛡️' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
];

export function Sidebar() {
  const { state } = useDashboard();

  return (
    <aside className="w-56 bg-terminal-surface border-r border-terminal-border flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-terminal-border">
        <div className="flex items-center gap-2">
          <span className="text-xl">🧠</span>
          <div>
            <h1 className="text-sm font-bold text-terminal-bright tracking-wide">NOEMA</h1>
            <p className="text-2xs text-terminal-muted font-mono">Trading Desk</p>
          </div>
        </div>
      </div>

      {/* Status */}
      <div className="px-4 py-3 border-b border-terminal-border">
        <StatusBadge />
        {!state.wsConnected && (
          <p className="text-2xs text-trade-loss mt-1 font-mono">
            WS reconnect #{state.wsReconnectAttempt}…
          </p>
        )}
        {state.systemHealth && (
          <p className="text-2xs text-terminal-muted mt-1 font-mono">
            v{state.systemHealth.version} · {state.systemHealth.activeAgents}/{state.systemHealth.totalAgents} agents
          </p>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600/15 text-blue-400 font-medium'
                  : 'text-terminal-text hover:bg-terminal-border/50 hover:text-terminal-bright'
              }`
            }
          >
            <span className="text-base">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-terminal-border">
        <p className="text-2xs text-terminal-muted font-mono">
          {state.lastUpdate
            ? `Last update: ${new Date(state.lastUpdate).toLocaleTimeString()}`
            : 'Waiting for data…'}
        </p>
      </div>
    </aside>
  );
}
