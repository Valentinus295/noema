"""Noema Agents Package.

Contains the 18-agent class-based system used by ModernOrchestrator.
The old 7-agent pipeline (orchestrator.py) has been removed.
"""
from noema.agents.macro import MacroEconomicAgent
from noema.agents.currency import CurrencyStrengthAgent
from noema.agents.structure import MarketStructureAgent
from noema.agents.institutional import InstitutionalFootprintAgent
from noema.agents.sr import SupportResistanceAgent
from noema.agents.session import SessionIntelligenceAgent
from noema.agents.opportunity import OpportunitySurveillanceAgent
from noema.agents.momentum import MomentumAgent
from noema.agents.price_action import PriceActionAgent
from noema.agents.thesis import TradeThesisAgent
from noema.agents.devil import DevilsAdvocateAgent
from noema.agents.cio import CIOAgent
from noema.agents.risk import RiskManagerAgent
from noema.agents.execution import ExecutionAgent
from noema.agents.management import TradeManagementAgent
from noema.agents.performance import PerformanceAnalystAgent
from noema.agents.learning import LearningAgent
from noema.agents.guardian import GuardianAgent

__all__ = [
    "MacroEconomicAgent", "CurrencyStrengthAgent", "MarketStructureAgent",
    "InstitutionalFootprintAgent", "SupportResistanceAgent", "SessionIntelligenceAgent",
    "OpportunitySurveillanceAgent", "MomentumAgent", "PriceActionAgent",
    "TradeThesisAgent", "DevilsAdvocateAgent", "CIOAgent",
    "RiskManagerAgent", "ExecutionAgent", "TradeManagementAgent",
    "PerformanceAnalystAgent", "LearningAgent", "GuardianAgent",
]
