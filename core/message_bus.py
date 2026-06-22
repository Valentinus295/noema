"""Async message bus for inter-agent communication in Noema.

Agents publish and subscribe to topics. The bus routes messages
to all registered handlers for a given topic.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Message:
    """A message published on the bus."""
    topic: str
    data: dict[str, Any]
    sender: str = ""
    timestamp: float = field(default_factory=lambda: __import__("time").time())


# Handler signature: async def handler(message: Message) -> None
Handler = Callable[[Message], Coroutine[Any, Any, None]]


class MessageBus:
    """Lightweight async pub/sub message bus for agent coordination."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[Message] = asyncio.Queue()
        self._running = False
        self._router_task: asyncio.Task | None = None
        self._logger = logger.bind(component="message_bus")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._router_task = asyncio.create_task(self._route_messages())
        self._logger.info("message_bus_started")

    async def stop(self) -> None:
        self._running = False
        if self._router_task:
            self._router_task.cancel()
            try:
                await self._router_task
            except asyncio.CancelledError:
                pass
        self._logger.info("message_bus_stopped")

    # ------------------------------------------------------------------
    # Pub / Sub
    # ------------------------------------------------------------------

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Register a handler for a topic."""
        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        """Remove a handler from a topic."""
        if handler in self._subscribers[topic]:
            self._subscribers[topic].remove(handler)

    async def publish(self, topic: str, data: dict[str, Any], sender: str = "") -> None:
        """Publish a message to a topic."""
        msg = Message(topic=topic, data=data, sender=sender)
        await self._queue.put(msg)
        self._logger.debug("message_published", topic=topic, sender=sender)

    async def register(self, agent: Any) -> None:
        """Auto-register an agent's on_message method if it exists."""
        if hasattr(agent, "on_message"):
            self.subscribe(agent.name, agent.on_message)

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------

    async def _route_messages(self) -> None:
        """Internal loop that dispatches queued messages to handlers."""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            handlers = self._subscribers.get(msg.topic, [])
            # Also deliver to wildcard subscribers
            handlers += self._subscribers.get("*", [])

            for handler in handlers:
                try:
                    await handler(msg)
                except Exception as exc:
                    self._logger.error(
                        "handler_error",
                        topic=msg.topic,
                        handler=handler.__qualname__,
                        error=str(exc),
                    )

    @property
    def stats(self) -> dict[str, int]:
        """Return subscription counts per topic."""
        return {t: len(h) for t, h in self._subscribers.items()}
