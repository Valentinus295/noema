import React, { createContext, useContext, useReducer, useCallback, type Dispatch } from 'react';
import type {
  AgentInfo, Trade, Position, Metrics, RiskMetrics, SystemHealth,
  TradingSettings, BusMessage, PipelinePhase, WsMessage, EquityPoint,
} from '@/types';
import { useWebSocket } from '@/hooks/useWebSocket';

// ── State ────────────────────────────────────────────────────

interface DashboardState {
  // System
  systemHealth: SystemHealth | null;
  wsConnected: boolean;
  wsReconnectAttempt: number;
  activePhase: PipelinePhase | null;
  completedPhases: PipelinePhase[];

  // Agents
  agents: AgentInfo[];
  busMessages: BusMessage[];

  // Trading
  positions: Position[];
  trades: Trade[];

  // Metrics
  metrics: Metrics | null;

  // Risk
  riskMetrics: RiskMetrics | null;

  // Settings
  settings: TradingSettings | null;

  // Loading / error
  error: string | null;
  lastUpdate: string | null;
}

const initialState: DashboardState = {
  systemHealth: null,
  wsConnected: false,
  wsReconnectAttempt: 0,
  activePhase: null,
  completedPhases: [],
  agents: [],
  busMessages: [],
  positions: [],
  trades: [],
  metrics: null,
  riskMetrics: null,
  settings: null,
  error: null,
  lastUpdate: null,
};

// ── Actions ──────────────────────────────────────────────────

type Action =
  | { type: 'WS_CONNECTED' }
  | { type: 'WS_DISCONNECTED'; attempt: number }
  | { type: 'SYSTEM_STATUS'; data: SystemHealth }
  | { type: 'AGENTS_UPDATE'; data: AgentInfo[] }
  | { type: 'AGENT_UPDATE'; data: AgentInfo }
  | { type: 'POSITIONS_UPDATE'; data: Position[] }
  | { type: 'TRADES_UPDATE'; data: Trade[] }
  | { type: 'METRICS_UPDATE'; data: Metrics }
  | { type: 'RISK_UPDATE'; data: RiskMetrics }
  | { type: 'SETTINGS_UPDATE'; data: TradingSettings }
  | { type: 'PIPELINE_PHASE'; phase: PipelinePhase; active: boolean }
  | { type: 'BUS_MESSAGE'; data: BusMessage }
  | { type: 'ERROR'; error: string }
  | { type: 'CLEAR_ERROR' };

function dashboardReducer(state: DashboardState, action: Action): DashboardState {
  switch (action.type) {
    case 'WS_CONNECTED':
      return { ...state, wsConnected: true, wsReconnectAttempt: 0, error: null };

    case 'WS_DISCONNECTED':
      return { ...state, wsConnected: false, wsReconnectAttempt: action.attempt };

    case 'SYSTEM_STATUS':
      return { ...state, systemHealth: action.data, lastUpdate: new Date().toISOString() };

    case 'AGENTS_UPDATE':
      return { ...state, agents: action.data, lastUpdate: new Date().toISOString() };

    case 'AGENT_UPDATE': {
      const idx = state.agents.findIndex((a) => a.id === action.data.id);
      const next = [...state.agents];
      if (idx >= 0) {
        next[idx] = action.data;
      } else {
        next.push(action.data);
      }
      return { ...state, agents: next, lastUpdate: new Date().toISOString() };
    }

    case 'POSITIONS_UPDATE':
      return { ...state, positions: action.data, lastUpdate: new Date().toISOString() };

    case 'TRADES_UPDATE':
      return { ...state, trades: action.data, lastUpdate: new Date().toISOString() };

    case 'METRICS_UPDATE':
      return { ...state, metrics: action.data, lastUpdate: new Date().toISOString() };

    case 'RISK_UPDATE':
      return { ...state, riskMetrics: action.data, lastUpdate: new Date().toISOString() };

    case 'SETTINGS_UPDATE':
      return { ...state, settings: action.data };

    case 'PIPELINE_PHASE':
      if (action.active) {
        return {
          ...state,
          activePhase: action.phase,
          completedPhases: state.completedPhases.includes(action.phase)
            ? state.completedPhases
            : [...state.completedPhases, action.phase],
        };
      }
      return state;

    case 'BUS_MESSAGE':
      return {
        ...state,
        busMessages: [action.data, ...state.busMessages].slice(0, 200),
      };

    case 'ERROR':
      return { ...state, error: action.error };

    case 'CLEAR_ERROR':
      return { ...state, error: null };

    default:
      return state;
  }
}

// ── Context ──────────────────────────────────────────────────

interface DashboardContextValue {
  state: DashboardState;
  dispatch: Dispatch<Action>;
  fetchApi: <T>(endpoint: string, init?: RequestInit) => Promise<T>;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(dashboardReducer, initialState);

  const handleWsMessage = useCallback((msg: WsMessage) => {
    switch (msg.type) {
      case 'agent_update':
        dispatch({ type: 'AGENT_UPDATE', data: msg.data as AgentInfo });
        break;
      case 'trade_update':
        dispatch({ type: 'TRADES_UPDATE', data: msg.data as Trade[] });
        break;
      case 'position_update':
        dispatch({ type: 'POSITIONS_UPDATE', data: msg.data as Position[] });
        break;
      case 'metrics_update':
        dispatch({ type: 'METRICS_UPDATE', data: msg.data as Metrics });
        break;
      case 'risk_update':
        dispatch({ type: 'RISK_UPDATE', data: msg.data as RiskMetrics });
        break;
      case 'system_status':
        dispatch({ type: 'SYSTEM_STATUS', data: msg.data as SystemHealth });
        break;
      case 'pipeline_phase':
        dispatch({
          type: 'PIPELINE_PHASE',
          phase: (msg.data as { phase: PipelinePhase }).phase,
          active: (msg.data as { active: boolean }).active,
        });
        break;
      case 'error':
        dispatch({ type: 'ERROR', error: String(msg.data) });
        break;
      default:
        break;
    }
  }, []);

  const handleWsOpen = useCallback(() => {
    dispatch({ type: 'WS_CONNECTED' });
  }, []);

  const handleWsClose = useCallback(() => {
    // Reconnect attempt is tracked in the hook
  }, []);

  const { isConnected, reconnectAttempt, send } = useWebSocket(WS_URL, {
    onMessage: handleWsMessage,
    onOpen: handleWsOpen,
    onClose: handleWsClose,
    reconnectInterval: 3000,
    maxReconnectAttempts: 20,
  });

  // Update WS state when reconnect attempt changes
  React.useEffect(() => {
    if (!isConnected && reconnectAttempt > 0) {
      dispatch({ type: 'WS_DISCONNECTED', attempt: reconnectAttempt });
    }
  }, [isConnected, reconnectAttempt]);

  const fetchApi = useCallback(async <T,>(endpoint: string, init?: RequestInit): Promise<T> => {
    const res = await fetch(`/api${endpoint}`, init);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API ${endpoint} failed (${res.status}): ${text}`);
    }
    return res.json();
  }, []);

  // Load initial data from REST API
  React.useEffect(() => {
    if (!isConnected) return;

    const loadInitialData = async () => {
      try {
        const [status, positions, trades, metrics, agents, risk, settings] =
          await Promise.allSettled([
            fetchApi<SystemHealth>('/status'),
            fetchApi<Position[]>('/positions'),
            fetchApi<Trade[]>('/trades?limit=100'),
            fetchApi<Metrics>('/metrics'),
            fetchApi<AgentInfo[]>('/agents'),
            fetchApi<RiskMetrics>('/risk'),
            fetchApi<TradingSettings>('/settings'),
          ]);

        if (status.status === 'fulfilled') dispatch({ type: 'SYSTEM_STATUS', data: status.value });
        if (positions.status === 'fulfilled') dispatch({ type: 'POSITIONS_UPDATE', data: positions.value });
        if (trades.status === 'fulfilled') dispatch({ type: 'TRADES_UPDATE', data: trades.value });
        if (metrics.status === 'fulfilled') dispatch({ type: 'METRICS_UPDATE', data: metrics.value });
        if (agents.status === 'fulfilled') dispatch({ type: 'AGENTS_UPDATE', data: agents.value });
        if (risk.status === 'fulfilled') dispatch({ type: 'RISK_UPDATE', data: risk.value });
        if (settings.status === 'fulfilled') dispatch({ type: 'SETTINGS_UPDATE', data: settings.value });
      } catch (err) {
        console.error('Failed to load initial data:', err);
      }
    };

    loadInitialData();
  }, [isConnected, fetchApi]);

  return (
    <DashboardContext.Provider value={{ state, dispatch, fetchApi }}>
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard(): DashboardContextValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) {
    throw new Error('useDashboard must be used within DashboardProvider');
  }
  return ctx;
}
