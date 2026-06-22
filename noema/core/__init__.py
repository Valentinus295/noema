"""Core framework for the Noema multi-agent system."""
from noema.core.agent import Agent, AgentState
from noema.core.platform import detect_platform, get_broker_class, PlatformInfo, check_prerequisites
from noema.core.message_bus import MessageBus, Message
from noema.core.state_machine import TradingPipeline, PipelineState
from noema.core.settings import Settings, load_settings

# Backward-compatible alias
NoemaConfig = Settings

__all__ = [
    "Agent", "AgentState",
    "MessageBus", "Message",
    "TradingPipeline", "PipelineState",
    "Settings", "load_settings",
    "NoemaConfig",
]
