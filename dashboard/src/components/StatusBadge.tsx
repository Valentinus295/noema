import { useDashboard } from '@/contexts/DashboardContext';
import type { SystemStatus } from '@/types';

export function StatusBadge() {
  const { state } = useDashboard();
  const status: SystemStatus = state.systemHealth?.status ?? 'red';
  const label = state.wsConnected
    ? status === 'green' ? 'OPERATIONAL' : status === 'yellow' ? 'DEGRADED' : 'DOWN'
    : 'DISCONNECTED';

  const colors: Record<SystemStatus, string> = {
    green: 'bg-status-green',
    yellow: 'bg-status-yellow',
    red: 'bg-status-red',
  };

  return (
    <div className="flex items-center gap-2">
      <span className={`inline-block w-2.5 h-2.5 rounded-full ${colors[state.wsConnected ? status : 'red']} ${state.wsConnected && status === 'green' ? 'animate-pulse-slow' : ''}`} />
      <span className="text-xs font-mono font-medium text-terminal-text">
        {label}
      </span>
    </div>
  );
}
