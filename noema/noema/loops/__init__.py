"""NOEMA Trading Loops — concrete loop implementations.

Each loop inherits from TradingLoop and implements a single ``tick()`` method.

Loop hierarchy (priority 0 = highest):
    0  SafetyLoop       1s    Guardian check_all — can halt everything
    1  TradingLoop      60s   Core OODA cycle: Data → Analysis → Decision → Execution
    2  LearningLoop     1h    Track outcomes, update agent weights
    2  CalibrationLoop  1d    Measure prediction accuracy, recalibrate thresholds
    2  RegimeLoop       5m    Monitor volatility regime shifts
"""

from noema.loops.safety_loop import SafetyLoop
from noema.loops.trading_loop import TradingLoopLoop
from noema.loops.learning_loop import LearningLoop
from noema.loops.calibration_loop import CalibrationLoop
from noema.loops.regime_loop import RegimeLoop

__all__ = [
    "SafetyLoop",
    "TradingLoopLoop",
    "LearningLoop",
    "CalibrationLoop",
    "RegimeLoop",
]
