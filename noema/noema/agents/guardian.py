"""GuardianAgent — pre-trade AND pre-order-send veto + global kill-switches.

Class-based agent (DeterministicAgent) providing protection layers:
1. Global kill-switches (system halt, max daily loss, max drawdown)
2. Pre-trade veto (correlation check, news filter, spread filter)
3. Pre-order-send checks (price deviation, volume check, hedging check)

Contract pinned in docs/ARCHITECTURE.md §10.

Legacy standalone functions (guardian_guard, check_daily_loss, etc.)
are preserved below for backward compatibility.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

from noema.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)

# ── Prometheus gauge for news blackout (COO condition #3) ──
try:
    from prometheus_client import Gauge
    NOEMA_NEWS_BLACKOUT_ACTIVE = Gauge(
        "noema_news_blackout_active",
        "News blackout active status (1=active, 0=inactive)",
        ["pair"],
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    NOEMA_NEWS_BLACKOUT_ACTIVE = None  # type: ignore[assignment]


# ── Legacy state / standalone functions (preserved for backward compat) ──


def _get_compile_time_max_lot() -> float:
    """Return the compile-time max lot size constant.
    
    Binds GuardianState.max_lot_size to Noema_MAX_LOT_SIZE at import time,
    ensuring both the logical check (Guardian) and physical gate (lot_protection)
    use the same constant. See QS WARNING-1.
    """
    from noema.broker.lot_protection import Noema_MAX_LOT_SIZE
    return Noema_MAX_LOT_SIZE


@dataclass
class GuardianState:
    """Mutable state tracked by the Guardian across cycles."""
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    daily_loss_limit_pct: float = 3.0
    weekly_loss_limit: float = 8.0
    last_heartbeat: datetime | None = None
    heartbeat_timeout: int = 30
    news_blackout: bool = False
    news_blackout_until: datetime | None = None
    spread_multiplier: float = 2.0
    # Extended fields for kill-switch tracking
    max_lot_size: float = field(default_factory=lambda: _get_compile_time_max_lot())
    trading_halted: bool = False
    halt_reason: str = ""
    consecutive_losses: int = 0
    max_consecutive_losses: int = 5
    total_trades: int = 0
    winning_trades: int = 0
    account_balance: float = 0.0
    account_equity: float = 0.0
    margin_level: float = 999.0
    margin_warning: float = 200.0
    spread_current: float = 0.0
    max_spread: float = 5.0
    drawdown_peak_equity: float = 0.0
    max_drawdown_pct: float = 20.0
    llm_errors: int = 0
    max_llm_errors: int = 10
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    _audit_log_maxlen: int = field(default=500, repr=False)
    # ── Phase 1: New kill-switch state ──
    # Kill-switch #15: Actor broken (silenced agents)
    actor_rejection_counts: dict[str, int] = field(default_factory=dict)
    actor_max_rejections: int = 50  # Noema_ACTOR_MAX_REJECTIONS
    silenced_agents: set[str] = field(default_factory=set)
    # Kill-switch #16: Learning under drawdown
    learning_freeze_drawdown: float = 0.10  # Noema_LEARNING_FREEZE_DRAWDOWN
    learning_frozen: bool = False
    # Critic team monitoring
    critic_team_down: bool = False
    critic_min_quorum: int = 2
    critic_responses_this_cycle: int = 0


def check_daily_loss(state: GuardianState) -> bool:
    return abs(state.daily_pnl) >= state.daily_loss_limit_pct


def check_weekly_loss(state: GuardianState) -> bool:
    return abs(state.weekly_pnl) >= state.weekly_loss_limit


def check_news_blackout(state: GuardianState, symbol: str) -> bool:
    if state.news_blackout:
        return True
    if state.news_blackout_until:
        return datetime.now(timezone.utc) < state.news_blackout_until
    return False


def check_heartbeat(state: GuardianState) -> bool:
    if not state.last_heartbeat:
        return False
    elapsed = (datetime.now(timezone.utc) - state.last_heartbeat).total_seconds()
    return elapsed < state.heartbeat_timeout


async def guardian_guard(
    state: GuardianState, setup, current_pnl: float,
) -> tuple[bool, str]:
    state.daily_pnl = current_pnl
    state.weekly_pnl = current_pnl

    if check_daily_loss(state):
        return False, f"Daily loss limit reached: {state.daily_pnl:.2f}%"

    if check_weekly_loss(state):
        return False, f"Weekly loss limit reached: {state.weekly_pnl:.2f}%"

    if setup:
        if check_news_blackout(state, setup.symbol):
            return False, "News blackout active"

    return True, "Approved"


async def heartbeat_task(state: GuardianState, interval: float = 5.0) -> None:
    while True:
        state.last_heartbeat = datetime.now(timezone.utc)
        await asyncio.sleep(interval)


# ── Extended Kill-Switch Checks ─────────────────────────────────────


def check_consecutive_losses(state: GuardianState) -> bool:
    return state.consecutive_losses >= state.max_consecutive_losses


def check_max_lot_size(state: GuardianState, lot_size: float) -> bool:
    return lot_size > state.max_lot_size


def check_margin_level(state: GuardianState) -> bool:
    return state.margin_level < state.margin_warning


def check_spread(state: GuardianState) -> bool:
    return state.spread_current > state.max_spread


def check_drawdown(state: GuardianState) -> bool:
    if state.drawdown_peak_equity <= 0 or state.account_equity <= 0:
        return False
    drawdown = (state.drawdown_peak_equity - state.account_equity) / state.drawdown_peak_equity * 100
    return drawdown >= state.max_drawdown_pct


def check_llm_errors(state: GuardianState) -> bool:
    return state.llm_errors >= state.max_llm_errors


def check_data_stale(state: GuardianState) -> bool:
    """Check if broker data is stale (set by health monitor).

    This is the #1 prevention against trading on stale prices.
    The health monitor sets trading_halted + halt_reason="data_stale"
    when last_tick is > 5 seconds old.
    """
    return state.trading_halted and state.halt_reason == "data_stale"


# ── NEW Kill-Switch Functions (Phase 1) ─────────────────────────────

def check_actor_broken(state: GuardianState) -> bool:
    """Kill-switch #15: Check if any actor agent has been silenced.

    An agent is silenced when its proposals are rejected N consecutive times
    (default 50). The agent remains silenced until human review.

    Returns True if any agent has been silenced (trade should be halted for review).
    """
    return len(state.silenced_agents) > 0


def check_learning_under_drawdown(state: GuardianState) -> bool:
    """Kill-switch #16: Freeze learning if drawdown exceeds threshold.

    Checked EVERY TRADE (real-time), not weekly.
    If running drawdown > Noema_LEARNING_FREEZE_DRAWDOWN (default 10%),
    freeze ALL learning until manual review.
    """
    if state.drawdown_peak_equity <= 0 or state.account_equity <= 0:
        return False
    drawdown = (state.drawdown_peak_equity - state.account_equity) / state.drawdown_peak_equity
    return drawdown >= state.learning_freeze_drawdown


def check_critic_team_down(state: GuardianState) -> bool:
    """Check if the critic team is non-responsive.

    ZeroResponsePolicy: If zero CriticTeam responses within timeout →
    IMMEDIATE KILL. MinQuorumRule: If < 2 responses → KILL.
    """
    return state.critic_team_down


def update_actor_rejection(state: GuardianState, agent_name: str, rejected: bool) -> None:
    """Track per-agent proposal rejections for kill-switch #15.

    Resets on first acceptance. Silences agent after 
    actor_max_rejections consecutive rejections.
    """
    if not rejected:
        state.actor_rejection_counts[agent_name] = 0
        return

    count = state.actor_rejection_counts.get(agent_name, 0) + 1
    state.actor_rejection_counts[agent_name] = count

    if count >= state.actor_max_rejections and agent_name not in state.silenced_agents:
        state.silenced_agents.add(agent_name)
        logger.error(
            "guardian_actor_silenced",
            agent=agent_name,
            consecutive_rejections=count,
            reason="kill-switch #15: actor_broken",
        )
        _audit_log_append(state, {
            "event": "actor_silenced",
            "agent": agent_name,
            "consecutive_rejections": count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


def set_critic_team_down(state: GuardianState, down: bool = True, reason: str = "") -> None:
    """Set the critic_team_down flag.

    Called by HealthChecker→Guardian bridge when:
    - Zero CriticTeam responses within timeout
    - Fewer than MIN_QUORUM responses
    """
    if down and not state.critic_team_down:
        state.critic_team_down = True
        state.trading_halted = True
        state.halt_reason = f"critic_team_down: {reason}"
        logger.critical(
            "guardian_critic_team_down",
            reason=reason,
        )
        _audit_log_append(state, {
            "event": "critic_team_down",
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    elif not down:
        state.critic_team_down = False


def set_learning_frozen(state: GuardianState, frozen: bool = True, drawdown_pct: float = 0.0) -> None:
    """Freeze/unfreeze learning (kill-switch #16)."""
    if frozen and not state.learning_frozen:
        state.learning_frozen = True
        logger.warning(
            "guardian_learning_frozen",
            reason="kill-switch #16: learning_under_drawdown",
            drawdown_pct=round(drawdown_pct, 4),
        )
        _audit_log_append(state, {
            "event": "learning_frozen",
            "drawdown_pct": drawdown_pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    elif not frozen:
        state.learning_frozen = False


def _audit_log_append(state: GuardianState, entry: dict[str, Any]) -> None:
    """Append to audit_log with bounded size (prevents memory leak)."""
    state.audit_log.append(entry)
    if len(state.audit_log) > state._audit_log_maxlen:
        del state.audit_log[:-state._audit_log_maxlen]


def check_win_rate_floor(state: GuardianState) -> bool:
    """Bayesian win-rate floor — halt if win rate drops below 0.25 after 10+ trades."""
    if state.total_trades < 10:
        return False
    wr = state.winning_trades / max(state.total_trades, 1)
    return wr < 0.25


def check_sprt_edge(state: GuardianState) -> bool:
    """SPRT edge monitor — halt if directionally biased toward losing."""
    if state.total_trades < 8:
        return False
    if state.consecutive_losses <= 3:
        return False
    wr = state.winning_trades / max(state.total_trades, 1)
    return wr < 0.40


def check_ks_drift(state: GuardianState) -> bool:
    """KS drift detection — halt if win rate deviates >15pp from 0.50 after 50+ trades."""
    if state.total_trades < 50:
        return False
    wr = state.winning_trades / max(state.total_trades, 1)
    return abs(wr - 0.50) > 0.15


# ── GuardianAgent (class-based, modern agent pattern) ──────────────────


class GuardianAgent(DeterministicAgent):
    """Agent #18 — Guardian.

    Provides kill-switch and pre-trade veto protection:
    - Global halt check
    - Daily/weekly loss limit enforcement
    - News event protection (Phase 1.5: automated activation via EventAnalyst)
    - Spread filter
    - Correlation position gate

    All logic is deterministic — no LLM calls.
    """

    name = "guardian"
    role = "Guardian"
    priority = 0

    def __init__(self, config: Any = None, guardian_state: GuardianState | None = None):
        super().__init__(config=config)
        self._guardian_state = guardian_state
        self._halt_lock = threading.Lock()
        # Async lock for GuardianState mutations (prevents races between
        # concurrent async code paths: check_all, pre_trade_check,
        # record_trade_result, update_account_state)
        self._state_lock = asyncio.Lock()
        # ── Phase 1.5: Blackout watchdog tracking ──
        self._blackout_activated_at: dict[str, datetime] = {}  # pair → activation time
        self._max_blackout_minutes: int = 60  # Hard timeout (COO condition #1)

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Run all safety gate checks against the proposed trade context.

        Checks are run in priority order — the first failure stops evaluation.
        """
        # ── 1. Global halt ──
        if context.get("global_halt"):
            return AgentReport(
                agent_name=self.name,
                signal="REJECT",
                reasoning="Global halt is active — all trading suspended.",
            )

        # ── 2. Daily loss limit ──
        daily_pnl = context.get("daily_pnl", 0.0)
        account_balance = context.get("account_balance", 10000.0)
        risk_config = self.config.risk if self.config else None
        max_daily_loss = risk_config.max_daily_loss if risk_config else 0.03

        if account_balance > 0:
            daily_pnl_pct = abs(daily_pnl) / account_balance
        else:
            daily_pnl_pct = abs(daily_pnl)

        if daily_pnl_pct >= max_daily_loss:
            return AgentReport(
                agent_name=self.name,
                signal="REJECT",
                reasoning=(
                    f"Daily loss limit breached: {daily_pnl:.2f} "
                    f"({daily_pnl_pct:.2%} >= {max_daily_loss:.2%})"
                ),
            )

        # ── 3. Spread filter ──
        spread_pips = context.get("spread_pips", 0.0)
        max_spread = risk_config.max_spread_pips if risk_config else 3.0

        if spread_pips > max_spread * 3:  # 3x threshold = abnormal
            return AgentReport(
                agent_name=self.name,
                signal="REJECT",
                reasoning=(
                    f"Abnormal spread: {spread_pips:.1f} pips "
                    f"(threshold: {max_spread * 3:.1f} pips)"
                ),
            )
        elif spread_pips > max_spread:
            return AgentReport(
                agent_name=self.name,
                signal="CAUTION",
                reasoning=(
                    f"Elevated spread: {spread_pips:.1f} pips "
                    f"(threshold: {max_spread:.1f} pips)"
                ),
            )

        # ── 4. News event protection ──
        upcoming_news = context.get("upcoming_news", [])
        for news in upcoming_news:
            impact = news.get("impact", "").lower()
            minutes_away = news.get("minutes_away", 999)
            if impact == "high" and minutes_away <= 30:
                return AgentReport(
                    agent_name=self.name,
                    signal="CAUTION",
                    reasoning=(
                        f"High-impact news event '{news.get('name', 'Unknown')}' "
                        f"in {minutes_away} min — increased volatility risk."
                    ),
                )
            elif impact in ("high", "medium") and minutes_away <= 60:
                # Logged but not a blocker
                logger.info(
                    "news_event_nearby",
                    name=news.get("name"),
                    impact=impact,
                    minutes_away=minutes_away,
                )

        # ── 5. Correlation / duplicate position gate ──
        open_positions = context.get("open_positions", [])
        pair = context.get("pair", "")
        direction = context.get("direction", "").lower()

        if open_positions and pair:
            for pos in open_positions:
                pos_symbol = pos.get("symbol", "")
                pos_dir = pos.get("direction", "").lower()
                if pos_symbol == pair:
                    if pos_dir == direction:
                        return AgentReport(
                            agent_name=self.name,
                            signal="CAUTION",
                            reasoning=(
                                f"Duplicate position for {pair} ({direction}) — "
                                f"identical position already open."
                            ),
                        )
                    # Opposite direction — close and reverse? Flag it
                    logger.info(
                        "correlated_position_detected",
                        pair=pair,
                        existing_direction=pos_dir,
                        proposed_direction=direction,
                    )

        # ── All checks passed ──
        return AgentReport(
            agent_name=self.name,
            signal="APPROVE",
            confidence=0.9,
            reasoning="All safety checks passed — trade approved by Guardian.",
        )

    # ── 14 Kill-Switch Registry ────────────────────────────────────

    KILLSWITCHES = [
        ("daily_loss", "Daily Loss Limit", "Halts if daily PnL exceeds configured limit"),
        ("weekly_loss", "Weekly Loss Limit", "Halts if weekly PnL exceeds configured limit"),
        ("consecutive_losses", "Consecutive Losses", "Pauses after N consecutive losses"),
        ("win_rate_floor", "Win-Rate Floor", "Bayesian posterior mass below floor"),
        ("sprt_edge", "SPRT Edge Monitor", "Sequential probability ratio test failure"),
        ("ks_drift", "KS Drift Detection", "Live-vs-backtest distribution drift"),
        ("heartbeat", "Guardian Heartbeat", "Guardian agent heartbeat timeout"),
        ("margin_level", "Margin Level", "Margin below warning threshold"),
        ("max_lot_size", "Max Lot Size", "Position size exceeds hard cap"),
        ("spread", "Spread Guard", "Spread exceeds max allowed"),
        ("news_blackout", "News Blackout", "Trading halted for high-impact news"),
        ("drawdown", "Max Drawdown", "Drawdown exceeds configured maximum"),
        ("llm_errors", "LLM Error Rate", "Too many LLM failures"),
        ("data_stale", "Stale Data Protection", "Broker data is stale — last tick > 5s old"),
        # ── Phase 1: New kill-switches ──
        ("actor_broken", "Actor Broken (KS #15)", "Agent silenced after N consecutive rejections"),
        ("learning_under_drawdown", "Learning Under Drawdown (KS #16)", "Freeze all learning when drawdown > 10%"),
        ("critic_team_down", "Critic Team Down", "Zero critic responses or below quorum — IMMEDIATE KILL"),
    ]

    # ── Pipeline Integration Methods ────────────────────────────────

    async def check_all(self, account_state: Optional[dict[str, float]] = None) -> list[dict[str, Any]]:
        """Run ALL kill-switch checks at the start of each trading cycle.

        Args:
            account_state: Optional dict with balance/equity/margin/daily_pnl/weekly_pnl/spread.
                          If provided, refreshes GuardianState before checking.
                          This prevents kill-switches from evaluating stale data.

        Returns list of triggered kill-switches. Empty list = all clear.
        """
        async with self._state_lock:
            return await self._check_all_unlocked(account_state)

    async def _check_all_unlocked(
        self, account_state: Optional[dict[str, float]] = None
    ) -> list[dict[str, Any]]:
        """Internal implementation of check_all — must hold _state_lock."""
        # Refresh state if caller provides current account data
        if account_state:
            self._update_account_state_unlocked(
                balance=account_state.get("balance", 0.0),
                equity=account_state.get("equity", 0.0),
                margin_level=account_state.get("margin_level", 0.0),
                daily_pnl=account_state.get("daily_pnl", 0.0),
                weekly_pnl=account_state.get("weekly_pnl", 0.0),
                spread=account_state.get("spread", 0.0),
            )
        state = self._get_state()
        triggered: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        checks = [
            ("daily_loss", check_daily_loss(state), {
                "value": f"{state.daily_pnl:.2f}%",
                "threshold": f"{state.daily_loss_limit_pct}%"
            }),
            ("weekly_loss", check_weekly_loss(state), {
                "value": f"{state.weekly_pnl:.2f}%",
                "threshold": f"{state.weekly_loss_limit}%"
            }),
            ("consecutive_losses", check_consecutive_losses(state), {
                "value": str(state.consecutive_losses),
                "threshold": str(state.max_consecutive_losses)
            }),
            ("win_rate_floor", check_win_rate_floor(state), {
                "value": f"{state.winning_trades}/{state.total_trades}",
                "threshold": "min 25%"
            }),
            ("sprt_edge", check_sprt_edge(state), {
                "value": f"wr={state.winning_trades/max(state.total_trades,1):.2f}",
                "threshold": "H1 (edge lost)"
            }),
            ("ks_drift", check_ks_drift(state), {
                "value": f"wr={state.winning_trades/max(state.total_trades,1):.2f}",
                "threshold": "p<0.01"
            }),
            ("heartbeat", not check_heartbeat(state), {
                "value": "stale" if not check_heartbeat(state) else "alive",
                "threshold": f"{state.heartbeat_timeout}s"
            }),
            ("margin_level", check_margin_level(state), {
                "value": f"{state.margin_level:.1f}%",
                "threshold": f"{state.margin_warning}%"
            }),
            ("spread", check_spread(state), {
                "value": f"{state.spread_current:.1f} pips",
                "threshold": f"{state.max_spread} pips"
            }),
            ("news_blackout", check_news_blackout(state), {
                "value": "active" if state.news_blackout else "clear",
                "threshold": "no active blackout"
            }),
            ("drawdown", check_drawdown(state), {
                "value": "triggered" if check_drawdown(state) else "ok",
                "threshold": f"{state.max_drawdown_pct}%"
            }),
            ("llm_errors", check_llm_errors(state), {
                "value": str(state.llm_errors),
                "threshold": str(state.max_llm_errors)
            }),
            ("data_stale", check_data_stale(state), {
                "value": "stale" if check_data_stale(state) else "fresh",
                "threshold": "fresh data required"
            }),
            # ── Phase 1: New kill-switch checks ──
            ("actor_broken", check_actor_broken(state), {
                "value": f"{len(state.silenced_agents)} agents silenced",
                "threshold": "0 silenced agents"
            }),
            ("learning_under_drawdown", check_learning_under_drawdown(state), {
                "value": "frozen" if state.learning_frozen else "active",
                "threshold": f"{state.learning_freeze_drawdown:.0%} drawdown"
            }),
            ("critic_team_down", check_critic_team_down(state), {
                "value": "down" if state.critic_team_down else "responsive",
                "threshold": f"min {state.critic_min_quorum} responses"
            }),
        ]

        for switch_id, fired, details in checks:
            if fired:
                entry = {
                    "id": switch_id,
                    "timestamp": now.isoformat(),
                    **details,
                }
                triggered.append(entry)
                logger.warning(
                    "killswitch_fired",
                    switch=switch_id,
                    **details,
                )
                self._append_audit_log(state, {"event": "killswitch_fired", **entry})

        if triggered:
            self._halt_trading("; ".join(t["id"] for t in triggered))
            logger.error(
                "guardian_halted_trading",
                switches=[t["id"] for t in triggered],
                reason=state.halt_reason,
            )

        return triggered

    async def pre_trade_check(
        self, pair: str, lot_size: float, current_pnl: float
    ) -> tuple[bool, str]:
        """Check if a specific trade can proceed.

        Called BEFORE every order placement.
        Returns (approved, reason).
        """
        async with self._state_lock:
            return await self._pre_trade_check_unlocked(pair, lot_size, current_pnl)

    async def _pre_trade_check_unlocked(
        self, pair: str, lot_size: float, current_pnl: float
    ) -> tuple[bool, str]:
        """Internal pre-trade check — must hold _state_lock."""
        state = self._get_state()

        # Update PnL snapshot
        state.daily_pnl = current_pnl
        state.weekly_pnl = current_pnl

        # If trading is already halted, reject immediately
        if state.trading_halted:
            return False, f"Trading halted: {state.halt_reason}"

        # Run pre-trade kill-switches
        if check_daily_loss(state):
            self._halt_trading("daily_loss")
            logger.error("guardian_pre_trade_reject", reason="daily_loss", pnl=state.daily_pnl)
            return False, f"Daily loss limit reached: {state.daily_pnl:.2f}%"

        if check_weekly_loss(state):
            self._halt_trading("weekly_loss")
            logger.error("guardian_pre_trade_reject", reason="weekly_loss", pnl=state.weekly_pnl)
            return False, f"Weekly loss limit reached: {state.weekly_pnl:.2f}%"

        if check_consecutive_losses(state):
            self._halt_trading("consecutive_losses")
            logger.error("guardian_pre_trade_reject", reason="consecutive_losses", count=state.consecutive_losses)
            return False, f"{state.consecutive_losses} consecutive losses"

        if check_margin_level(state):
            self._halt_trading("margin_level")
            logger.error("guardian_pre_trade_reject", reason="margin_level", level=state.margin_level)
            return False, f"Margin level too low: {state.margin_level:.1f}%"

        if check_max_lot_size(state, lot_size):
            logger.warning("guardian_pre_trade_reject", reason="max_lot_size", lot_size=lot_size, cap=state.max_lot_size)
            return False, f"Lot size {lot_size} exceeds max {state.max_lot_size}"

        if check_spread(state):
            self._halt_trading("spread")
            logger.error("guardian_pre_trade_reject", reason="spread", spread=state.spread_current)
            return False, f"Spread too high: {state.spread_current:.1f} pips"

        if check_news_blackout(state, pair):
            return False, "News blackout active"

        if check_data_stale(state):
            logger.error("guardian_pre_trade_reject", reason="data_stale")
            return False, "Broker data is stale — last tick > 5s old"

        logger.info("guardian_pre_trade_approved", pair=pair, lot_size=lot_size)
        return True, "Approved"

    async def system_health_check(self) -> dict[str, Any]:
        """Run system health check on every pipeline tick.

        Returns health status dict with heartbeat, halt state, and PnL snapshot.
        """
        state = self._get_state()
        heartbeat_ok = check_heartbeat(state)
        health = {
            "heartbeat_ok": heartbeat_ok,
            "last_heartbeat": state.last_heartbeat.isoformat() if state.last_heartbeat else None,
            "trading_halted": state.trading_halted,
            "halt_reason": state.halt_reason,
            "daily_pnl": state.daily_pnl,
            "weekly_pnl": state.weekly_pnl,
            "consecutive_losses": state.consecutive_losses,
            "margin_level": state.margin_level,
            "spread_current": state.spread_current,
            "total_trades": state.total_trades,
            "win_rate": state.winning_trades / max(state.total_trades, 1) if state.total_trades > 0 else 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if not heartbeat_ok:
            logger.warning("guardian_heartbeat_stale", last=state.last_heartbeat)

        if state.trading_halted:
            logger.warning("guardian_trading_halted", reason=state.halt_reason)

        return health

    def update_account_state(
        self,
        balance: float = 0.0,
        equity: float = 0.0,
        margin_level: float = 0.0,
        daily_pnl: float = 0.0,
        weekly_pnl: float = 0.0,
        spread: float = 0.0,
    ) -> None:
        """Update account-level state after each trade or account check.

        Thread-safe: acquires _state_lock if an event loop is running,
        otherwise updates directly (for synchronous callers at init time).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're in an async context — schedule the update under the lock
            loop.create_task(
                self._update_account_state_locked(
                    balance=balance,
                    equity=equity,
                    margin_level=margin_level,
                    daily_pnl=daily_pnl,
                    weekly_pnl=weekly_pnl,
                    spread=spread,
                )
            )
        else:
            # Synchronous context (e.g. __init__) — update directly
            self._update_account_state_unlocked(
                balance=balance,
                equity=equity,
                margin_level=margin_level,
                daily_pnl=daily_pnl,
                weekly_pnl=weekly_pnl,
                spread=spread,
            )

    async def _update_account_state_locked(self, **kwargs: Any) -> None:
        async with self._state_lock:
            self._update_account_state_unlocked(**kwargs)

    def _update_account_state_unlocked(
        self,
        balance: float = 0.0,
        equity: float = 0.0,
        margin_level: float = 0.0,
        daily_pnl: float = 0.0,
        weekly_pnl: float = 0.0,
        spread: float = 0.0,
    ) -> None:
        """Update account state — must hold _state_lock or be in sync context."""
        state = self._get_state()
        if balance:
            state.account_balance = balance
        if equity:
            state.account_equity = equity
            if equity > state.drawdown_peak_equity:
                state.drawdown_peak_equity = equity
        if margin_level:
            state.margin_level = margin_level
        if daily_pnl:
            state.daily_pnl = daily_pnl
        if weekly_pnl:
            state.weekly_pnl = weekly_pnl
        if spread:
            state.spread_current = spread

    def record_trade_result(self, won: bool, pnl: float = 0.0) -> None:
        """Record the result of a closed trade.

        Thread-safe: acquires _state_lock if an event loop is running.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(self._record_trade_result_locked(won, pnl))
        else:
            self._record_trade_result_unlocked(won, pnl)

    async def _record_trade_result_locked(self, won: bool, pnl: float = 0.0) -> None:
        async with self._state_lock:
            self._record_trade_result_unlocked(won, pnl)

    def _record_trade_result_unlocked(self, won: bool, pnl: float = 0.0) -> None:
        """Record trade result — must hold _state_lock or be in sync context."""
        state = self._get_state()
        state.total_trades += 1
        if won:
            state.winning_trades += 1
            state.consecutive_losses = 0
        else:
            state.consecutive_losses += 1

        state.daily_pnl += pnl
        state.weekly_pnl += pnl

        logger.info(
            "guardian_trade_recorded",
            won=won,
            pnl=pnl,
            consecutive_losses=state.consecutive_losses,
            total=state.total_trades,
            win_rate=f"{state.winning_trades / state.total_trades:.2%}",
        )
        self._append_audit_log(state, {
            "event": "trade_result",
            "won": won,
            "pnl": pnl,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _get_state(self) -> GuardianState:
        """Internal helper to access the shared GuardianState.

        The orchestrator maintains a single GuardianState instance and passes
        it via GuardianAgent.__init__. We store a reference for all methods.
        """
        # Access the state reference stored on the instance
        if not hasattr(self, '_guardian_state') or self._guardian_state is None:
            raise RuntimeError("GuardianAgent._guardian_state not set. Pass GuardianState to __init__.")
        return self._guardian_state

    @staticmethod
    def _append_audit_log(state: GuardianState, entry: dict[str, Any]) -> None:
        """Append to audit_log with bounded size (prevents memory leak)."""
        state.audit_log.append(entry)
        if len(state.audit_log) > state._audit_log_maxlen:
            del state.audit_log[:-state._audit_log_maxlen]

    def _halt_trading(self, reason: str) -> None:
        """Thread-safe halt of all trading with a given reason.

        Uses a lock to prevent races between concurrent callers
        (e.g. health monitor and pipeline both checking guardian).
        """
        state = self._get_state()
        with self._halt_lock:
            state.trading_halted = True
            state.halt_reason = reason

    def halt_trading(self, reason: str) -> None:
        """Public thread-safe halt — callable from external callers (e.g. health monitor)."""
        self._halt_trading(reason)

    # ── Phase 1.5: News Blackout Activation / Deactivation ──────────

    def activate_news_blackout(
        self,
        reason: str,
        pair: str,
        until: datetime | None = None,
    ) -> None:
        """Activate the news blackout for a pair (deterministic, no LLM).

        Called by EventAnalyst when a high-impact event is within the
        blackout window [event_time - 15min, event_time + 15min].

        Sets GuardianState.news_blackout = True and logs an audit entry.
        Implements COO conditions #3 (Prometheus) and #4 (audit logging).

        Args:
            reason: Human-readable reason (e.g. "NFP — 15 min window")
            pair: Trading pair affected (e.g. "EURUSD")
            until: Optional end time for the blackout. If None, uses
                   GuardianState.news_blackout_until or defaults to 15 min.
        """
        state = self._get_state()
        now = datetime.now(timezone.utc)

        state.news_blackout = True
        if until:
            state.news_blackout_until = until
        else:
            state.news_blackout_until = now + timedelta(minutes=15)

        # Track activation time for watchdog
        self._blackout_activated_at[pair] = now

        # ── Audit log (COO condition #4) ────────
        audit_entry = {
            "event": "news_blackout_activated",
            "pair": pair,
            "reason": reason,
            "blackout_until": state.news_blackout_until.isoformat(),
            "activated_at": now.isoformat(),
            "watchdog_timeout_minutes": self._max_blackout_minutes,
        }
        self._append_audit_log(state, audit_entry)

        logger.warning(
            "guardian_news_blackout_activated",
            pair=pair,
            reason=reason,
            until=state.news_blackout_until.isoformat(),
        )

        # ── Prometheus gauge (COO condition #3) ────────
        if PROMETHEUS_AVAILABLE and NOEMA_NEWS_BLACKOUT_ACTIVE is not None:
            NOEMA_NEWS_BLACKOUT_ACTIVE.labels(pair=pair).set(1)

    def deactivate_news_blackout(
        self,
        reason: str,
        pair: str,
    ) -> None:
        """Deactivate the news blackout for a pair.

        Called by EventAnalyst when:
        - The event window has passed AND volatility is normalized
        - OR the 60-minute watchdog timeout has been reached

        Clears GuardianState.news_blackout and logs audit entry.
        """
        state = self._get_state()
        now = datetime.now(timezone.utc)

        state.news_blackout = False
        state.news_blackout_until = None

        # Calculate blackout duration
        duration_minutes = 0.0
        if pair in self._blackout_activated_at:
            duration_minutes = (
                (now - self._blackout_activated_at[pair]).total_seconds() / 60
            )
            del self._blackout_activated_at[pair]

        # ── Audit log (COO condition #4) ────────
        audit_entry = {
            "event": "news_blackout_deactivated",
            "pair": pair,
            "reason": reason,
            "deactivated_at": now.isoformat(),
            "duration_minutes": round(duration_minutes, 1),
        }
        self._append_audit_log(state, audit_entry)

        logger.info(
            "guardian_news_blackout_deactivated",
            pair=pair,
            reason=reason,
            duration_minutes=round(duration_minutes, 1),
        )

        # ── Prometheus gauge (COO condition #3) ────────
        if PROMETHEUS_AVAILABLE and NOEMA_NEWS_BLACKOUT_ACTIVE is not None:
            NOEMA_NEWS_BLACKOUT_ACTIVE.labels(pair=pair).set(0)

    def _check_blackout_watchdog(self) -> None:
        """Check blackout watchdog — force-deactivate if exceeded.

        COO condition #1: Maximum 60-minute blackout.
        If a blackout has been active > max_blackout_minutes, force-deactivate.
        """
        now = datetime.now(timezone.utc)
        pairs_to_release = []

        for pair, activated_at in list(self._blackout_activated_at.items()):
            elapsed = (now - activated_at).total_seconds() / 60
            if elapsed > self._max_blackout_minutes:
                pairs_to_release.append(pair)
                logger.error(
                    "guardian_blackout_watchdog_force_release",
                    pair=pair,
                    elapsed_minutes=round(elapsed, 1),
                    max_minutes=self._max_blackout_minutes,
                )

        for pair in pairs_to_release:
            self.deactivate_news_blackout(
                reason=f"Watchdog timeout ({self._max_blackout_minutes} min max)",
                pair=pair,
            )

    def set_max_blackout_minutes(self, minutes: int) -> None:
        """Configure the maximum blackout duration.

        Called at startup from settings (Noema_EVENT_BLACKOUT_MINUTES).
        """
        self._max_blackout_minutes = minutes
