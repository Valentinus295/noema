"""Analysis modules for VMPM — the analytical brain of the system."""
from vmpm.analysis.fundamental import FundamentalAnalyzer
from vmpm.analysis.technical import TechnicalAnalyzer
from vmpm.analysis.smc import SMCForecaster
from vmpm.analysis.candlestick import CandlestickDetector
from vmpm.analysis.econometrics import EconometricsEngine

__all__ = [
    "FundamentalAnalyzer",
    "TechnicalAnalyzer",
    "SMCForecaster",
    "CandlestickDetector",
    "EconometricsEngine",
]
