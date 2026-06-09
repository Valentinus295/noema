"""Core framework for the VMPM multi-agent system."""
from vmpm.core.agent import Agent, AgentState
from vmpm.core.message_bus import MessageBus, Message
from vmpm.core.state_machine import TradingPipeline, PipelineState
from vmpm.core.config import load_config, VMPMConfig

__all__ = [
    "Agent", "AgentState",
    "MessageBus", "Message",
    "TradingPipeline", "PipelineState",
    "load_config", "VMPMConfig",
]
