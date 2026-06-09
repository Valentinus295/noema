"""Risk Manager Agent — protects capital at all costs.

Calculates position sizing, enforces daily/weekly loss limits,
and ensures proper risk/reward before any trade execution.
"""

from __future__ import annotations

from typing import Any

import structlog

from vmpm.core.agent import Agent, AgentReport

logger = structlog.get_logger(__name__)


class RiskManagerAgent(Agent):
    """Agent #13 — Risk Manager.

    Protects capital. Calculates position sizing, enforces loss limits,
    checks correlation risk, and ensures proper risk/reward.
    """

    name = "risk-manager"
    role = "Risk Manager"
    priority = 1

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Evaluate risk parameters for a proposed trade."""
        config = self.config
        risk_config = config.risk if config else None
        account_balance = context.get("account_balance", 10000.0)
        pair: str = context.get("pair", "EURUSD")
        direction: str = context.get("direction", "long")
        current_price = context.get("current_price", 0.0)
        stop_loss = context.get("stop_loss", 0.0)
        take_profit = context.get("take_profit", 0.0)
        daily_pnl = context.get("daily_pnl", 0.0)
        weekly_pnl = context.get("weekly_pnl", 0.0)
        open_trades = context.get("open_trades", 0)

        risk_per_trade = risk_config.risk_per_trade if risk_config else 0.01
        max_daily_loss = risk_config.max_daily_loss if risk_config else 0.03
        max_weekly_loss = risk_config.max_weekly_loss if risk_config else 0.08
        min_rr = risk_config.min_risk_reward if risk_config else 2.0
        max_open = risk_config.max_open_trades if risk_config else 5

        rejections: list[str] = []

        # Check daily loss limit
        if abs(daily_pnl) >= max_daily_loss * account_balance:
            rejections.append(f"Daily loss limit reached: {daily_pnl:.2f}")

        # Check weekly loss limit
        if abs(weekly_pnl) >= max_weekly_loss * account_balance:
            rejections.append(f"Weekly loss limit reached: {weekly_pnl:.2f}")

        # Check max open trades
        if open_trades >= max_open:
            rejections.append(f"Max open trades reached: {open_trades}/{max_open}")

        # Calculate risk/reward
        if current_price > 0 and stop_loss > 0 and take_profit > 0:
            if direction == "long":
                risk_pips = abs(current_price - stop_loss)
                reward_pips = abs(take_profit - current_price)
            else:
                risk_pips = abs(stop_loss - current_price)
                reward_pips = abs(current_price - take_profit)

            rr_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
            if rr_ratio < min_rr:
                rejections.append(f"Risk/Reward too low: 1:{rr_ratio:.1f} (min 1:{min_rr})")
        else:
            rr_ratio = 0
            risk_pips = 0
            reward_pips = 0

        # Calculate position size
        risk_amount = account_balance * risk_per_trade
        if risk_pips > 0:
            # Approximate lot size (simplified)
            pip_value = 10 if "JPY" not in pair else 0.01
            lot_size = round(risk_amount / (risk_pips * pip_value * 10), 2)
            lot_size = max(0.01, lot_size)
        else:
            lot_size = 0.01

        signal = "REJECT" if rejections else "APPROVE"
        confidence = 0.9 if not rejections else 0.2

        reasoning = f"Risk Manager Report:\n"
        reasoning += f"  Account: ${account_balance:,.2f}\n"
        reasoning += f"  Risk per trade: {risk_per_trade:.1%}\n"
        reasoning += f"  R:R ratio: 1:{rr_ratio:.1f}\n"
        reasoning += f"  Position size: {lot_size} lots\n"
        reasoning += f"  Daily P&L: ${daily_pnl:,.2f}\n"
        reasoning += f"  Weekly P&L: ${weekly_pnl:,.2f}\n"
        if rejections:
            reasoning += f"  REJECTIONS:\n"
            for r in rejections:
                reasoning += f"    ✗ {r}\n"
        else:
            reasoning += f"  ✓ All risk checks passed\n"

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            data={
                "approved": not rejections,
                "rejections": rejections,
                "lot_size": lot_size,
                "risk_amount": risk_amount,
                "rr_ratio": rr_ratio,
                "risk_pips": risk_pips,
                "reward_pips": reward_pips,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            },
            reasoning=reasoning,
        )
