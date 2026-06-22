import { useMemo, useState } from 'react';
import { useDashboard } from '@/contexts/DashboardContext';
import { PIPELINE_PHASES, PHASE_LABELS } from '@/types';
import type { AgentInfo, PipelinePhase, AgentState } from '@/types';
import { formatRelativeTime, formatTimestamp } from '@/utils/format';

const STATE_COLORS: Record<AgentState, string> = {
  active: 'bg-emerald-500',
  idle: 'bg-slate-500',
  error: 'bg-red-500',
  offline: 'bg-slate-700',
};

const STATE_LABELS: Record<AgentState, string> = {
  active: 'Active',
  idle: 'Idle',
  error: 'Error',
  offline: 'Offline',
};

const STATE_BADGE: Record<AgentState, string> = {
  active: 'badge-green',
  idle: 'badge-neutral',
  error: 'badge-red',
  offline: 'badge-neutral',
};

function AgentCard({ agent }: { agent: AgentInfo }) {
  return (
    <div className="card hover:border-terminal-muted/50 transition-colors">
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`inline-block w-2 h-2 rounded-full ${STATE_COLORS[agent.state]} ${agent.state === 'active' ? 'animate-pulse-slow' : ''}`} />
          <span className="text-sm font-medium text-terminal-bright">{agent.name}</span>
        </div>
        <span className={`badge ${STATE_BADGE[agent.state]}`}>{STATE_LABELS[agent.state]}</span>
      </div>

      <div className="space-y-1 text-2xs font-mono">
        <div className="flex justify-between">
          <span className="text-terminal-muted">Layer</span>
          <span className="text-terminal-text">{agent.layer}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-terminal-muted">Type</span>
          <span className="text-terminal-text">{agent.type.toUpperCase()}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-terminal-muted">Phase</span>
          <span className="text-terminal-text">{PHASE_LABELS[agent.phase]}</span>
        </div>
        {agent.executionTimeMs !== null && (
          <div className="flex justify-between">
            <span className="text-terminal-muted">Latency</span>
            <span className="text-terminal-text">{agent.executionTimeMs.toFixed(0)}ms</span>
          </div>
        )}
        <div className="flex justify-between">
          <span className="text-terminal-muted">Last Activity</span>
          <span className="text-terminal-text">{formatRelativeTime(agent.lastActivity)}</span>
        </div>
      </div>

      {agent.lastOutput && (
        <div className="mt-2 pt-2 border-t border-terminal-border">
          <p className="text-2xs text-terminal-muted truncate">{agent.lastOutput}</p>
        </div>
      )}

      {agent.errorMessage && (
        <div className="mt-2 pt-2 border-t border-red-500/20">
          <p className="text-2xs text-trade-loss truncate">{agent.errorMessage}</p>
        </div>
      )}
    </div>
  );
}

function PipelineVisualization({
  activePhase,
  completedPhases,
  agents,
}: {
  activePhase: PipelinePhase | null;
  completedPhases: PipelinePhase[];
  agents: AgentInfo[];
}) {
  const agentsByPhase = useMemo(() => {
    const map = new Map<PipelinePhase, AgentInfo[]>();
    for (const a of agents) {
      const existing = map.get(a.phase) || [];
      existing.push(a);
      map.set(a.phase, existing);
    }
    return map;
  }, [agents]);

  return (
    <div className="card">
      <div className="card-header">Pipeline Status</div>
      <div className="space-y-1.5">
        {PIPELINE_PHASES.map((phase, idx) => {
          const phaseAgents = agentsByPhase.get(phase) || [];
          const isActive = activePhase === phase;
          const isCompleted = completedPhases.includes(phase);
          const hasError = phaseAgents.some((a) => a.state === 'error');

          return (
            <div
              key={phase}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-xs transition-all ${
                isActive
                  ? 'bg-blue-600/10 border border-blue-500/30'
                  : isCompleted
                  ? 'bg-emerald-500/5 border border-emerald-500/15'
                  : 'border border-transparent'
              }`}
            >
              {/* Step number */}
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-2xs font-mono font-bold shrink-0 ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : isCompleted
                    ? 'bg-emerald-600 text-white'
                    : hasError
                    ? 'bg-red-600 text-white'
                    : 'bg-terminal-border text-terminal-muted'
                }`}
              >
                {isCompleted ? '✓' : idx + 1}
              </div>

              {/* Phase info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`font-medium ${isActive ? 'text-blue-400' : isCompleted ? 'text-emerald-400' : 'text-terminal-muted'}`}>
                    {PHASE_LABELS[phase]}
                  </span>
                  {isActive && (
                    <span className="text-2xs text-blue-400 animate-pulse-slow">● RUNNING</span>
                  )}
                </div>
                <div className="text-2xs text-terminal-muted mt-0.5">
                  {phaseAgents.map((a) => a.name).join(' · ')}
                </div>
              </div>

              {/* Agent status dots */}
              <div className="flex items-center gap-1">
                {phaseAgents.map((a) => (
                  <span
                    key={a.id}
                    className={`inline-block w-1.5 h-1.5 rounded-full ${STATE_COLORS[a.state]}`}
                    title={`${a.name}: ${STATE_LABELS[a.state]}`}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MessageBus({ messages }: { messages: import('@/types').BusMessage[] }) {
  // Show simulated bus messages from agent activity
  const { state } = useDashboard();
  const [filter, setFilter] = useState<string>('');

  const displayMessages = useMemo(() => {
    if (state.agents.length === 0) return [];
    // Generate simulated bus messages from agent states
    return state.agents
      .filter((a) => a.lastActivity)
      .sort((a, b) => {
        const ta = a.lastActivity ? new Date(a.lastActivity).getTime() : 0;
        const tb = b.lastActivity ? new Date(b.lastActivity).getTime() : 0;
        return tb - ta;
      })
      .slice(0, 50)
      .map((a, i) => ({
        id: `${a.id}-${i}`,
        agentId: a.id,
        agentName: a.name,
        direction: a.state === 'active' ? ('pub' as const) : ('sub' as const),
        channel: `noema:${a.phase}`,
        content: a.lastOutput || `${a.state === 'active' ? 'Processing' : 'Idle'} — ${PHASE_LABELS[a.phase]}`,
        timestamp: a.lastActivity || new Date().toISOString(),
      }));
  }, [state.agents]);

  const filtered = filter
    ? displayMessages.filter(
        (m) =>
          m.agentName.toLowerCase().includes(filter.toLowerCase()) ||
          m.channel.toLowerCase().includes(filter.toLowerCase()),
      )
    : displayMessages;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="card-header mb-0">Agent Communication Log</div>
        <input
          type="text"
          placeholder="Filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="input-field w-40 text-xs py-1"
        />
      </div>
      <div className="space-y-1 max-h-96 overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="text-xs text-terminal-muted text-center py-4">
            {state.wsConnected ? 'No messages yet' : 'Waiting for connection…'}
          </p>
        ) : (
          filtered.map((msg) => (
            <div
              key={msg.id}
              className="flex items-start gap-2 px-2 py-1.5 rounded hover:bg-terminal-border/20 transition-colors text-2xs font-mono"
            >
              <span className="text-terminal-muted shrink-0 w-16">
                {formatTimestamp(msg.timestamp).split(' ')[1] || msg.timestamp}
              </span>
              <span
                className={`shrink-0 w-8 text-center ${
                  msg.direction === 'pub' ? 'text-blue-400' : 'text-terminal-muted'
                }`}
              >
                {msg.direction.toUpperCase()}
              </span>
              <span className="text-terminal-muted shrink-0 w-28 truncate">
                {msg.channel}
              </span>
              <span className="text-emerald-400 shrink-0 w-20 truncate">
                [{msg.agentName}]
              </span>
              <span className="text-terminal-text truncate">
                {msg.content}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export function Agents() {
  const { state } = useDashboard();

  const stats = useMemo(() => {
    const active = state.agents.filter((a) => a.state === 'active').length;
    const idle = state.agents.filter((a) => a.state === 'idle').length;
    const error = state.agents.filter((a) => a.state === 'error').length;
    const offline = state.agents.filter((a) => a.state === 'offline').length;
    return { active, idle, error, offline, total: state.agents.length };
  }, [state.agents]);

  return (
    <div className="p-4 space-y-4 animate-fade-in">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-terminal-bright">Agent Monitor</h2>
        {state.systemHealth && (
          <div className="flex items-center gap-3 text-xs font-mono">
            <span className="text-terminal-muted">
              {stats.total} agents
            </span>
            <span className="text-status-green">{stats.active} active</span>
            <span className="text-terminal-muted">{stats.idle} idle</span>
            {stats.error > 0 && (
              <span className="text-status-red">{stats.error} errors</span>
            )}
            {stats.offline > 0 && (
              <span className="text-terminal-muted">{stats.offline} offline</span>
            )}
          </div>
        )}
      </div>

      {/* Pipeline + Agent Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-4">
        {/* Pipeline visualization */}
        <div className="xl:col-span-1">
          <PipelineVisualization
            activePhase={state.activePhase}
            completedPhases={state.completedPhases}
            agents={state.agents}
          />
        </div>

        {/* Agent cards grid */}
        <div className="xl:col-span-3">
          {state.agents.length === 0 ? (
            <div className="card text-center py-12">
              <p className="text-terminal-muted text-sm">
                {state.wsConnected ? 'Loading agent data…' : 'Connect to backend to see agent status'}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {state.agents.map((agent) => (
                <AgentCard key={agent.id} agent={agent} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Message bus log */}
      <MessageBus messages={state.busMessages} />
    </div>
  );
}
