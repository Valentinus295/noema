// ── Agent Types ──────────────────────────────────────────────

export type AgentState = 'active' | 'idle' | 'error' | 'offline';

export type AgentType = 'deterministic' | 'llm';

export type PipelinePhase =
  | 'data_collection'
  | 'macro_analysis'
  | 'technical_analysis'
  | 'sentiment_analysis'
  | 'confluence'
  | 'thesis_generation'
  | 'devils_advocate'
  | 'cio_decision'
  | 'risk_assessment'
  | 'execution'
  | 'management'
  | 'learning';

export const PIPELINE_PHASES: PipelinePhase[] = [
  'data_collection',
  'macro_analysis',
  'technical_analysis',
  'sentiment_analysis',
  'confluence',
  'thesis_generation',
  'devils_advocate',
  'cio_decision',
  'risk_assessment',
  'execution',
  'management',
  'learning',
];

export const PHASE_LABELS: Record<PipelinePhase, string> = {
  data_collection: 'Data Collection',
  macro_analysis: 'Macro Analysis',
  technical_analysis: 'Technical Analysis',
  sentiment_analysis: 'Sentiment Analysis',
  confluence: 'Confluence Scoring',
  thesis_generation: 'Thesis Generation',
  devils_advocate: "Devil's Advocate",
  cio_decision: 'CIO Decision',
  risk_assessment: 'Risk Assessment',
  execution: 'Execution',
  management: 'Trade Management',
  learning: 'Learning & Review',
};

export interface AgentInfo {
  id: string;
  name: string;
  layer: number;
  phase: PipelinePhase;
  type: AgentType;
  state: AgentState;
  lastActivity: string | null;
  lastOutput: string | null;
  errorMessage: string | null;
  executionTimeMs: number | null;
}

// ── Trade Types ──────────────────────────────────────────────

export type TradeDirection = 'BUY' | 'SELL';
export type TradeStatus = 'open' | 'closed' | 'pending' | 'cancelled';

export interface Trade {
  id: number;
  ticket: number | null;
  symbol: string;
  direction: TradeDirection;
  volume: number;
  entryPrice: number;
  exitPrice: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  pnl: number;
  pnlPips: number;
  riskReward: number | null;
  status: TradeStatus;
  session: string;
  confidence: number | null;
  closeReason: string | null;
  openedAt: string;
  closedAt: string | null;
  durationSeconds: number | null;
}

// ── Position Types ───────────────────────────────────────────

export interface Position {
  ticket: number;
  symbol: string;
  direction: 'buy' | 'sell';
  volume: number;
  openPrice: number;
  currentPrice: number;
  stopLoss: number;
  takeProfit: number;
  pnl: number;
  pnlPips: number;
  magic: number;
}

// ── Metrics Types ────────────────────────────────────────────

export interface DailyMetrics {
  date: string;
  tradesTaken: number;
  wins: number;
  losses: number;
  totalPnl: number;
  maxDrawdown: number;
  winRate: number;
}

export interface Metrics {
  balance: number;
  equity: number;
  dailyPnl: number;
  weeklyPnl: number;
  monthlyPnl: number;
  totalTrades: number;
  winRate: number;
  profitFactor: number;
  sharpeRatio: number;
  maxDrawdown: number;
  currentDrawdown: number;
  avgRR: number;
  bestTrade: number;
  worstTrade: number;
  equityCurve: EquityPoint[];
  dailyWinRateHistory: DailyWinRate[];
  pnlDistribution: PnLBin[];
  winRateBySymbol: WinRateBySymbol[];
  winRateBySession: WinRateBySession[];
  winRateByDayOfWeek: WinRateByDayOfWeek[];
  winRateByHour: WinRateByHour[];
  drawdownHistory: EquityPoint[];
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
}

export interface DailyWinRate {
  date: string;
  winRate: number;
  trades: number;
}

export interface PnLBin {
  range: string;
  count: number;
}

export interface WinRateBySymbol {
  symbol: string;
  winRate: number;
  trades: number;
}

export interface WinRateBySession {
  session: string;
  winRate: number;
  trades: number;
}

export interface WinRateByDayOfWeek {
  day: string;
  winRate: number;
  trades: number;
}

export interface WinRateByHour {
  hour: number;
  winRate: number;
  trades: number;
}

// ── Risk Types ───────────────────────────────────────────────

export interface KillSwitch {
  id: string;
  name: string;
  description: string;
  active: boolean; // true = tripped/triggered
  value: string;
  threshold: string;
  timestamp: string | null;
}

export interface RiskMetrics {
  currentExposurePct: number;
  maxExposurePct: number;
  dailyLossPct: number;
  dailyLossLimitPct: number;
  consecutiveLosses: number;
  maxConsecutiveLosses: number;
  marginLevel: number;
  marginLevelWarning: number;
  freeMargin: number;
  killSwitches: KillSwitch[];
  correlationMatrix: CorrelationMatrix | null;
  openPositions: Position[];
}

export interface CorrelationMatrix {
  symbols: string[];
  values: number[][];
}

// ── System Status ────────────────────────────────────────────

export type SystemStatus = 'green' | 'yellow' | 'red';

export interface SystemHealth {
  status: SystemStatus;
  uptime: number;
  pipelineActive: boolean;
  brokerConnected: boolean;
  redisConnected: boolean;
  dbConnected: boolean;
  lastPipelineRun: string | null;
  pipelineLatencyMs: number | null;
  llmStatus: 'online' | 'degraded' | 'offline';
  activeAgents: number;
  totalAgents: number;
  version: string;
}

// ── Settings Types ────────────────────────────────────────────

export interface TradingSettings {
  riskPctPerTrade: number;
  maxConcurrentPositions: number;
  maxPerSymbol: number;
  dailyLossLimitPct: number;
  maxSpreadPips: number;
  minRR: number;
  slMethod: 'atr' | 'garch';
  confluenceThreshold: number;
  llmReviewEnabled: boolean;
  symbols: SymbolConfig[];
  sessions: SessionConfig;
  brokerConnected: boolean;
  brokerAccount: string;
  brokerServer: string;
}

export interface SymbolConfig {
  symbol: string;
  enabled: boolean;
  maxSpread: number;
}

export interface SessionConfig {
  sydney: boolean;
  tokyo: boolean;
  london: boolean;
  newYork: boolean;
  londonNYOverlap: boolean;
  sydneyTime: string;
  tokyoTime: string;
  londonTime: string;
  newYorkTime: string;
  overlapTime: string;
}

// ── WebSocket Event Types ────────────────────────────────────

export type WsEventType =
  | 'agent_update'
  | 'trade_update'
  | 'position_update'
  | 'metrics_update'
  | 'risk_update'
  | 'system_status'
  | 'pipeline_phase'
  | 'kill_switch'
  | 'error';

export interface WsMessage {
  type: WsEventType;
  data: unknown;
  timestamp: string;
}

// ── Message Bus Log ──────────────────────────────────────────

export interface BusMessage {
  id: string;
  agentId: string;
  agentName: string;
  direction: 'pub' | 'sub';
  channel: string;
  content: string;
  timestamp: string;
}

// ── Chart / SMC Types ────────────────────────────────────────

export type Timeframe = 'M15' | 'H1' | 'H4' | 'D1';
export type ChartSymbol = 'EURUSD' | 'GBPUSD' | 'USDJPY' | 'AUDUSD' | 'XAUUSD';
export type SMCDirection = 'bullish' | 'bearish';
export type StructureKind = 'BOS' | 'CHoCH';

export interface Candle {
  time: string;  // ISO 8601
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OrderBlock {
  time: string;
  priceHigh: number;
  priceLow: number;
  direction: SMCDirection;
}

export interface FairValueGap {
  time: string;
  top: number;
  bottom: number;
  direction: SMCDirection;
  mitigated: boolean;
}

export interface LiquiditySweep {
  time: string;
  level: number;
  direction: SMCDirection;
}

export interface StructureEvent {
  time: string;
  kind: StructureKind;
  direction: SMCDirection;
  price: number;
}

export interface ActiveSetup {
  entry: number;
  sl: number;
  tp: number;
  direction: SMCDirection;
}

export interface ChartData {
  symbol: string;
  timeframe: string;
  candles: Candle[];
  orderBlocks: OrderBlock[];
  fvgs: FairValueGap[];
  sweeps: LiquiditySweep[];
  structureEvents: StructureEvent[];
  activeSetup: ActiveSetup | null;
}
