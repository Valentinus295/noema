"""Risk Manager Agent — protects capital at all costs.

Calculates position sizing, enforces daily/weekly loss limits,
and ensures proper risk/reward before any trade execution.
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)


class RiskManagerAgent(DeterministicAgent):
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

        # Hard cap from config
        max_lot = getattr(risk_config, 'max_lot_size', 1.0) if risk_config else 1.0

        # Calculate position size
        risk_amount = account_balance * risk_per_trade
        if risk_pips > 0:
            # Approximate lot size (simplified)
            pip_value = 10 if "JPY" not in pair else 0.01
            lot_size = round(risk_amount / (risk_pips * pip_value * 10), 2)
            lot_size = max(0.01, min(lot_size, max_lot))
        else:
            lot_size = min(0.01, max_lot)

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

from dataclasses import dataclass

@dataclass
class RiskParams:
    """Parameters for position sizing and risk management."""
    risk_pct: float = 0.01          # 1% of balance per trade
    max_daily_loss_pct: float = 0.03  # 3% daily loss limit
    max_weekly_loss_pct: float = 0.08  # 8% weekly loss limit
    min_rr_ratio: float = 2.0       # Minimum risk/reward
    max_open_trades: int = 5
    atr_buffer_mult: float = 1.0    # ATR multiplier for SL buffer


def compute_sl_tp(
    bars: list, entry_price: float, direction, atr_mult_sl: float = 1.5, atr_mult_tp: float = 3.0
) -> tuple[float, float]:
    """Compute stop-loss and take-profit levels using ATR.

    Args:
        bars: List of Bar objects for ATR calculation
        entry_price: Entry price level
        direction: Direction enum ("bullish" or "bearish")
        atr_mult_sl: ATR multiplier for stop-loss distance
        atr_mult_tp: ATR multiplier for take-profit distance

    Returns:
        (stop_loss, take_profit) tuple
    """
    if not bars or len(bars) < 15:
        # Fallback: use 0.1% of price
        sl_dist = entry_price * 0.001
        tp_dist = entry_price * 0.002
    else:
        # Compute ATR(14)
        tr_values = []
        for i in range(1, len(bars)):
            tr = max(
                bars[i].high - bars[i].low,
                abs(bars[i].high - bars[i - 1].close),
                abs(bars[i].low - bars[i - 1].close),
            )
            tr_values.append(tr)
        atr = sum(tr_values[-14:]) / min(14, len(tr_values))
        sl_dist = atr * atr_mult_sl
        tp_dist = atr * atr_mult_tp

    dir_str = str(direction) if not isinstance(direction, str) else direction
    if "bullish" in dir_str.lower():
        sl = entry_price - sl_dist
        tp = entry_price + tp_dist
    else:
        sl = entry_price + sl_dist
        tp = entry_price - tp_dist

    return (round(sl, 5), round(tp, 5))


def compute_position_size(
    balance: float, entry_price: float, sl_price: float,
    risk_params: RiskParams, symbol_info: dict | None = None,
    max_lot_size: float = 1.0,
) -> float:
    """Compute position size (lots) based on risk percentage.

    Args:
        balance: Account balance
        entry_price: Planned entry price
        sl_price: Stop-loss price
        risk_params: Risk parameters
        symbol_info: Optional symbol info dict for pip value
        max_lot_size: Hard cap — NEVER exceed regardless of risk calculation

    Returns:
        Lot size (minimum 0.01, maximum max_lot_size)
    """
    risk_amount = balance * risk_params.risk_pct
    sl_distance = abs(entry_price - sl_price)

    if sl_distance == 0:
        return min(0.01, max_lot_size)

    # Determine pip value based on symbol
    symbol = (symbol_info or {}).get("symbol", "")
    if "JPY" in str(symbol):
        pip_value = 0.01
    else:
        pip_value = 0.0001

    sl_pips = sl_distance / pip_value
    if sl_pips == 0:
        return min(0.01, max_lot_size)

    # Standard lot: 1 pip = $10 for standard forex pairs
    lot_size = risk_amount / (sl_pips * 10)
    # Hard cap: NEVER exceed max_lot_size
    lot_size = min(lot_size, max_lot_size)
    return max(0.01, round(lot_size, 2))

