"""Async message bus for inter-agent communication in Noema.

Agents publish and subscribe to topics. The bus routes messages
to all registered handlers for a given topic.

Enhanced with:
- TypedMessage support (typed, validated payloads)
- Priority queue (CRITICAL messages processed first)
- Dead letter queue (failed messages retained for inspection)
- Backpressure (maxsize=1000, drops LOW/BACKGROUND when full)
- TTL enforcement (expired messages dropped before delivery)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

import structlog

from noema.core.typed_messages import (
    MessagePriority,
    MessageType,
    TypedMessage,
)

logger = structlog.get_logger(__name__)

# Maximum items in the dead letter queue before oldest entries are evicted.
_DLQ_MAXLEN = 1000


@dataclass
class Message:
    """A message published on the bus.

    This is the *legacy* untyped message kept for backward compatibility.
    New code should prefer ``publish_typed`` with a ``TypedMessage``.
    """
    topic: str
    data: dict[str, Any]
    sender: str = ""
    timestamp: float = field(default_factory=lambda: __import__("time").time())


# Handler signature: async def handler(message: Message | TypedMessage) -> None
Handler = Callable[[Any], Coroutine[Any, Any, None]]


class MessageBus:
    """Lightweight async pub/sub message bus for agent coordination.

    Features:
    - Priority ordering via ``asyncio.PriorityQueue`` (CRITICAL > HIGH > MEDIUM > LOW > BACKGROUND)
    - Dead letter queue (deque, max 1000) for messages whose handlers all failed
    - Backpressure: queue maxsize=1000; LOW/BACKGROUND messages are dropped when full
    - TTL enforcement: expired messages are silently dropped before delivery
    - Full backward compatibility with the legacy untyped ``publish()`` API
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._queue: asyncio.PriorityQueue[tuple[int, float, Any]] = (
            asyncio.PriorityQueue(maxsize=maxsize)
        )
        self._maxsize = maxsize
        self._running = False
        self._router_task: asyncio.Task | None = None
        self._dead_letter_queue: deque[dict[str, Any]] = deque(maxlen=_DLQ_MAXLEN)
        self._drop_count: int = 0
        self._logger = logger.bind(component="message_bus")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._router_task = asyncio.create_task(self._route_messages())
        self._logger.info("message_bus_started", maxsize=self._maxsize)

    async def stop(self) -> None:
        self._running = False
        if self._router_task:
            self._router_task.cancel()
            try:
                await self._router_task
            except asyncio.CancelledError:
                pass
        self._logger.info(
            "message_bus_stopped",
            dlq_size=len(self._dead_letter_queue),
            total_drops=self._drop_count,
        )

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
        """Publish an untyped message to a topic (backward-compatible).

        Wraps the data in a legacy ``Message`` and enqueues with MEDIUM priority.
        """
        msg = Message(topic=topic, data=data, sender=sender)
        await self._enqueue(msg, priority=MessagePriority.MEDIUM)
        self._logger.debug("message_published", topic=topic, sender=sender)

    async def publish_typed(self, typed_msg: TypedMessage) -> None:
        """Publish a ``TypedMessage`` with its declared priority.

        The message is checked for TTL expiry before enqueueing.
        If the queue is full and the priority is LOW or BACKGROUND,
        the message is dropped and sent to the dead letter queue.
        """
        if typed_msg.is_expired:
            self._logger.debug(
                "typed_message_expired",
                message_type=typed_msg.message_type.value,
                age=typed_msg.age_seconds,
            )
            return

        await self._enqueue(typed_msg, priority=typed_msg.priority)
        self._logger.debug(
            "typed_message_published",
            message_type=typed_msg.message_type.value,
            priority=typed_msg.priority.value,
            sender=typed_msg.sender,
        )

    async def register(self, agent: Any) -> None:
        """Auto-register an agent's on_message method if it exists."""
        if hasattr(agent, "on_message"):
            self.subscribe(agent.name, agent.on_message)

    # ------------------------------------------------------------------
    # Internal enqueue with backpressure
    # ------------------------------------------------------------------

    async def _enqueue(self, msg: Any, priority: MessagePriority) -> None:
        """Put a message on the priority queue.

        Uses a monotonically increasing counter as a tiebreaker so that
        messages with equal priority are delivered in FIFO order.

        Backpressure: if the queue is full and the message priority is
        LOW or BACKGROUND, the message is dropped to the dead letter queue.
        """
        # Check if queue is full for low-priority messages
        if self._queue.full() and priority.ordinal <= MessagePriority.LOW.ordinal:
            self._drop_count += 1
            self._dead_letter_queue.append({
                "reason": "backpressure_drop",
                "priority": priority.value,
                "message": self._serialize_for_dlq(msg),
            })
            self._logger.warning(
                "message_dropped_backpressure",
                priority=priority.value,
                drop_count=self._drop_count,
            )
            return

        # Use negative ordinal so higher priority sorts first in the min-heap
        counter = id(msg)  # unique per enqueue for FIFO tiebreaking
        try:
            self._queue.put_nowait((-priority.ordinal, counter, msg))
        except asyncio.QueueFull:
            # Queue became full between our check and put_nowait (race).
            # Drop to DLQ regardless of priority — this is a safety valve.
            self._drop_count += 1
            self._dead_letter_queue.append({
                "reason": "queue_full",
                "priority": priority.value,
                "message": self._serialize_for_dlq(msg),
            })
            self._logger.warning(
                "message_dropped_queue_full",
                priority=priority.value,
            )

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------

    async def _route_messages(self) -> None:
        """Internal loop that dispatches queued messages to handlers."""
        while self._running:
            try:
                _prio, _counter, msg = await asyncio.wait_for(
                    self._queue.get(), timeout=0.1
                )
            except asyncio.TimeoutError:
                continue

            # ── TTL enforcement for TypedMessages ──
            if isinstance(msg, TypedMessage) and msg.is_expired:
                self._logger.debug(
                    "typed_message_expired_in_queue",
                    message_type=msg.message_type.value,
                    age=msg.age_seconds,
                )
                continue

            # Resolve topic
            if isinstance(msg, TypedMessage):
                topic = msg.message_type.value
            else:
                topic = msg.topic

            handlers = self._subscribers.get(topic, [])
            # Also deliver to wildcard subscribers
            handlers += self._subscribers.get("*", [])

            if not handlers:
                # No handler — route to DLQ so the message isn't silently lost
                self._dead_letter_queue.append({
                    "reason": "no_handler",
                    "topic": topic,
                    "message": self._serialize_for_dlq(msg),
                })
                continue

            all_failed = True
            for handler in handlers:
                try:
                    await handler(msg)
                    all_failed = False
                except Exception as exc:
                    self._logger.error(
                        "handler_error",
                        topic=topic,
                        handler=handler.__qualname__,
                        error=str(exc),
                    )

            if all_failed and handlers:
                # All handlers failed — record in dead letter queue
                self._dead_letter_queue.append({
                    "reason": "all_handlers_failed",
                    "topic": topic,
                    "message": self._serialize_for_dlq(msg),
                })

    # ------------------------------------------------------------------
    # Dead Letter Queue
    # ------------------------------------------------------------------

    @property
    def dead_letter_queue(self) -> list[dict[str, Any]]:
        """Return a snapshot of the dead letter queue (newest first)."""
        return list(reversed(self._dead_letter_queue))

    @property
    def dlq_size(self) -> int:
        """Current number of entries in the dead letter queue."""
        return len(self._dead_letter_queue)

    def clear_dlq(self) -> int:
        """Clear the dead letter queue and return the number of entries removed."""
        count = len(self._dead_letter_queue)
        self._dead_letter_queue.clear()
        return count

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, int]:
        """Return subscription counts per topic."""
        base = {t: len(h) for t, h in self._subscribers.items()}
        base["__queue_size"] = self._queue.qsize()
        base["__dlq_size"] = len(self._dead_letter_queue)
        base["__drop_count"] = self._drop_count
        return base

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_for_dlq(msg: Any) -> dict[str, Any]:
        """Serialize a message for dead letter queue storage."""
        if isinstance(msg, TypedMessage):
            return {
                "type": "TypedMessage",
                "message_type": msg.message_type.value,
                "priority": msg.priority.value,
                "sender": msg.sender,
                "symbol": msg.symbol,
                "message_id": msg.message_id,
                "age_seconds": round(msg.age_seconds, 2),
            }
        elif isinstance(msg, Message):
            return {
                "type": "Message",
                "topic": msg.topic,
                "sender": msg.sender,
                "data_keys": list(msg.data.keys()) if isinstance(msg.data, dict) else [],
            }
        return {"type": str(type(msg).__name__)}
