"""TypedMessage Protocol — All 46 message types for inter-agent communication.

Provides a typed, versioned, priority-aware message system with 8 categories:
- Market Data (5 types)
- Analysis (6 types)
- Decision (6 types)
- Execution (9 types)
- Risk (5 types)
- Guardian (5 types)
- System (5 types)
- Meta/Learning/Telemetry (5 types)

Every message has: identity, type, priority, sender, payload, TTL,
and event-sourcing metadata (correlation_id, causation_id).

Uses Pydantic for validation — no LLM involvement in message routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════
# Message Classification Enums
# ═══════════════════════════════════════════════════

class MessagePriority(str, Enum):
    """Priority determines delivery order.
    
    CRITICAL messages bypass all queues. HIGH are trade decisions.
    MEDIUM are analysis results. LOW/BACKGROUND are telemetry.
    """
    CRITICAL = "critical"    # Kill-switch, margin call, emergency flatten
    HIGH = "high"            # Trade decision, risk alert, order execution
    MEDIUM = "medium"         # Analysis result, market data update
    LOW = "low"              # Learning, metrics, telemetry
    BACKGROUND = "background" # Logging, archival, heartbeats

    @property
    def ordinal(self) -> int:
        """Numeric ordering for priority queue (higher = more urgent)."""
        return {
            "critical": 4, "high": 3, "medium": 2, "low": 1, "background": 0,
        }[self.value]


class MessageCategory(str, Enum):
    """Logical grouping for channel organization."""
    MARKET_DATA = "market_data"
    ANALYSIS = "analysis"
    DECISION = "decision"
    EXECUTION = "execution"
    RISK = "risk"
    GUARDIAN = "guardian"
    LEARNING = "learning"
    SYSTEM = "system"
    TELEMETRY = "telemetry"


class MessageType(str, Enum):
    """Complete message type catalog — 46 types across 8 categories."""
    
    # ── MARKET DATA (5 types) ──
    MARKET_DATA_UPDATE = "market_data.update"       # OHLCV tick/candle
    ECONOMIC_EVENT = "market_data.economic_event"    # Economic calendar event
    SESSION_CHANGE = "market_data.session_change"    # Trading session transition
    NEWS_HEADLINE = "market_data.news_headline"      # High-impact news alert
    SPREAD_UPDATE = "market_data.spread_update"      # Broker spread change
    
    # ── ANALYSIS (6 types) ──
    ANALYSIS_RESULT = "analysis.result"              # Generic analysis output
    STRUCTURE_BREAK = "analysis.structure_break"     # BOS/CHoCH detected
    LIQUIDITY_SWEEP = "analysis.liquidity_sweep"     # Liquidity sweep detected
    SR_LEVEL_TOUCHED = "analysis.sr_touched"         # Price at S/R level
    ORDER_BLOCK_FORMED = "analysis.ob_formed"        # New order block identified
    REGIME_CHANGE = "analysis.regime_change"          # Market regime transition
    
    # ── DECISION — Actor-Critic (6 types) ──
    TRADE_PROPOSAL = "decision.proposal"             # Actor → Critic: proposed trade
    PROPOSAL_APPROVED = "decision.approved"          # Critic → Exec: approved
    PROPOSAL_REJECTED = "decision.rejected"          # Critic → Actor: rejected + feedback
    PROPOSAL_MODIFIED = "decision.modified"          # Critic → Actor: revise and resubmit
    CIO_NARRATIVE = "decision.cio_narrative"          # CIO generates narrative summary only
    DEBATE_SYNTHESIS = "decision.debate_synthesis"   # Structured debate output
    
    # ── EXECUTION (9 types) ──
    ORDER_PLACED = "execution.order_placed"          # Order sent to broker
    ORDER_FILLED = "execution.order_filled"          # Order confirmed filled
    ORDER_REJECTED = "execution.order_rejected"      # Broker rejected order
    ORDER_MODIFIED = "execution.order_modified"      # SL/TP modified
    ORDER_CANCELLED = "execution.order_cancelled"    # Order cancelled
    POSITION_OPENED = "execution.position_opened"    # New position active
    POSITION_CLOSED = "execution.position_closed"    # Position exited
    STOP_LOSS_HIT = "execution.sl_hit"               # SL triggered
    TAKE_PROFIT_HIT = "execution.tp_hit"             # TP triggered
    
    # ── RISK (5 types) ──
    RISK_LIMIT_BREACH = "risk.limit_breach"          # Position/exposure limit hit
    DRAWDOWN_WARNING = "risk.drawdown_warning"       # DD approaching limit
    CORRELATION_WARNING = "risk.correlation_warning"  # Cross-symbol correlation
    MARGIN_WARNING = "risk.margin_warning"            # Margin close to limit
    VOLATILITY_SPIKE = "risk.volatility_spike"        # Abnormal volatility
    
    # ── GUARDIAN (5 types) ──
    KILL_SWITCH_ACTIVATED = "guardian.killswitch"     # Kill-switch tripped
    TRADING_HALTED = "guardian.halted"                # All trading stopped
    TRADING_RESUMED = "guardian.resumed"              # Trading restarted
    DATA_STALE = "guardian.data_stale"                # Market data is old
    HEARTBEAT_MISSED = "guardian.heartbeat_missed"    # Agent heartbeat lost
    
    # ── LEARNING (5 types) ──
    AGENT_PERFORMANCE = "learning.agent_performance"  # Per-agent P&L update
    STRATEGY_ROTATION = "learning.strategy_rotation"  # Strategy enabled/disabled
    ANOMALY_DETECTED = "learning.anomaly_detected"    # Agent behavior anomaly
    WEIGHT_UPDATE = "learning.weight_update"          # Voting weight changed
    LEARNING_REPORT = "learning.learning_report"       # Daily/weekly learning summary
    
    # ── SYSTEM (5 types) ──
    AGENT_HEARTBEAT = "system.heartbeat"              # Agent alive check
    AGENT_REGISTERED = "system.agent_registered"      # New agent online
    AGENT_DEREGISTERED = "system.agent_deregistered"   # Agent shut down
    HEALTH_SNAPSHOT = "system.health_snapshot"        # Full system health
    CONFIG_CHANGE = "system.config_change"            # Runtime config modified

    @property
    def category(self) -> MessageCategory:
        """Derive the category from the message type."""
        prefix = self.value.split(".")[0]
        mapping = {
            "market_data": MessageCategory.MARKET_DATA,
            "analysis": MessageCategory.ANALYSIS,
            "decision": MessageCategory.DECISION,
            "execution": MessageCategory.EXECUTION,
            "risk": MessageCategory.RISK,
            "guardian": MessageCategory.GUARDIAN,
            "learning": MessageCategory.LEARNING,
            "system": MessageCategory.SYSTEM,
        }
        return mapping.get(prefix, MessageCategory.SYSTEM)


# ═══════════════════════════════════════════════════
# Core TypedMessage
# ═══════════════════════════════════════════════════

T = TypeVar("T", bound=BaseModel)


@dataclass
class TypedMessage(Generic[T]):
    """A typed, versioned, priority-aware message for inter-agent communication.
    
    This replaces the current untyped dict-based message passing.
    Every message has: identity, type, priority, sender, payload, TTL,
    and event-sourcing metadata (correlation_id, causation_id).
    
    LLM is NEVER in the critical path for message routing or decision-making.
    All priority ordering, TTL enforcement, and dispatch is deterministic.
    """
    message_id: str = field(default_factory=lambda: uuid4().hex[:12])
    message_type: MessageType = MessageType.ANALYSIS_RESULT
    priority: MessagePriority = MessagePriority.MEDIUM
    sender: str = ""                           # agent name or component
    symbol: str = ""                           # trading symbol (EURUSD, XAUUSD)
    timestamp: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    payload: Optional[T] = None                 # Typed payload (Pydantic model)
    correlation_id: str = ""                   # Links request-response pairs
    causation_id: str = ""                     # Links to parent (event sourcing chain)
    ttl_seconds: float = 300.0                 # 0 = no expiry, >0 = auto-drop after TTL
    schema_version: int = 1                    # For backward-compatible evolution
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if message has exceeded its TTL."""
        if self.ttl_seconds <= 0:
            return False
        age = datetime.now(timezone.utc).timestamp() - self.timestamp
        return age > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        """Age of the message in seconds."""
        return datetime.now(timezone.utc).timestamp() - self.timestamp

    def __lt__(self, other: "TypedMessage") -> bool:
        """Compare for priority queue ordering (higher priority first)."""
        return self.priority.ordinal > other.priority.ordinal


# ═══════════════════════════════════════════════════
# Concrete Message Payloads (All Pydantic models)
# ═══════════════════════════════════════════════════

# ── Market Data Payloads ──

class MarketDataPayload(BaseModel):
    """OHLCV candle data."""
    symbol: str
    timeframe: str                   # M5, M15, H1, H4, D1
    open: list[float] = Field(default_factory=list)
    high: list[float] = Field(default_factory=list)
    low: list[float] = Field(default_factory=list)
    close: list[float] = Field(default_factory=list)
    volume: list[float] = Field(default_factory=list)
    bar_count: int = 0
    last_update: float = 0.0


class EconomicEventPayload(BaseModel):
    """Economic calendar event."""
    event_name: str                  # "NFP", "FOMC", "CPI"
    currency: str                    # "USD", "EUR"
    impact: str = "medium"           # "high", "medium", "low"
    actual: Optional[float] = None
    forecast: Optional[float] = None
    previous: Optional[float] = None
    event_time: str = ""             # ISO 8601


class SessionChangePayload(BaseModel):
    """Trading session transition."""
    from_session: str                # "asia", "london", "ny"
    to_session: str                  # "asia", "london", "ny"
    timestamp: str = ""


class NewsHeadlinePayload(BaseModel):
    """High-impact news alert."""
    headline: str
    source: str = ""
    impact: str = "medium"
    timestamp: str = ""


class SpreadUpdatePayload(BaseModel):
    """Broker spread change."""
    symbol: str
    spread_pips: float
    bid: float = 0.0
    ask: float = 0.0
    timestamp: str = ""


# ── Analysis Payloads ──

class AnalysisResultPayload(BaseModel):
    """Generic agent analysis output."""
    agent_name: str
    signal: str                      # "BULLISH", "BEARISH", "NEUTRAL"
    confidence: float = 0.0          # 0.0-1.0
    reasoning: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0


class StructureBreakPayload(BaseModel):
    """BOS/CHoCH detected."""
    break_type: str                  # "BOS", "CHoCH"
    direction: str                   # "bullish", "bearish"
    level: float
    timeframe: str
    confidence: float = 0.0


class LiquiditySweepPayload(BaseModel):
    """Liquidity sweep detected."""
    swept_level: float
    direction: str                   # "above_high", "below_low"
    session: str = ""
    is_genuine: bool = True
    confidence: float = 0.0


class SRLevelTouchedPayload(BaseModel):
    """Price at S/R level."""
    level: float
    level_type: str = "support"      # "support", "resistance"
    reaction: str = ""               # "bounce", "break"
    timestamp: str = ""


class OrderBlockPayload(BaseModel):
    """New order block identified."""
    price_low: float
    price_high: float
    ob_type: str = ""                # "bullish", "bearish"
    timeframe: str = ""
    volume_ratio: float = 1.0


class RegimeChangePayload(BaseModel):
    """Market regime transition."""
    from_regime: str
    to_regime: str
    confidence: float = 0.0
    transition_probability: float = 0.0


# ── Decision Payloads — Actor-Critic ──

class TradeProposalPayload(BaseModel):
    """Actor → Critic: proposed trade."""
    proposal_id: str = ""
    direction: str                   # "BUY" | "SELL"
    symbol: str
    confidence: float = 0.0          # 0.0-1.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward_ratio: float = 0.0
    lot_size: float = 0.0
    evidence: dict[str, Any] = Field(default_factory=dict)
    risk_score: float = 0.0
    debate_quality: str = "PENDING"  # "STRONG", "ADEQUATE", "WEAK"


class ProposalFeedback(BaseModel):
    """Critic → Actor: feedback on proposal."""
    proposal_id: str = ""
    decision: str = "REJECT"         # "APPROVE" | "REJECT" | "MODIFY"
    reason: str = ""
    suggested_modifications: dict[str, Any] = Field(default_factory=dict)
    critic_scores: dict[str, float] = Field(default_factory=dict)  # per-critic confidence
    aggregate_confidence: float = 0.0


class CIONarrative(BaseModel):
    """CIO generates narrative summary only — NO decision fields.

    The CIONarrative model CONTAINS NO directional/execution fields.
    It has NO `direction`, `lot`, `sl`, `tp`, or `decision` fields.
    The tiebreaker is rule-based and deterministic — no LLM in the decision path.

    Per ADR-002 requirement: Pydantic validates this contract.

    IMPORTANT: `tiebreaker_result` is validated to ALWAYS be "NO_TRADE"
    on construction. This prevents LLMs from injecting a tiebreaker decision.
    The ConservativeTiebreaker sets the real result via attribute assignment
    AFTER model construction — not through the constructor.
    """
    proposal_id: str = ""
    narrative_summary: str = ""      # Natural language synthesis of critic debate
    critic_votes: dict[str, str] = Field(default_factory=dict)  # {devil: "REJECT", risk: "APPROVE"}
    tiebreaker_result: str = "NO_TRADE"  # Rule-based: "NO_TRADE" | "REDUCE_SIZE" | "FULL_SIZE"
    tiebreaker_rule: str = ""        # Which rule: "conservative_majority" | "quorum_fail" | "all_approve"

    # Note: No direction, lot, sl, tp, or decision fields.
    # The ConservativeTiebreaker is the sole decision authority.

    @field_validator("tiebreaker_result")
    @classmethod
    def enforce_no_llm_tiebreaker(cls, v: str) -> str:
        """Enforce that tiebreaker_result is NEVER set by LLM.

        Any value other than "NO_TRADE" during model construction is rejected.
        The ConservativeTiebreaker sets the real value via attribute assignment
        AFTER construction, bypassing this validator.

        Per QS WARNING-7: Pydantic validator prevents LLM manipulation.
        """
        if v != "NO_TRADE":
            raise ValueError(
                f"tiebreaker_result must be 'NO_TRADE' during construction. "
                f"Got '{v}'. The ConservativeTiebreaker sets the real value "
                f"after model construction via attribute assignment. "
                f"This prevents LLM hallucination from setting trade decisions."
            )
        return v


class DebateSynthesisPayload(BaseModel):
    """Structured debate output."""
    proposal_id: str
    rounds_completed: int = 0
    bull_claims_resolved: list[str] = Field(default_factory=list)
    bear_objections_resolved: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    final_conviction: float = 0.0
    verdict: str = "NO_TRADE"        # "PROCEED", "REDUCE_SIZE", "NO_TRADE"
    debate_quality: str = "WEAK"     # "STRONG", "ADEQUATE", "WEAK"


# ── Execution Payloads ──

class OrderPayload(BaseModel):
    """Order placed/modified/filled/rejected/cancelled."""
    order_id: str = ""
    symbol: str = ""
    side: str = ""                   # "BUY", "SELL"
    order_type: str = "MARKET"       # "MARKET", "LIMIT", "STOP"
    volume: float = 0.0
    price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    broker: str = ""                 # "fxpesa", "fbs", "paper"
    ticket: Optional[int] = None
    status: str = "PENDING"          # "PENDING", "FILLED", "REJECTED", "CANCELLED"
    comment: str = ""


class PositionPayload(BaseModel):
    """Position opened/closed."""
    position_id: str = ""
    symbol: str = ""
    direction: str = ""
    volume: float = 0.0
    open_price: float = 0.0
    current_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: str = ""
    closed_at: str = ""
    status: str = "OPEN"             # "OPEN", "CLOSED"
    exit_reason: str = ""            # "TP_HIT", "SL_HIT", "MANUAL", "TRAILING_STOP"


# ── Risk Payloads ──

class RiskBreachPayload(BaseModel):
    """Risk limit breach."""
    breach_type: str                 # "position_limit", "daily_loss", "drawdown", "exposure"
    current_value: float
    limit_value: float
    symbol: str = ""
    timestamp: str = ""


class DrawdownPayload(BaseModel):
    """Drawdown status."""
    current_drawdown_pct: float
    peak_equity: float = 0.0
    current_equity: float = 0.0
    warning_level: str = "GREEN"     # "GREEN", "YELLOW", "RED"


class CorrelationPayload(BaseModel):
    """Cross-symbol correlation warning."""
    symbols: list[str] = Field(default_factory=list)
    correlation: float = 0.0         # Pearson r
    positions_aligned: bool = False  # True if all same direction
    recommendation: str = "IGNORE"   # "IGNORE", "REDUCE_SIZE", "REJECT"


class MarginWarningPayload(BaseModel):
    """Margin warning."""
    margin_level: float = 0.0
    margin_used: float = 0.0
    margin_free: float = 0.0
    symbol: str = ""


class VolatilitySpikePayload(BaseModel):
    """Abnormal volatility."""
    symbol: str
    current_volatility: float
    expected_volatility: float
    ratio: float = 1.0               # current / expected
    threshold: float = 2.0


# ── Guardian Payloads ──

class KillSwitchPayload(BaseModel):
    """Kill-switch activation."""
    switch_name: str                 # "daily_loss", "max_drawdown", "data_stale", etc.
    reason: str = ""
    activated_by: str = ""           # agent name
    timestamp: str = ""
    emergency_flatten: bool = False


class TradingHaltedPayload(BaseModel):
    """Trading halted."""
    reason: str
    halted_by: str = ""
    timestamp: str = ""


class TradingResumedPayload(BaseModel):
    """Trading resumed."""
    resumed_by: str = ""
    timestamp: str = ""


class DataStalePayload(BaseModel):
    """Market data stale warning."""
    last_tick_age_seconds: float
    source: str = ""                 # "mt5", "broker"
    threshold: float = 5.0


class HeartbeatMissedPayload(BaseModel):
    """Agent heartbeat lost."""
    agent_name: str
    last_heartbeat_at: str = ""
    missed_since: float = 0.0        # seconds


# ── Learning Payloads ──

class AgentPerformancePayload(BaseModel):
    """Per-agent performance update."""
    agent_name: str
    symbol: str = ""
    win_rate_30d: float = 0.0
    sharpe_contribution: float = 0.0
    avg_confidence: float = 0.0
    calibration_error: float = 0.0   # Brier score
    total_signals: int = 0
    current_weight: float = 1.0
    last_updated: str = ""


class StrategyRotationPayload(BaseModel):
    """Strategy enabled/disabled."""
    strategy_name: str
    action: str = ""                 # "enable", "disable", "rotate"
    reason: str = ""


class AnomalyPayload(BaseModel):
    """Agent behavior anomaly detected."""
    agent_name: str
    anomaly_type: str                # "signal_distribution_shift", "confidence_drift", "latency_spike"
    description: str = ""
    severity: str = "LOW"           # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    detected_at: str = ""
    recommended_action: str = "MONITOR"


class WeightUpdatePayload(BaseModel):
    """Voting weight changed."""
    agent_name: str
    old_weight: float
    new_weight: float
    reason: str = ""
    updated_at: str = ""


class LearningReportPayload(BaseModel):
    """Daily/weekly learning summary."""
    period: str = "daily"            # "daily", "weekly"
    trades_analyzed: int = 0
    new_lessons: int = 0
    rules_created: int = 0
    rules_retired: int = 0
    weight_changes: dict[str, float] = Field(default_factory=dict)
    regime_performance: dict[str, dict] = Field(default_factory=dict)
    strategy_fitness: Optional[float] = None


# ── System Payloads ──

class HeartbeatPayload(BaseModel):
    """Agent alive check."""
    agent_name: str
    uptime_seconds: float = 0.0
    memory_usage_mb: float = 0.0
    active_signals: int = 0
    last_signal_at: str = ""


class AgentRegisteredPayload(BaseModel):
    """New agent online."""
    agent_name: str
    agent_type: str = ""
    version: str = "1.0.0"
    registered_at: str = ""


class AgentDeregisteredPayload(BaseModel):
    """Agent shut down."""
    agent_name: str
    reason: str = "shutdown"
    deregistered_at: str = ""


class HealthSnapshotPayload(BaseModel):
    """Full system health."""
    agent_name: str = ""
    score: float = 0.0               # 0-100
    status: str = "UNKNOWN"          # "HEALTHY", "DEGRADED", "FAILED", "ISOLATED"
    components: dict[str, float] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)


class ConfigChangePayload(BaseModel):
    """Runtime config modified."""
    changed_by: str
    parameter: str
    old_value: Any = None
    new_value: Any = None
    timestamp: str = ""


# ═══════════════════════════════════════════════════
# Payload Type Registry — Maps MessageType → Payload Model
# ═══════════════════════════════════════════════════


class MessageRegistry:
    """Registry for looking up payload types by MessageType.
    
    Provides deterministic lookup of Pydantic payload models for each
    message type. Used by the message bus to validate and deserialize
    incoming typed messages without LLM involvement.
    """
    
    _registry: dict[MessageType, type[BaseModel]] = {}
    _reverse: dict[type[BaseModel], MessageType] = {}
    
    @classmethod
    def register(cls, msg_type: MessageType, payload_model: type[BaseModel]) -> None:
        """Register a payload model for a message type."""
        cls._registry[msg_type] = payload_model
        cls._reverse[payload_model] = msg_type
    
    @classmethod
    def get_payload_model(cls, msg_type: MessageType) -> type[BaseModel] | None:
        """Get the payload Pydantic model for a given message type."""
        return cls._registry.get(msg_type)
    
    @classmethod
    def get_message_type(cls, payload_model: type[BaseModel]) -> MessageType | None:
        """Get the MessageType for a given payload model (reverse lookup)."""
        return cls._reverse.get(payload_model)
    
    @classmethod
    def initialize(cls) -> None:
        """Bootstrap the registry from PAYLOAD_REGISTRY."""
        for msg_type, model in PAYLOAD_REGISTRY.items():
            cls.register(msg_type, model)


PAYLOAD_REGISTRY: dict[MessageType, type[BaseModel]] = {
    # Market Data
    MessageType.MARKET_DATA_UPDATE: MarketDataPayload,
    MessageType.ECONOMIC_EVENT: EconomicEventPayload,
    MessageType.SESSION_CHANGE: SessionChangePayload,
    MessageType.NEWS_HEADLINE: NewsHeadlinePayload,
    MessageType.SPREAD_UPDATE: SpreadUpdatePayload,

    # Analysis
    MessageType.ANALYSIS_RESULT: AnalysisResultPayload,
    MessageType.STRUCTURE_BREAK: StructureBreakPayload,
    MessageType.LIQUIDITY_SWEEP: LiquiditySweepPayload,
    MessageType.SR_LEVEL_TOUCHED: SRLevelTouchedPayload,
    MessageType.ORDER_BLOCK_FORMED: OrderBlockPayload,
    MessageType.REGIME_CHANGE: RegimeChangePayload,

    # Decision
    MessageType.TRADE_PROPOSAL: TradeProposalPayload,
    MessageType.PROPOSAL_APPROVED: ProposalFeedback,
    MessageType.PROPOSAL_REJECTED: ProposalFeedback,
    MessageType.PROPOSAL_MODIFIED: ProposalFeedback,
    MessageType.CIO_NARRATIVE: CIONarrative,
    MessageType.DEBATE_SYNTHESIS: DebateSynthesisPayload,

    # Execution
    MessageType.ORDER_PLACED: OrderPayload,
    MessageType.ORDER_FILLED: OrderPayload,
    MessageType.ORDER_REJECTED: OrderPayload,
    MessageType.ORDER_MODIFIED: OrderPayload,
    MessageType.ORDER_CANCELLED: OrderPayload,
    MessageType.POSITION_OPENED: PositionPayload,
    MessageType.POSITION_CLOSED: PositionPayload,
    MessageType.STOP_LOSS_HIT: PositionPayload,
    MessageType.TAKE_PROFIT_HIT: PositionPayload,

    # Risk
    MessageType.RISK_LIMIT_BREACH: RiskBreachPayload,
    MessageType.DRAWDOWN_WARNING: DrawdownPayload,
    MessageType.CORRELATION_WARNING: CorrelationPayload,
    MessageType.MARGIN_WARNING: MarginWarningPayload,
    MessageType.VOLATILITY_SPIKE: VolatilitySpikePayload,

    # Guardian
    MessageType.KILL_SWITCH_ACTIVATED: KillSwitchPayload,
    MessageType.TRADING_HALTED: TradingHaltedPayload,
    MessageType.TRADING_RESUMED: TradingResumedPayload,
    MessageType.DATA_STALE: DataStalePayload,
    MessageType.HEARTBEAT_MISSED: HeartbeatMissedPayload,

    # Learning
    MessageType.AGENT_PERFORMANCE: AgentPerformancePayload,
    MessageType.STRATEGY_ROTATION: StrategyRotationPayload,
    MessageType.ANOMALY_DETECTED: AnomalyPayload,
    MessageType.WEIGHT_UPDATE: WeightUpdatePayload,
    MessageType.LEARNING_REPORT: LearningReportPayload,

    # System
    MessageType.AGENT_HEARTBEAT: HeartbeatPayload,
    MessageType.AGENT_REGISTERED: AgentRegisteredPayload,
    MessageType.AGENT_DEREGISTERED: AgentDeregisteredPayload,
    MessageType.HEALTH_SNAPSHOT: HealthSnapshotPayload,
    MessageType.CONFIG_CHANGE: ConfigChangePayload,
}


# ═══════════════════════════════════════════════════
# TTL Configuration per MessageType
# ═══════════════════════════════════════════════════

TTL_CONFIG: dict[MessageType, float] = {
    # Data — stale quickly
    MessageType.MARKET_DATA_UPDATE: 60.0,
    MessageType.ECONOMIC_EVENT: 300.0,
    MessageType.SESSION_CHANGE: 30.0,
    MessageType.NEWS_HEADLINE: 600.0,
    MessageType.SPREAD_UPDATE: 10.0,

    # Analysis — valid for one cycle
    MessageType.ANALYSIS_RESULT: 60.0,
    MessageType.STRUCTURE_BREAK: 120.0,
    MessageType.LIQUIDITY_SWEEP: 120.0,
    MessageType.SR_LEVEL_TOUCHED: 60.0,
    MessageType.ORDER_BLOCK_FORMED: 300.0,
    MessageType.REGIME_CHANGE: 600.0,

    # Decision — valid within cycle
    MessageType.TRADE_PROPOSAL: 30.0,
    MessageType.PROPOSAL_APPROVED: 30.0,
    MessageType.PROPOSAL_REJECTED: 30.0,
    MessageType.PROPOSAL_MODIFIED: 30.0,
    MessageType.CIO_NARRATIVE: 30.0,
    MessageType.DEBATE_SYNTHESIS: 60.0,

    # Execution — short TTL (time-sensitive)
    MessageType.ORDER_PLACED: 15.0,
    MessageType.ORDER_FILLED: 60.0,
    MessageType.ORDER_REJECTED: 15.0,
    MessageType.ORDER_MODIFIED: 15.0,
    MessageType.ORDER_CANCELLED: 15.0,
    MessageType.POSITION_OPENED: 0.0,      # permanent
    MessageType.POSITION_CLOSED: 0.0,       # permanent
    MessageType.STOP_LOSS_HIT: 0.0,         # permanent
    MessageType.TAKE_PROFIT_HIT: 0.0,       # permanent

    # Risk — immediate action
    MessageType.RISK_LIMIT_BREACH: 0.0,      # permanent
    MessageType.DRAWDOWN_WARNING: 300.0,
    MessageType.CORRELATION_WARNING: 300.0,
    MessageType.MARGIN_WARNING: 30.0,
    MessageType.VOLATILITY_SPIKE: 60.0,

    # Guardian — permanent
    MessageType.KILL_SWITCH_ACTIVATED: 0.0,
    MessageType.TRADING_HALTED: 0.0,
    MessageType.TRADING_RESUMED: 0.0,
    MessageType.DATA_STALE: 60.0,
    MessageType.HEARTBEAT_MISSED: 30.0,

    # Learning — medium TTL
    MessageType.AGENT_PERFORMANCE: 3600.0,
    MessageType.STRATEGY_ROTATION: 3600.0,
    MessageType.ANOMALY_DETECTED: 1800.0,
    MessageType.WEIGHT_UPDATE: 3600.0,
    MessageType.LEARNING_REPORT: 86400.0,

    # System — short for heartbeats
    MessageType.AGENT_HEARTBEAT: 15.0,
    MessageType.AGENT_REGISTERED: 0.0,
    MessageType.AGENT_DEREGISTERED: 0.0,
    MessageType.HEALTH_SNAPSHOT: 30.0,
    MessageType.CONFIG_CHANGE: 0.0,
}
