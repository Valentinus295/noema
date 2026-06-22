"""Noema Agents Package.

Contains two agent systems:
- 7-agent pure-function system (per docs/ARCHITECTURE.md) — used by agents/orchestrator.py
- 17-agent class-based system (legacy) — used by main.py

The 7-agent system is the canonical architecture per the pinned ARCHITECTURE.md.
Legacy class-based agents are retained for backward compatibility.
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

__all__ = [
    "MacroEconomicAgent", "CurrencyStrengthAgent", "MarketStructureAgent",
    "InstitutionalFootprintAgent", "SupportResistanceAgent", "SessionIntelligenceAgent",
    "OpportunitySurveillanceAgent", "MomentumAgent", "PriceActionAgent",
    "TradeThesisAgent", "DevilsAdvocateAgent", "CIOAgent",
    "RiskManagerAgent", "ExecutionAgent", "TradeManagementAgent",
    "PerformanceAnalystAgent", "LearningAgent",
]
