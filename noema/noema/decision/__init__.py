"""
Risk Context — injectable risk state for all LLM agent prompts.

Pattern inspired by TradingAgents' practice of keeping every agent
risk-aware through prompt injection. Instead of relying on a single
risk-agent gate, every LLM agent receives current risk context so
risk awareness is distributed across the system.

Usage:
    from noema.decision.risk_context import RiskContext, inject_risk_context

    risk = RiskContext(
        exposure_pct=12.5,
        daily_pnl=-45.30,
        consecutive_losses=2,
        drawdown_pct=3.2,
    )

    system_prompt = inject_risk_context(
        base_prompt,
        risk,
        agent_name="trade-thesis",
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RiskContext:
    """Current risk state for injection into agent prompts.

    Provides every agent with awareness of:
    - Current exposure and margin usage
    - Recent P&L performance
    - Drawdown severity
    - Streak patterns (consecutive wins/losses)
    - Correlation warnings
    - Upcoming high-impact events

    This enables risk-aware reasoning at every decision point,
    not just at the risk-agent gate.
    """

    # ── Account State ────────────────────────────────────────────
    exposure_pct: float = 0.0
    """Percentage of equity currently at risk (margin / equity * 100)."""

    margin_level: float = 0.0
    """Current margin level (equity / margin * 100)."""

    drawdown_pct: float = 0.0
    """Current drawdown from peak equity."""

    free_margin: float = 0.0
    """Available margin for new positions."""

    account_risk_level: str = "UNKNOWN"
    """Overall risk level: LOW, MODERATE, HIGH, CRITICAL."""

    # ── Performance ──────────────────────────────────────────────
    daily_pnl: float = 0.0
    """Current day's P&L in account currency."""

    weekly_pnl: float = 0.0
    """Current week's P&L in account currency."""

    monthly_pnl: float = 0.0
    """Current month's P&L in account currency."""

    consecutive_losses: int = 0
    """Number of consecutive losing trades."""

    consecutive_wins: int = 0
    """Number of consecutive winning trades."""

    win_rate_30d: float = 0.0
    """Win rate over the last 30 days (0.0-1.0)."""

    # ── Position Context ─────────────────────────────────────────
    position_count: int = 0
    """Number of currently open positions."""

    open_symbols: list[str] = field(default_factory=list)
    """Symbols with open positions."""

    correlation_warnings: list[str] = field(default_factory=list)
    """Warnings about correlated positions."""

    # ── Event Context ────────────────────────────────────────────
    high_impact_events_soon: bool = False
    """Are there high-impact economic events within 24h?"""

    upcoming_events: list[str] = field(default_factory=list)
    """Names of upcoming high-impact events."""

    session_volatility: str = "NORMAL"
    """Current session volatility: LOW, NORMAL, HIGH."""

    # ── Limits ──────────────────────────────────────────────────
    max_daily_loss: float = 0.0
    """Maximum daily loss limit."""

    max_position_count: int = 0
    """Maximum number of concurrent positions."""

    daily_loss_remaining: float = 0.0
    """Remaining daily loss budget (max_daily_loss - abs(daily_pnl))."""

    # ── Metadata ────────────────────────────────────────────────
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source: str = "unknown"

    # ── Properties ───────────────────────────────────────────────

    @property
    def is_critical(self) -> bool:
        """Is risk at a critical level that should prevent all trading?"""
        return (
            self.account_risk_level == "CRITICAL"
            or self.margin_level < 150
            or self.drawdown_pct > 20
            or self.consecutive_losses >= 5
        )

    @property
    def is_elevated(self) -> bool:
        """Is risk elevated, requiring reduced position sizing?"""
        return (
            self.account_risk_level in ("HIGH",)
            or self.margin_level < 300
            or self.drawdown_pct > 10
            or self.consecutive_losses >= 3
            or self.high_impact_events_soon
        )

    @property
    def risk_multiplier(self) -> float:
        """Risk multiplier for position sizing (1.0 = normal, 0.0 = no trade)."""
        if self.is_critical:
            return 0.0
        if self.is_elevated:
            return 0.5
        if self.account_risk_level == "MODERATE":
            return 0.75
        return 1.0


# ── Context Injection ──────────────────────────────────────────────────

def inject_risk_context(
    base_prompt: str,
    risk: RiskContext,
    agent_name: str = "unknown",
) -> str:
    """Inject risk context into an agent's system prompt.

    Returns the base prompt with a risk context section appended.
    The section is tailored to the agent's role.

    Args:
        base_prompt: The agent's original system prompt
        risk: Current RiskContext with account state and performance
        agent_name: Name of the agent receiving the context

    Returns:
        Modified prompt with risk context section
    """
    if risk.is_critical and agent_name in ("thesis", "cio", "execution"):
        # Critical risk — no-trade override for decision-makers
        critical_block = _build_critical_block(risk)
        return base_prompt + "\n\n" + critical_block

    risk_block = _build_risk_block(risk, agent_name)
    return base_prompt + "\n\n" + risk_block


def inject_risk_context_to_messages(
    messages: list[dict[str, str]],
    risk: RiskContext,
    agent_name: str = "unknown",
) -> list[dict[str, str]]:
    """Inject risk context into the system message of a messages list.

    Args:
        messages: List of messages in OpenAI format
        risk: Current RiskContext
        agent_name: Name of the agent

    Returns:
        Modified messages list with risk context in system message
    """
    result = list(messages)
    for i, msg in enumerate(result):
        if msg.get("role") == "system":
            result[i] = {
                "role": "system",
                "content": inject_risk_context(
                    msg["content"], risk, agent_name
                ),
            }
            break
    return result


def _build_risk_block(risk: RiskContext, agent_name: str) -> str:
    """Build a risk context block for agent prompts."""
    lines = [
        "## Current Risk Context",
        "Before making your decision, consider the current risk state:",
        "",
    ]

    # Account state
    if risk.exposure_pct > 0:
        lines.append(f"- **Exposure**: {risk.exposure_pct:.1f}% of equity at risk")
    if risk.margin_level > 0:
        lines.append(f"- **Margin Level**: {risk.margin_level:.0f}%")
    if risk.drawdown_pct > 0:
        lines.append(f"- **Drawdown**: {risk.drawdown_pct:.1f}% from peak")
    if risk.free_margin > 0:
        lines.append(f"- **Free Margin**: ${risk.free_margin:,.0f}")

    # Performance
    if risk.daily_pnl != 0:
        direction = "+" if risk.daily_pnl >= 0 else ""
        lines.append(f"- **Today's P&L**: {direction}{risk.daily_pnl:,.2f}")
    if risk.consecutive_losses > 0:
        lines.append(f"- **Consecutive Losses**: {risk.consecutive_losses} ⚠️")
    if risk.consecutive_wins > 0:
        lines.append(f"- **Consecutive Wins**: {risk.consecutive_wins}")

    # Position warnings
    if risk.open_symbols:
        lines.append(f"- **Open Positions**: {', '.join(risk.open_symbols)}")
    if risk.correlation_warnings:
        for warning in risk.correlation_warnings:
            lines.append(f"- ⚠️ {warning}")

    # Events
    if risk.high_impact_events_soon:
        lines.append("- ⚠️ **High-Impact Events Soon**: Exercise extra caution")
        if risk.upcoming_events:
            for event in risk.upcoming_events[:3]:
                lines.append(f"  - {event}")

    # Agent-specific guidance
    lines.append("")
    if agent_name in ("thesis", "cio", "execution"):
        if risk.is_elevated:
            lines.append(
                "**Given elevated risk, consider smaller position sizes "
                "and wider stop losses. If in doubt, NO_TRADE is the safer option.**"
            )
        elif risk.is_critical:
            lines.append(
                "**CRITICAL RISK STATE: Do not open new positions. "
                "Capital preservation is the only priority.**"
            )

    return "\n".join(lines)


def _build_critical_block(risk: RiskContext) -> str:
    """Build a critical risk block that overrides normal decision-making."""
    return (
        "## ⛔ CRITICAL RISK STATE — OVERRIDE ACTIVE\n\n"
        "The system is in a **CRITICAL** risk state. You MUST NOT approve any new trades.\n\n"
        f"- Consecutive Losses: {risk.consecutive_losses}\n"
        f"- Drawdown: {risk.drawdown_pct:.1f}%\n"
        f"- Risk Level: {risk.account_risk_level}\n\n"
        "**Your only valid decision is NO_TRADE. Capital preservation is mandatory.**\n"
        "Do NOT propose, approve, or execute any trade regardless of how good the setup looks.\n"
        "There will always be another opportunity. Protecting capital comes first."
    )


# ── RiskContext Builder ────────────────────────────────────────────────

def build_risk_context_from_account(
    account_state: dict[str, Any],
    broker_status: dict[str, Any] | None = None,
    calendar: dict[str, Any] | None = None,
    correlation: dict[str, Any] | None = None,
) -> RiskContext:
    """Build a RiskContext from account state and optional context sources.

    Args:
        account_state: Output from get_account_state()
        broker_status: Optional output from get_broker_status()
        calendar: Optional output from get_economic_calendar()
        correlation: Optional output from get_currency_correlation()

    Returns:
        Populated RiskContext
    """
    risk = RiskContext()

    # Map account state
    risk.exposure_pct = account_state.get("exposure_pct", 0.0)
    risk.margin_level = account_state.get("margin_level", 0.0)
    risk.drawdown_pct = account_state.get("drawdown_pct", 0.0)
    risk.free_margin = account_state.get("free_margin", 0.0)
    risk.account_risk_level = account_state.get("risk_level", "UNKNOWN")
    risk.position_count = account_state.get("position_count", 0)
    risk.open_symbols = [
        p["symbol"] for p in account_state.get("positions", [])
    ]
    risk.daily_pnl = account_state.get("total_pnl", 0.0)

    # Map event calendar
    if calendar:
        risk.high_impact_events_soon = calendar.get("high_impact_count", 0) > 0
        risk.upcoming_events = [
            e["event"] for e in calendar.get("upcoming_events", [])
            if e.get("impact") == "high"
        ]
        if calendar.get("risk_warning"):
            risk.upcoming_events.append(calendar["risk_warning"])

    # Map correlation warnings
    if correlation and correlation.get("risk_warning"):
        risk.correlation_warnings = [correlation["risk_warning"]]

    # Set limits (from config or defaults)
    risk.max_daily_loss = 100.0  # TODO: from config
    risk.max_position_count = 5  # TODO: from config
    risk.daily_loss_remaining = risk.max_daily_loss - abs(risk.daily_pnl)

    return risk
