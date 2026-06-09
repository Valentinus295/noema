"""VMPM Agent Swarm — 17 intelligent agents in a hedge fund hierarchy.

Each agent owns a business function and uses many tools internally.
They are departments in a hedge fund, not simple indicators.
"""
from vmpm.agents.macro import MacroEconomicAgent
from vmpm.agents.currency import CurrencyStrengthAgent
from vmpm.agents.structure import MarketStructureAgent
from vmpm.agents.institutional import InstitutionalFootprintAgent
from vmpm.agents.sr import SupportResistanceAgent
from vmpm.agents.session import SessionIntelligenceAgent
from vmpm.agents.opportunity import OpportunitySurveillanceAgent
from vmpm.agents.momentum import MomentumAgent
from vmpm.agents.price_action import PriceActionAgent
from vmpm.agents.thesis import TradeThesisAgent
from vmpm.agents.devil import DevilsAdvocateAgent
from vmpm.agents.cio import CIOAgent
from vmpm.agents.risk import RiskManagerAgent
from vmpm.agents.execution import ExecutionAgent
from vmpm.agents.management import TradeManagementAgent
from vmpm.agents.performance import PerformanceAnalystAgent
from vmpm.agents.learning import LearningAgent

__all__ = [
    "MacroEconomicAgent", "CurrencyStrengthAgent", "MarketStructureAgent",
    "InstitutionalFootprintAgent", "SupportResistanceAgent", "SessionIntelligenceAgent",
    "OpportunitySurveillanceAgent", "MomentumAgent", "PriceActionAgent",
    "TradeThesisAgent", "DevilsAdvocateAgent", "CIOAgent",
    "RiskManagerAgent", "ExecutionAgent", "TradeManagementAgent",
    "PerformanceAnalystAgent", "LearningAgent",
]
