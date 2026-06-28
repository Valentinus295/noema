"""Institutional Footprint Agent — finds where smart money acted.

Enhanced with JARVIS SMC integration:
- Order blocks with validation status and impulse tracking
- FVGs with mitigation state (not just filled/unfilled)
- Liquidity sweeps with displacement measurement
- Confluence scoring across OB + FVG + sweep patterns
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import structlog

from noema.analysis.smc import (
    SMCForecaster,
    SMCReport,
    OrderBlock,
    FairValueGap,
    LiquiditySweep,
)
from noema.core.modern_agent import DeterministicAgent, AgentReport
from noema.core.registry import AgentRegistry

logger = structlog.get_logger(__name__)


@AgentRegistry.register("institutional-footprint", layer="analysis")
class InstitutionalFootprintAgent(DeterministicAgent):
    """Agent #5 — Finds where smart money acted.

    Detects: Validated/Invalidated Order Blocks, Mitigated/Unmitigated FVGs,
    Liquidity Sweeps with displacement analysis.

    Answers: Where did institutions enter? Where will they defend positions?
    What zones are likely to attract price?

    Enhanced with JARVIS patterns:
    - OB validation based on price respecting the zone
    - FVG mitigation tracking (partial fill vs full fill)
    - Sweep displacement measurement for reversal confirmation
    - Confluence scoring: sweep + OB + FVG overlap = high probability zone
    """

    name = "institutional-footprint"
    role = "Institutional Footprint Analyst"
    priority = 7

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.smc = SMCForecaster(self.config)

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Analyze institutional footprints in price data.

        Runs comprehensive SMC analysis and evaluates:
        1. Order block quality (validation, impulse strength, wick cleanliness)
        2. FVG significance (gap size, mitigation state)
        3. Sweep quality (displacement, wick penetration)
        4. Confluence between all three patterns
        """
        df: pd.DataFrame = context.get("price_data")
        if df is None or len(df) < 50:
            return AgentReport(
                agent_name=self.name,
                signal="NEUTRAL",
                reasoning="Insufficient data (< 50 bars)",
            )

        report = self.smc.analyze(df)

        # Separate and score OBs
        bullish_obs = self._score_blocks(
            [ob for ob in report.order_blocks if ob.type == "bullish"]
        )
        bearish_obs = self._score_blocks(
            [ob for ob in report.order_blocks if ob.type == "bearish"]
        )

        # Score FVGs
        bullish_fvgs = [f for f in report.fair_value_gaps if f.type == "bullish"]
        bearish_fvgs = [f for f in report.fair_value_gaps if f.type == "bearish"]

        # Score sweeps
        buy_sweeps = [s for s in report.liquidity_sweeps if s.type == "buy_side"]
        sell_sweeps = [s for s in report.liquidity_sweeps if s.type == "sell_side"]

        # Determine signal
        signal, confidence = self._determine_signal(
            bullish_obs, bearish_obs,
            bullish_fvgs, bearish_fvgs,
            buy_sweeps, sell_sweeps,
            report,
        )

        # Build data
        data = {
            "order_blocks": {
                "bullish": [
                    {
                        "midpoint": ob.midpoint, "strength": ob.strength,
                        "validated": ob.validated, "invalidated": ob.invalidated,
                        "impulse_candles": ob.impulse_candles, "wick_pct": ob.wick_pct,
                    }
                    for ob in bullish_obs[-5:]
                ],
                "bearish": [
                    {
                        "midpoint": ob.midpoint, "strength": ob.strength,
                        "validated": ob.validated, "invalidated": ob.invalidated,
                        "impulse_candles": ob.impulse_candles,
                    }
                    for ob in bearish_obs[-5:]
                ],
            },
            "fair_value_gaps": {
                "bullish": [
                    {"midpoint": f.midpoint, "mitigated": f.mitigated,
                     "filled": f.filled, "gap_size_pct": f.gap_size_pct}
                    for f in bullish_fvgs[-5:]
                ],
                "bearish": [
                    {"midpoint": f.midpoint, "mitigated": f.mitigated,
                     "filled": f.filled, "gap_size_pct": f.gap_size_pct}
                    for f in bearish_fvgs[-5:]
                ],
            },
            "liquidity_sweeps": {
                "buy_side": [
                    {"level": s.level, "displacement": s.displacement,
                     "wick_pct": s.wick_pct}
                    for s in buy_sweeps[-3:]
                ],
                "sell_side": [
                    {"level": s.level, "displacement": s.displacement,
                     "wick_pct": s.wick_pct}
                    for s in sell_sweeps[-3:]
                ],
            },
            "confluence": {
                "bullish_ob_count": len(bullish_obs),
                "bearish_ob_count": len(bearish_obs),
                "validated_ob_count": sum(1 for ob in report.order_blocks if ob.validated),
                "unmitigated_fvg_count": sum(1 for f in report.fair_value_gaps if not f.mitigated),
                "sweep_count": len(report.liquidity_sweeps),
                "bos_aligned": report.bos_detected,
                "choch_detected": report.choch_detected,
            },
            "setup": self._serialize_setup(report.setup) if report.setup else None,
        }

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            data=data,
            reasoning=report.reasoning,
        )

    def _score_blocks(self, blocks: list[OrderBlock]) -> list[OrderBlock]:
        """Score and sort order blocks by quality.

        Quality factors:
        - validated=True: +0.2 to strength
        - impulse_candles >= 3: +0.15
        - wick_pct < 0.3: +0.1
        """
        scored = list(blocks)
        for ob in scored:
            adjusted = ob.strength
            if ob.validated:
                adjusted += 0.2
            if ob.impulse_candles >= 3:
                adjusted += 0.15
            if ob.wick_pct < 0.3:
                adjusted += 0.1
            ob.strength = min(1.0, adjusted)
        scored.sort(key=lambda o: o.strength, reverse=True)
        return scored

    def _determine_signal(
        self,
        bullish_obs: list[OrderBlock],
        bearish_obs: list[OrderBlock],
        bullish_fvgs: list[FairValueGap],
        bearish_fvgs: list[FairValueGap],
        buy_sweeps: list[LiquiditySweep],
        sell_sweeps: list[LiquiditySweep],
        report: SMCReport,
    ) -> tuple[str, float]:
        """Determine signal based on institutional footprint confluence.

        Uses multi-factor voting: sweep bias + OB balance + FVG balance
        + structure alignment. Valid setup overrides all.
        """
        # If valid setup exists, use it
        if report.setup and report.setup.valid:
            setup = report.setup
            signal = "BULLISH" if setup.direction == "BUY" else "BEARISH"
            confidence = 0.5 + (setup.confluence_score * 0.1)
            return signal, min(1.0, confidence)

        # Sweep-based bias
        sell_sweep_displacement = sum(abs(s.displacement) for s in sell_sweeps[-3:]) if sell_sweeps else 0.0
        buy_sweep_displacement = sum(abs(s.displacement) for s in buy_sweeps[-3:]) if buy_sweeps else 0.0

        sweep_bias = "bullish" if sell_sweep_displacement > buy_sweep_displacement else \
                     "bearish" if buy_sweep_displacement > sell_sweep_displacement else "neutral"

        # OB balance
        bull_ob_strength = sum(ob.strength for ob in bullish_obs[-3:]) if bullish_obs else 0.0
        bear_ob_strength = sum(ob.strength for ob in bearish_obs[-3:]) if bearish_obs else 0.0
        ob_bias = "bullish" if bull_ob_strength > bear_ob_strength else \
                  "bearish" if bear_ob_strength > bull_ob_strength else "neutral"

        # FVG balance
        bull_fvg_count = sum(1 for f in bullish_fvgs if not f.mitigated)
        bear_fvg_count = sum(1 for f in bearish_fvgs if not f.mitigated)
        fvg_bias = "bullish" if bull_fvg_count > bear_fvg_count else \
                   "bearish" if bear_fvg_count > bull_fvg_count else "neutral"

        # Structure alignment
        structure_bias = report.bos_direction if report.bos_detected or report.choch_detected else "none"

        # Combine biases
        biases = [sweep_bias, ob_bias, fvg_bias]
        if structure_bias != "none":
            biases.append(structure_bias)

        bull_votes = sum(1 for b in biases if b == "bullish")
        bear_votes = sum(1 for b in biases if b == "bearish")

        if bull_votes > bear_votes:
            signal = "BULLISH"
        elif bear_votes > bull_votes:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"

        # Confidence
        confidence = report.confidence
        if signal != "NEUTRAL":
            agreements = bull_votes if signal == "BULLISH" else bear_votes
            confidence += 0.05 * agreements

            if sweep_bias == signal.lower():
                total_displacement = max(sell_sweep_displacement, buy_sweep_displacement)
                if total_displacement > 0:
                    confidence += 0.1

            validated_obs = [ob for ob in report.order_blocks
                           if ob.validated and ob.type == ("bullish" if signal == "BULLISH" else "bearish")]
            if validated_obs:
                confidence += 0.05 * min(3, len(validated_obs))

        return signal, min(1.0, confidence)

    def _serialize_setup(self, setup) -> dict[str, Any]:
        """Serialize Setup to JSON-safe dict."""
        if setup is None:
            return None
        return {
            "direction": setup.direction,
            "entry_price": setup.entry_price,
            "stop_loss": setup.stop_loss,
            "take_profit": setup.take_profit,
            "confluence_score": setup.confluence_score,
            "valid": setup.valid,
            "reasoning": setup.reasoning,
            "htf_trend": setup.htf_trend,
        }
