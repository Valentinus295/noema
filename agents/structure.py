"""Market Structure Agent — understands the story of price.

Detects HH/HL/LH/LL, BOS, CHoCH to determine who controls the market.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import structlog

from noema.analysis.technical import TechnicalAnalyzer
from noema.analysis.smc import SMCForecaster
from noema.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)


class MarketStructureAgent(DeterministicAgent):
    """Agent #4 — Understands the story of price.

    Detects: HH, HL, LH, LL, BOS, CHoCH.
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
        """Analyze market structure from OHLCV data."""
        df: pd.DataFrame = context.get("price_data")
        if df is None or len(df) < 50:
            return AgentReport(agent_name=self.name, signal="NEUTRAL", reasoning="Insufficient data")

        # Detect structure
        structure = self.technical.detect_structure(df)

        # Detect BOS/CHoCH from SMC
        smc_structure = self.smc.detect_structure_breaks(df)

        # Combine
        combined_structure = structure["structure"]

        if smc_structure["choch_detected"]:
            combined_structure = smc_structure["bos_direction"].upper()

        signal_map = {"BULLISH": "BULLISH", "BEARISH": "BEARISH", "RANGE": "NEUTRAL"}
        signal = signal_map.get(combined_structure, "NEUTRAL")

        confidence = 0.0
        if combined_structure != "RANGE":
            confidence += 0.4
        if smc_structure["bos_detected"]:
            confidence += 0.3
        if structure["higher_highs"] and structure["higher_lows"]:
            confidence += 0.15
        elif structure["lower_highs"] and structure["lower_lows"]:
            confidence += 0.15

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=min(1.0, confidence),
            data={
                "structure": combined_structure,
                "higher_highs": structure["higher_highs"],
                "higher_lows": structure["higher_lows"],
                "lower_highs": structure["lower_highs"],
                "lower_lows": structure["lower_lows"],
                "bos_detected": smc_structure["bos_detected"],
                "choch_detected": smc_structure["choch_detected"],
                "swing_highs": structure.get("swing_highs", []),
                "swing_lows": structure.get("swing_lows", []),
            },
            reasoning=f"Structure: {combined_structure}. "
                      f"HH={structure['higher_highs']}, HL={structure['higher_lows']}, "
                      f"LH={structure['lower_highs']}, LL={structure['lower_lows']}. "
                      f"BOS={smc_structure['bos_detected']}, CHoCH={smc_structure['choch_detected']}",
        )


from noema.core.types import Bar, Direction, Timeframe, Verdict

def analyze_structure(symbol: str, bars: list[Bar]) -> Verdict:
    """Pure-function structure analysis for the 7-agent pipeline.

    Returns a Verdict for ConfluenceAgent to consume.
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

    # Convert bars to DataFrame
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
    smc_structure = smc.detect_structure_breaks(df)

    combined = structure["structure"]
    if smc_structure["choch_detected"]:
        combined = smc_structure["bos_direction"].upper()

    direction_map = {"BULLISH": Direction("bullish"), "BEARISH": Direction("bearish"), "RANGE": Direction("neutral")}
    direction = direction_map.get(combined, Direction("neutral"))

    strength = 0.0
    if combined != "RANGE":
        strength += 0.4
    if smc_structure["bos_detected"]:
        strength += 0.3
    if structure["higher_highs"] and structure["higher_lows"]:
        strength += 0.15
    elif structure["lower_highs"] and structure["lower_lows"]:
        strength += 0.15

    rationale = (
        f"Structure: {combined}. "
        f"HH={structure['higher_highs']}, HL={structure['higher_lows']}, "
        f"LH={structure['lower_highs']}, LL={structure['lower_lows']}. "
        f"BOS={smc_structure['bos_detected']}, CHoCH={smc_structure['choch_detected']}"
    )

    return Verdict(
        agent="StructureAgent",
        symbol=symbol,
        timeframe=Timeframe("H1"),
        direction=direction,
        strength=min(1.0, strength),
        rationale=rationale,
    )
