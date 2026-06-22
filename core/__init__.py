"""Core framework for the VMPM multi-agent system."""
from vmpm.core.agent import Agent, AgentState
from vmpm.core.message_bus import MessageBus, Message
from vmpm.core.state_machine import TradingPipeline, PipelineState
from vmpm.core.settings import Settings, load_settings

# Backward compatibility
from vmpm.core.config import VMPMConfig, load_config

__all__ = [
    "Agent", "AgentState",
    "MessageBus", "Message",
    "TradingPipeline", "PipelineState",
    "Settings", "load_settings",
    "VMPMConfig", "load_config",
]
