"""Order Router Agent — Execution Team member for Noema Nexus.

Phase 2: The OrderRouter routes trade orders to the correct broker
based on the trading symbol. It supports multiple broker backends
simultaneously and selects the appropriate one for each order.

The OrderRouter:
1. Receives approved trade orders from the Critic Manager
2. Routes each order to the correct broker based on symbol
3. Handles broker-specific order parameters
4. Monitors broker health and failover

Broker routing rules:
- Default: Uses the primary broker configured in settings
- Symbol-based: Can route specific symbols to specific brokers
- Failover: Falls back to paper broker if live broker is unavailable
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)


class OrderRouter(DeterministicAgent):
    """Agent — Execution Team — Routes orders to correct broker.

    Supports multi-broker setups where different symbols or order types
    go to different brokers. Provides broker health-aware routing
    with automatic failover to paper trading.
    """

    name = "order-router"
    role = "Order Router (Execution Team)"
    priority = 0  # Runs last in execution team

    # Standard broker types
    BROKER_MT5 = "mt5"
    BROKER_FBS = "fbs"
    BROKER_PAPER = "paper"
    BROKER_FXPESA = "fxpesa"

    FALLBACK_BROKER = BROKER_PAPER

    def __init__(self, config=None, nim_client=None):
        super().__init__(config=config, nim_client=nim_client)
        self._brokers: dict[str, Any] = {}  # broker_name → broker instance
        self._routing_rules: dict[str, str] = {}  # symbol → broker_name
        self._broker_health: dict[str, bool] = {}  # broker_name → is_healthy
        self._routed_count: int = 0
        self._routed_by_broker: dict[str, int] = {}
        self._failover_count: int = 0

    def register_broker(self, name: str, broker: Any) -> None:
        """Register a broker backend.

        Args:
            name: Broker identifier (e.g., "mt5", "fbs", "paper").
            broker: Broker instance with `place_order()`, `get_tick()`, etc.
        """
        self._brokers[name] = broker
        self._broker_health[name] = True
        self._routed_by_broker[name] = 0
        logger.info("order_router_broker_registered", broker=name)

    def set_routing_rules(self, rules: dict[str, str]) -> None:
        """Set symbol-to-broker routing rules.

        Args:
            rules: Dict mapping symbol → broker_name.
                  e.g., {"XAUUSD": "fbs", "EURUSD": "mt5"}.
        """
        self._routing_rules = rules

    def add_routing_rule(self, symbol: str, broker_name: str) -> None:
        """Add a routing rule for a specific symbol."""
        self._routing_rules[symbol.upper()] = broker_name

    def get_broker_for_symbol(self, symbol: str) -> str:
        """Determine which broker to use for a symbol.

        Returns the broker name. Falls back to the first available
        broker if no specific rule exists.
        """
        # Check explicit routing rules
        broker_name = self._routing_rules.get(symbol.upper())
        if broker_name and self._broker_health.get(broker_name, False):
            return broker_name

        # Fall back to first healthy broker
        for name, healthy in self._broker_health.items():
            if healthy and name != self.FALLBACK_BROKER:
                return name

        # Last resort: paper broker
        return self.FALLBACK_BROKER

    def update_broker_health(self, name: str, is_healthy: bool) -> None:
        """Update health status for a broker.

        Args:
            name: Broker name.
            is_healthy: True if broker is connected and responsive.
        """
        was_healthy = self._broker_health.get(name, False)
        self._broker_health[name] = is_healthy

        if was_healthy and not is_healthy:
            logger.warning("order_router_broker_unhealthy", broker=name)
        elif not was_healthy and is_healthy:
            logger.info("order_router_broker_recovered", broker=name)

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Route an order to the appropriate broker.

        Args:
            context: Order context containing:
                - symbol: Trading symbol
                - direction: "long" or "short"
                - lot_size: Position size
                - stop_loss: SL price
                - take_profit: TP price
                - decision: Optional CIODecision
                - broker: Optional explicit broker backend (overrides routing)
                - magic_number: Magic number for MT5 orders
                - comment: Order comment

        Returns:
            AgentReport with execution result.
        """
        symbol: str = context.get("symbol", context.get("pair", "EURUSD")).upper()
        direction: str = context.get("direction", "long")
        lot_size: float = context.get("lot_size", 0.01)
        stop_loss: float = context.get("stop_loss", 0.0)
        take_profit: float = context.get("take_profit", 0.0)
        magic_number: int = context.get("magic_number", 20260609)
        comment: str = context.get("comment", "Noema")

        # ── Determine broker ──
        # If context has a specific broker, use it
        explicit_broker = context.get("broker")
        if explicit_broker:
            broker = explicit_broker
            broker_name = getattr(broker, "name", "explicit")
        else:
            broker_name = self.get_broker_for_symbol(symbol)
            broker = self._brokers.get(broker_name)

        if broker is None:
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning=f"No broker available for {symbol} (routed to: {broker_name})",
            )

        # ── Validate broker health ──
        if not self._broker_health.get(broker_name, False) and broker_name != self.FALLBACK_BROKER:
            # Attempt failover to paper
            fallback_broker = self._brokers.get(self.FALLBACK_BROKER)
            if fallback_broker:
                logger.warning(
                    "order_router_failover",
                    symbol=symbol,
                    from_broker=broker_name,
                    to=self.FALLBACK_BROKER,
                )
                broker = fallback_broker
                broker_name = self.FALLBACK_BROKER
                self._failover_count += 1
            else:
                return AgentReport(
                    agent_name=self.name,
                    signal="ERROR",
                    confidence=0.0,
                    reasoning=f"Broker {broker_name} is unhealthy and no fallback available",
                )

        # ── Get current tick for the symbol ──
        tick = None
        try:
            if hasattr(broker, 'get_tick'):
                tick = broker.get_tick(symbol)
        except Exception as e:
            logger.warning("order_router_tick_failed", symbol=symbol, broker=broker_name, error=str(e))

        if tick is None:
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning=f"No tick data for {symbol} on {broker_name}",
            )

        # ── Place the order ──
        order_type = "buy" if direction.lower() == "long" else "sell"

        try:
            result = broker.place_order(
                symbol=symbol,
                order_type=order_type,
                volume=lot_size,
                sl=stop_loss,
                tp=take_profit,
                comment=comment,
                magic=magic_number,
            )
        except Exception as e:
            logger.error(
                "order_router_placement_failed",
                symbol=symbol,
                broker=broker_name,
                error=str(e),
            )
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning=f"Order placement failed on {broker_name}: {e}",
            )

        # ── Record metrics ──
        self._routed_count += 1
        self._routed_by_broker[broker_name] = self._routed_by_broker.get(broker_name, 0) + 1

        # ── Build response ──
        if result and getattr(result, 'success', False):
            return AgentReport(
                agent_name=self.name,
                signal="ROUTED",
                confidence=1.0,
                data={
                    "ticket": getattr(result, 'ticket', None),
                    "price": getattr(result, 'price', 0.0),
                    "volume": getattr(result, 'volume', lot_size),
                    "sl": stop_loss,
                    "tp": take_profit,
                    "symbol": symbol,
                    "direction": direction,
                    "broker": broker_name,
                    "route": f"{symbol} → {broker_name}",
                },
                reasoning=(
                    f"Order routed to {broker_name}: {direction.upper()} "
                    f"{lot_size} lots of {symbol} @ {getattr(result, 'price', 'market')}"
                ),
            )
        else:
            error_msg = getattr(result, 'error', 'Unknown error') if result else "No result from broker"
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning=f"Order rejected by {broker_name}: {error_msg}",
            )

    # ── Utility Methods ────────────────────────────────────────────

    def get_available_brokers(self) -> list[str]:
        """Get list of registered broker names."""
        return list(self._brokers.keys())

    def get_healthy_brokers(self) -> list[str]:
        """Get list of healthy broker names."""
        return [name for name, healthy in self._broker_health.items() if healthy]

    def get_routing_rules(self) -> dict[str, str]:
        """Get current routing rules."""
        return dict(self._routing_rules)

    def get_stats(self) -> dict[str, Any]:
        """Get order router statistics."""
        return {
            "name": self.name,
            "brokers": list(self._brokers.keys()),
            "healthy_brokers": self.get_healthy_brokers(),
            "routing_rules": dict(self._routing_rules),
            "total_routed": self._routed_count,
            "routed_by_broker": dict(self._routed_by_broker),
            "failover_count": self._failover_count,
        }
