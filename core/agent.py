"""Base agent class for the VMPM multi-agent system.

Every agent in the VMPM swarm inherits from this base class.
Agents communicate via the MessageBus and maintain their own state.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)


class AgentState(Enum):
    """Lifecycle states for an agent."""
    IDLE = "idle"
    PROCESSING = "processing"
    WAITING = "waiting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentReport:
    """Standardized output from an agent after analysis."""
    agent_name: str
    timestamp: float = field(default_factory=time.time)
    signal: str = "NEUTRAL"          # BULLISH, BEARISH, NEUTRAL
    confidence: float = 0.0          # 0.0 - 1.0
    data: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class Agent:
    """Base class for all VMPM agents.

    Subclasses must implement:
        - name: Unique agent identifier
        - role: Human-readable role description
        - analyze(): Core analysis logic
    """

    name: str = "base-agent"
    role: str = "Base Agent"
    priority: int = 0  # Higher = runs first among peers

    def __init__(self, message_bus: Any = None, config: Any = None) -> None:
        self.state = AgentState.IDLE
        self.message_bus = message_bus
        self.config = config
        self._task: Optional[asyncio.Task] = None
        self._report_history: list[AgentReport] = []
        self._subscriptions: list[str] = []
        self._logger = logger.bind(agent=self.name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the agent's background loop if it has one."""
        self._logger.info("agent_started", role=self.role)
        self.state = AgentState.IDLE
        if self.message_bus:
            await self.message_bus.register(self)

    async def stop(self) -> None:
        """Gracefully stop the agent."""
        self.state = AgentState.STOPPED
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._logger.info("agent_stopped")

    # ------------------------------------------------------------------
    # Analysis interface
    # ------------------------------------------------------------------

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Run analysis and return a report. Must be overridden."""
        raise NotImplementedError(f"{self.name} must implement analyze()")

    async def process(self, context: dict[str, Any]) -> AgentReport:
        """Wrapper around analyze() that handles state and error handling."""
        self.state = AgentState.PROCESSING
        start = time.monotonic()
        try:
            report = await self.analyze(context)
            elapsed = time.monotonic() - start
            self._report_history.append(report)
            self._logger.info(
                "analysis_complete",
                signal=report.signal,
                confidence=report.confidence,
                elapsed_ms=round(elapsed * 1000, 1),
            )
            self.state = AgentState.IDLE
            return report
        except Exception as exc:
            self.state = AgentState.ERROR
            self._logger.error("analysis_failed", error=str(exc))
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning=f"Error: {exc}",
            )

    # ------------------------------------------------------------------
    # Messaging helpers
    # ------------------------------------------------------------------

    async def publish(self, topic: str, data: dict[str, Any]) -> None:
        """Publish a message to the message bus."""
        if self.message_bus:
            await self.message_bus.publish(topic, data, sender=self.name)

    def subscribe(self, topic: str, handler: Callable) -> None:
        """Subscribe to a topic on the message bus."""
        if self.message_bus:
            self.message_bus.subscribe(topic, handler)
            self._subscriptions.append(topic)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def last_report(self) -> Optional[AgentReport]:
        return self._report_history[-1] if self._report_history else None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} state={self.state.value}>"
