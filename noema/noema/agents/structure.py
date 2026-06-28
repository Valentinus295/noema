"""Market Structure Agent — understands the story of price.

Enhanced with JARVIS SMC integration:
- Fractal swing detection with walk-forward BOS/CHoCH tracking
- Produces SMCReport objects with swing history and structure events
- Distinguishes BOS (continuation) vs CHoCH (reversal)
- Multi-timeframe structure analysis for deeper context
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import structlog

from noema.analysis.technical import TechnicalAnalyzer
from noema.analysis.smc import SMCForecaster, SMCReport, StructureEvent, Setup
from noema.core.modern_agent import DeterministicAgent, AgentReport
from noema.core.registry import AgentRegistry

logger = structlog.get_logger(__name__)


@AgentRegistry.register("market-structure", layer="analysis")
class MarketStructureAgent(DeterministicAgent):
    """Agent #4 — Understands the story of price.

    Uses JARVIS-style structure tracking:
    - Fractal swing detection (unique max/min with configurable lookback)
    - Walk-forward BOS/CHoCH detection with StructureEvent history
    - Trend initialization and reversal detection

    Detects: HH, HL, LH, LL, BOS, CHoCH, structure events.
    Answers: Who is controlling the market? Buyers? Sellers? Has structure changed?
    """

    name = "market-structure"
    role = "Market Structure Analyst"
    priority = 8

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.technical = TechnicalAnalyzer(self.config)
        self.smc = SMCForecaster(self.config)

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Analyze market structure from OHLCV data.

        Produces a rich SMCReport with:
        - Swing points (fractal detection)
        - Structure events (BOS/CHoCH chronology)
        - Current trend from walk-forward tracking
        - Optional entry setup if confluence detected
        """
        df: pd.DataFrame = context.get("price_data")
        if df is None or len(df) < 50:
            return AgentReport(
                agent_name=self.name,
                signal="NEUTRAL",
                reasoning="Insufficient data (< 50 bars)",
                data={"smc_report": None},
            )

        # Classic structure detection (HH/HL/LH/LL)
        tech_structure = self.technical.detect_structure(df)

        # JARVIS-style SMC structure (swings + BOS/CHoCH events)
        smc_report = self.smc.analyze(df)

        # Determine combined signal
        signal, confidence, reasoning = self._evaluate_structure(
            tech_structure, smc_report, df
        )

        # Build rich data payload
        data = {
            "smc_report": self._serialize_smc_report(smc_report),
            "classic_structure": {
                "structure": tech_structure["structure"],
                "higher_highs": tech_structure["higher_highs"],
                "higher_lows": tech_structure["higher_lows"],
                "lower_highs": tech_structure["lower_highs"],
                "lower_lows": tech_structure["lower_lows"],
            },
            "swing_points": {
                "highs": tech_structure.get("swing_highs", []),
                "lows": tech_structure.get("swing_lows", []),
            },
            "structure_events": smc_report.structure_events,
            "current_trend": smc_report.current_trend,
            "setup": self._serialize_setup(smc_report.setup) if smc_report.setup else None,
        }

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            data=data,
            reasoning=reasoning,
        )

    def _evaluate_structure(
        self,
        tech_structure: dict[str, Any],
        smc_report: SMCReport,
        df: pd.DataFrame,
    ) -> tuple[str, float, str]:
        """Evaluate structure from both classic and SMC analysis.

        Signal logic:
        - CHoCH detected → strong directional signal (reversal)
        - BOS detected → continuation signal
        - Classic HH/HL → bullish, LH/LL → bearish
        - Multiple structure events → higher confidence
        """
        parts: list[str] = []
        signal = "NEUTRAL"
        confidence = 0.0

        # Classic structure
        classic_struct = tech_structure["structure"]
        parts.append(f"Classic structure: {classic_struct}")

        hh = tech_structure["higher_highs"]
        hl = tech_structure["higher_lows"]
        lh = tech_structure["lower_highs"]
        ll = tech_structure["lower_lows"]

        # SMC structure events
        n_events = len(smc_report.structure_events)
        n_bos = sum(1 for e in smc_report.structure_events if e.type == "BOS")
        n_choch = sum(1 for e in smc_report.structure_events if e.type == "CHoCH")

        parts.append(f"SMC trend: {smc_report.current_trend.upper()} "
                     f"({n_events} events: {n_bos}BOS, {n_choch}CHoCH)")

        # Signal determination
        if smc_report.choch_detected:
            if smc_report.bos_direction == "bullish":
                signal = "BULLISH"
                confidence = 0.5 + (0.1 * min(3, n_events))
                parts.append("CHoCH bullish — trend reversal to upside")
            else:
                signal = "BEARISH"
                confidence = 0.5 + (0.1 * min(3, n_events))
                parts.append("CHoCH bearish — trend reversal to downside")

        elif smc_report.bos_detected:
            if smc_report.bos_direction == "bullish":
                signal = "BULLISH"
                confidence = 0.35 + (0.08 * min(4, n_bos))
                parts.append(f"BOS bullish — uptrend continuation ({n_bos} confirmations)")
            else:
                signal = "BEARISH"
                confidence = 0.35 + (0.08 * min(4, n_bos))
                parts.append(f"BOS bearish — downtrend continuation ({n_bos} confirmations)")

        elif classic_struct == "BULLISH" and hh and hl:
            signal = "BULLISH"
            confidence = 0.3
            parts.append("Classic bullish structure (HH+HL) without SMC confirmation")

        elif classic_struct == "BEARISH" and lh and ll:
            signal = "BEARISH"
            confidence = 0.3
            parts.append("Classic bearish structure (LH+LL) without SMC confirmation")

        else:
            parts.append("Ranging market — no clear structure signal")

        # Confidence adjustments
        if signal in ("BULLISH", "BEARISH"):
            recent_bos = [
                e for e in smc_report.structure_events[-5:]
                if e.type == "BOS" and e.direction == signal.lower()
            ]
            if len(recent_bos) >= 3:
                confidence += 0.1
                parts.append(f"Strong trend: {len(recent_bos)} recent BOS in same direction")

        # Setup confluence
        if smc_report.setup and smc_report.setup.valid:
            setup_dir = smc_report.setup.direction
            if (signal == "BULLISH" and setup_dir == "BUY") or \
               (signal == "BEARISH" and setup_dir == "SELL"):
                confidence += 0.1
                parts.append(f"Setup alignment: {setup_dir} setup validates structure")

        confidence = min(1.0, confidence)
        reasoning = " | ".join(parts)
        reasoning += f"\n{smc_report.reasoning}"

        return signal, confidence, reasoning

    def _serialize_smc_report(self, report: SMCReport) -> dict[str, Any]:
        """Serialize SMCReport to JSON-safe dict."""
        return {
            "bos_detected": report.bos_detected,
            "choch_detected": report.choch_detected,
            "bos_direction": report.bos_direction,
            "current_trend": report.current_trend,
            "confidence": report.confidence,
            "n_order_blocks": len(report.order_blocks),
            "n_fvgs": len(report.fair_value_gaps),
            "n_sweeps": len(report.liquidity_sweeps),
            "n_swings": len(report.swings),
            "n_structure_events": len(report.structure_events),
            "structure_events": [
                {
                    "type": e.type,
                    "direction": e.direction,
                    "price": e.price,
                    "index": e.index,
                    "confidence": e.confidence,
                }
                for e in report.structure_events[-5:]
            ],
            "swings": {
                "highs": [s.price for s in report.swings if s.type == "high"][-6:],
                "lows": [s.price for s in report.swings if s.type == "low"][-6:],
            },
            "order_blocks": [
                {"type": ob.type, "midpoint": ob.midpoint, "strength": ob.strength,
                 "validated": ob.validated}
                for ob in report.order_blocks[-5:]
            ],
            "reasoning": report.reasoning,
        }

    def _serialize_setup(self, setup: Setup) -> dict[str, Any]:
        """Serialize Setup to JSON-safe dict."""
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


# ======================================================================
# Pure-function pipeline interface (backward compatible)
# ======================================================================

from noema.core.types import Bar, Direction, Timeframe, Verdict


def analyze_structure(symbol: str, bars: list[Bar]) -> Verdict:
    """Pure-function structure analysis for the 7-agent pipeline.

    Returns a Verdict for ConfluenceAgent to consume.
    Enhanced with JARVIS-style SMC structure analysis.
    """
    import pandas as pd

    if len(bars) < 50:
        return Verdict(
            agent="StructureAgent",
            symbol=symbol,
            timeframe=Timeframe("H1"),
            direction=Direction("neutral"),
            strength=0.0,
            rationale="Insufficient data for structure analysis",
        )

    df = pd.DataFrame([
        {"time": b.time, "open": b.open, "high": b.high,
         "low": b.low, "close": b.close, "volume": b.volume}
        for b in bars
    ])

    from noema.analysis.technical import TechnicalAnalyzer
    from noema.analysis.smc import SMCForecaster

    tech = TechnicalAnalyzer()
    smc = SMCForecaster()

    structure = tech.detect_structure(df)
    smc_report = smc.analyze(df)

    combined = structure["structure"]
    if smc_report.choch_detected:
        combined = smc_report.bos_direction.upper()
    elif smc_report.bos_detected and combined == "RANGE":
        combined = smc_report.bos_direction.upper()

    direction_map = {
        "BULLISH": Direction("bullish"),
        "BEARISH": Direction("bearish"),
        "RANGE": Direction("neutral"),
    }
    direction = direction_map.get(combined, Direction("neutral"))

    strength = 0.0
    if combined != "RANGE":
        strength += 0.35
    if smc_report.choch_detected:
        strength += 0.25
    elif smc_report.bos_detected:
        strength += 0.2
    if structure["higher_highs"] and structure["higher_lows"]:
        strength += 0.15
    elif structure["lower_highs"] and structure["lower_lows"]:
        strength += 0.15
    n_bos = sum(1 for e in smc_report.structure_events if e.type == "BOS")
    strength += 0.03 * min(5, n_bos)

    rationale = (
        f"Structure: {combined}. "
        f"HH={structure['higher_highs']}, HL={structure['higher_lows']}, "
        f"LH={structure['lower_highs']}, LL={structure['lower_lows']}. "
        f"BOS={smc_report.bos_detected}, CHoCH={smc_report.choch_detected}. "
        f"SMC trend: {smc_report.current_trend}. "
        f"Structure events: {len(smc_report.structure_events)} "
        f"({sum(1 for e in smc_report.structure_events if e.type == 'BOS')} BOS, "
        f"{sum(1 for e in smc_report.structure_events if e.type == 'CHoCH')} CHoCH)"
    )

    return Verdict(
        agent="StructureAgent",
        symbol=symbol,
        timeframe=Timeframe("H1"),
        direction=direction,
        strength=min(1.0, strength),
        rationale=rationale,
    )
