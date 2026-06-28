"""Multi-Broker Gateway — aggregate multiple brokers with smart routing.

Routes orders to the broker with best liquidity, provides failover on broker
health degradation, and reconciles cross-broker positions.

Works with ANY MT5 broker — FxPesa, FBS, IC Markets, Exness, etc.
Just register brokers by name and the gateway handles the rest.

Architecture:
    MultiBrokerGateway
    ├── MT5Broker (any MT5 broker)
    ├── ...additional brokers
    ├── OrderRouter (best bid/ask + liquidity routing)
    ├── HealthMonitor (per-broker heartbeat + failover)
    └── PositionAggregator (cross-broker position view)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from noema.broker.base import (
    AccountState,
    BrokerBase,
    BrokerProtocol,
    OrderRequest,
    OrderResult,
    Position,
    Tick,
)
from noema.core.types import Bar

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════

class BrokerHealth(str, Enum):
    """Broker health status for failover decisions."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"   # latencies high but functional
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class OrderRoutingPolicy(str, Enum):
    """How orders are routed across brokers."""
    BEST_PRICE = "best_price"           # Route to broker with best bid/ask
    BEST_LIQUIDITY = "best_liquidity"   # Route to broker with tightest spread
    ROUND_ROBIN = "round_robin"         # Distribute evenly
    PRIMARY_ONLY = "primary_only"       # Only use primary broker
    FAILOVER = "failover"               # Primary first, failover on error


@dataclass
class BrokerTick:
    """Enriched tick with broker metadata."""
    broker_name: str
    symbol: str
    bid: float
    ask: float
    spread: float = 0.0
    time: float = 0.0

    def __post_init__(self):
        if self.spread == 0.0 and self.ask > 0 and self.bid > 0:
            self.spread = self.ask - self.bid


@dataclass
class BrokerStatus:
    """Per-broker health snapshot."""
    name: str
    health: BrokerHealth = BrokerHealth.UNKNOWN
    connected: bool = False
    last_heartbeat: float = 0.0
    latency_ms: float = 0.0
    consecutive_failures: int = 0
    max_consecutive_failures: int = 3
    account_state: AccountState | None = None
    open_positions: int = 0

    @property
    def can_route(self) -> bool:
        return self.health in (BrokerHealth.HEALTHY, BrokerHealth.DEGRADED)


# ═══════════════════════════════════════════════════════════
# Multi-Broker Gateway
# ═══════════════════════════════════════════════════════════

class MultiBrokerGateway:
    """Aggregate gateway for ANY MT5 broker(s).

    Provides:
    - Best bid/ask across all healthy brokers
    - Automatic failover on broker health degradation
    - Cross-broker position reconciliation
    - Order routing by liquidity or price preference
    - Unified account view (sum of all brokers)

    Works with FxPesa, FBS, IC Markets, Exness, or any MT5 broker.
    """

    def __init__(
        self,
        brokers: dict[str, BrokerBase] | None = None,
        routing_policy: OrderRoutingPolicy = OrderRoutingPolicy.BEST_LIQUIDITY,
        primary_broker: str = "",
        health_check_interval: float = 5.0,
    ) -> None:
        self._brokers: dict[str, BrokerBase] = brokers or {}
        self._routing_policy = routing_policy
        # Auto-detect primary: first registered broker if not specified
        self._primary_broker = primary_broker
        self._health_check_interval = health_check_interval

        # Per-broker status tracking
        self._status: dict[str, BrokerStatus] = {}
        for name in self._brokers:
            self._status[name] = BrokerStatus(name=name)

        self._initialized = False
        self._health_task: asyncio.Task | None = None
        self._logger = logger.bind(gateway="multi_broker")

    # ── Lifecycle ─────────────────────────────────────────────

    def register_broker(self, name: str, broker: BrokerBase) -> None:
        """Register a broker with the gateway."""
        self._brokers[name] = broker
        if name not in self._status:
            self._status[name] = BrokerStatus(name=name)
        # Auto-set primary broker to first registered if not specified
        if not self._primary_broker:
            self._primary_broker = name
        self._logger.info("broker_registered", name=name, primary=self._primary_broker)

    def initialize(self) -> bool:
        """Initialize all registered brokers."""
        success_count = 0
        for name, broker in self._brokers.items():
            try:
                if broker.initialize():
                    self._status[name].connected = True
                    self._status[name].health = BrokerHealth.HEALTHY
                    self._status[name].last_heartbeat = time.monotonic()
                    success_count += 1
                    self._logger.info("broker_initialized", name=name)
                else:
                    self._status[name].health = BrokerHealth.DISCONNECTED
                    self._logger.error("broker_init_failed", name=name)
            except (ConnectionError, OSError) as e:
                self._status[name].health = BrokerHealth.DISCONNECTED
                self._logger.error("broker_init_error", name=name, error=str(e))

        self._initialized = success_count > 0
        if self._initialized:
            self._logger.info("gateway_initialized", brokers_ready=success_count)
        return self._initialized

    def shutdown(self) -> None:
        """Shutdown all broker connections."""
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None
        for name, broker in self._brokers.items():
            try:
                broker.shutdown()
                self._status[name].connected = False
                self._status[name].health = BrokerHealth.DISCONNECTED
            except Exception:  # Shutdown should never raise — swallow all errors
                pass
        self._initialized = False
        self._logger.info("gateway_shutdown")

    # ── Health Monitoring ─────────────────────────────────────

    async def start_health_monitor(self) -> None:
        """Start background health-check loop."""
        if self._health_task is not None:
            return
        self._health_task = asyncio.create_task(self._health_loop())
        self._logger.info("health_monitor_started", interval=self._health_check_interval)

    async def _health_loop(self) -> None:
        """Background loop: ping each broker, update health status."""
        while True:
            try:
                await self._check_all_brokers()
            except asyncio.CancelledError:
                break
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                self._logger.error("health_loop_error", error=str(e))
            await asyncio.sleep(self._health_check_interval)

    async def _check_all_brokers(self) -> None:
        """Check health of all registered brokers."""
        for name, broker in self._brokers.items():
            await self._check_broker_health(name, broker)

    async def _check_broker_health(self, name: str, broker: BrokerBase) -> None:
        """Check a single broker's health with ping + account query."""
        status = self._status[name]
        start = time.monotonic()
        try:
            _ = broker.get_account_info()
            latency = (time.monotonic() - start) * 1000
            status.connected = True
            status.latency_ms = latency
            status.last_heartbeat = time.monotonic()
            status.consecutive_failures = 0

            if latency < 200:
                status.health = BrokerHealth.HEALTHY
            elif latency < 1000:
                status.health = BrokerHealth.DEGRADED
            else:
                status.health = BrokerHealth.DEGRADED

        except Exception as e:
            status.consecutive_failures += 1
            status.latency_ms = 9999
            if status.consecutive_failures >= status.max_consecutive_failures:
                status.connected = False
                status.health = BrokerHealth.DISCONNECTED
                self._logger.error(
                    "broker_disconnected",
                    name=name,
                    failures=status.consecutive_failures,
                    error=str(e),
                )
            else:
                status.health = BrokerHealth.DEGRADED

    def get_healthy_brokers(self) -> list[str]:
        """Return names of brokers that can accept orders."""
        return [
            name for name, s in self._status.items()
            if s.can_route
        ]

    def is_any_healthy(self) -> bool:
        """Check if at least one broker is healthy."""
        return any(s.can_route for s in self._status.values())

    # ── Price Discovery (Best Bid/Ask) ────────────────────────

    def get_best_bid_ask(self, symbol: str) -> tuple[float, float, str, str]:
        """Get best bid/ask across all healthy brokers.

        Returns:
            (best_bid, best_ask, bid_broker, ask_broker)
        """
        best_bid = 0.0
        best_ask = float("inf")
        bid_broker = ""
        ask_broker = ""

        for name, broker in self._brokers.items():
            if not self._status[name].can_route:
                continue
            try:
                tick = broker.get_tick(symbol)
                bid = tick.get("bid", 0)
                ask = tick.get("ask", 0)
                if bid > best_bid:
                    best_bid = bid
                    bid_broker = name
                if 0 < ask < best_ask:
                    best_ask = ask
                    ask_broker = name
            except Exception as e:
                self._logger.warning("tick_fetch_failed", broker=name, symbol=symbol, error=str(e))

        return best_bid, best_ask, bid_broker, ask_broker

    def get_all_ticks(self, symbol: str) -> list[BrokerTick]:
        """Get ticks from all healthy brokers for a symbol."""
        ticks: list[BrokerTick] = []
        for name, broker in self._brokers.items():
            if not self._status[name].can_route:
                continue
            try:
                t = broker.get_tick(symbol)
                ticks.append(BrokerTick(
                    broker_name=name,
                    symbol=symbol,
                    bid=t.get("bid", 0),
                    ask=t.get("ask", 0),
                    time=t.get("time", time.time()),
                ))
            except Exception:
                pass
        return ticks

    def get_best_spread_broker(self, symbol: str) -> str | None:
        """Get broker name with tightest spread for a symbol."""
        ticks = self.get_all_ticks(symbol)
        if not ticks:
            return None
        best = min(ticks, key=lambda t: t.spread if t.spread > 0 else float("inf"))
        return best.broker_name

    # ── Order Routing ─────────────────────────────────────────

    def route_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float = 0,
        tp: float = 0,
        magic: int = 0,
        comment: str = "Noema-Gateway",
    ) -> OrderResult:
        """Route an order to the best broker based on routing policy.

        Failover: if primary broker fails, try next healthy broker.
        """
        broker_order = self._determine_broker_order(symbol)

        for broker_name in broker_order:
            broker = self._brokers.get(broker_name)
            if broker is None:
                continue
            if not self._status[broker_name].can_route:
                self._logger.warning("broker_unhealthy_skip", name=broker_name)
                continue

            try:
                result = broker.place_order(
                    symbol=symbol, direction=direction, volume=volume,
                    sl=sl, tp=tp, magic=magic, comment=comment,
                )
                if result.success:
                    self._logger.info(
                        "order_routed",
                        broker=broker_name,
                        symbol=symbol,
                        direction=direction,
                        volume=volume,
                        ticket=result.ticket,
                    )
                    return result
                else:
                    self._logger.warning(
                        "order_rejected",
                        broker=broker_name,
                        symbol=symbol,
                        error=result.error,
                    )
            except Exception as e:
                self._logger.error(
                    "order_routing_error",
                    broker=broker_name,
                    symbol=symbol,
                    error=str(e),
                )
                self._status[broker_name].consecutive_failures += 1

        return OrderResult(success=False, error="All brokers failed or unavailable")

    def _determine_broker_order(self, symbol: str) -> list[str]:
        """Determine which broker to try first based on routing policy."""
        healthy = self.get_healthy_brokers()
        if not healthy:
            return list(self._brokers.keys())  # try all anyway

        if self._routing_policy == OrderRoutingPolicy.PRIMARY_ONLY:
            return [self._primary_broker]

        if self._routing_policy == OrderRoutingPolicy.FAILOVER:
            primary_first = [self._primary_broker] if self._primary_broker in healthy else []
            others = [n for n in healthy if n != self._primary_broker]
            return primary_first + others

        if self._routing_policy == OrderRoutingPolicy.BEST_LIQUIDITY:
            best = self.get_best_spread_broker(symbol)
            if best:
                return [best] + [n for n in healthy if n != best]
            return healthy

        if self._routing_policy == OrderRoutingPolicy.BEST_PRICE:
            # For buy orders, lowest ask wins; for sell, highest bid
            _, best_ask, _, ask_broker = self.get_best_bid_ask(symbol)
            best_bid, _, bid_broker, _ = self.get_best_bid_ask(symbol)
            # By default, prefer tightest spread (lowest ask broker)
            preferred = ask_broker or bid_broker
            if preferred:
                return [preferred] + [n for n in healthy if n != preferred]
            return healthy

        # ROUND_ROBIN: just use all healthy brokers in order
        return healthy

    async def route_order_async(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float = 0,
        tp: float = 0,
        magic: int = 0,
        comment: str = "Noema-Gateway",
    ) -> OrderResult:
        """Async wrapper for order routing."""
        return await asyncio.to_thread(
            self.route_order, symbol, direction, volume, sl, tp, magic, comment
        )

    # ── Position Management ───────────────────────────────────

    def get_all_positions(self, magic: int = 0) -> dict[str, list[Position]]:
        """Get open positions from all brokers keyed by broker name."""
        positions: dict[str, list[Position]] = {}
        for name, broker in self._brokers.items():
            if self._status[name].can_route:
                try:
                    pos = broker.get_open_positions(magic=magic)
                    positions[name] = pos
                    self._status[name].open_positions = len(pos)
                except Exception as e:
                    self._logger.error("positions_fetch_failed", broker=name, error=str(e))
                    positions[name] = []
        return positions

    def get_aggregate_positions(self, magic: int = 0) -> list[Position]:
        """Get all open positions across all brokers (aggregated)."""
        all_positions: list[Position] = []
        for name, broker in self._brokers.items():
            if self._status[name].can_route:
                try:
                    all_positions.extend(broker.get_open_positions(magic=magic))
                except Exception:
                    pass
        return all_positions

    def get_aggregate_pnl(self) -> float:
        """Get total unrealized P&L across all brokers."""
        total = 0.0
        for positions in self.get_all_positions().values():
            total += sum(p.pnl for p in positions)
        return total

    def close_position(self, ticket: int, broker_name: str | None = None) -> bool:
        """Close a position on a specific broker or search all."""
        if broker_name:
            broker = self._brokers.get(broker_name)
            if broker:
                return broker.close_position(ticket)
            return False

        # Search all brokers
        for _name, broker in self._brokers.items():
            try:
                if broker.close_position(ticket):
                    return True
            except Exception:
                pass
        return False

    def close_all_positions(self, reason: str = "Gateway shutdown") -> dict[str, int]:
        """Close all positions across all brokers. Returns {broker: count_closed}."""
        closed: dict[str, int] = {}
        for name, broker in self._brokers.items():
            try:
                count = 0
                for pos in broker.get_open_positions():
                    if broker.close_position(pos.ticket):
                        count += 1
                closed[name] = count
                self._logger.info("positions_closed", broker=name, count=count, reason=reason)
            except Exception as e:
                closed[name] = 0
                self._logger.error("close_all_failed", broker=name, error=str(e))
        return closed

    # ── Unified Account View ──────────────────────────────────

    def get_aggregate_account(self) -> dict[str, Any]:
        """Get aggregated account info across all brokers."""
        total_balance = 0.0
        total_equity = 0.0
        total_margin = 0.0
        total_free_margin = 0.0
        per_broker: dict[str, dict] = {}

        for name, broker in self._brokers.items():
            try:
                info = broker.get_account_info()
                total_balance += info.get("balance", 0)
                total_equity += info.get("equity", 0)
                total_margin += info.get("margin", 0)
                total_free_margin += info.get("free_margin", 0)
                per_broker[name] = info
                self._status[name].account_state = AccountState(
                    balance=info.get("balance", 0),
                    equity=info.get("equity", 0),
                    margin=info.get("margin", 0),
                    free_margin=info.get("free_margin", 0),
                    leverage=info.get("leverage", 100),
                    currency=info.get("currency", "USD"),
                )
            except Exception:
                per_broker[name] = {}

        return {
            "aggregate": {
                "balance": total_balance,
                "equity": total_equity,
                "margin": total_margin,
                "free_margin": total_free_margin,
                "margin_level": (total_equity / total_margin * 100) if total_margin > 0 else 0,
            },
            "per_broker": per_broker,
        }

    # ── Status & Diagnostics ──────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get full gateway status for dashboard/health check."""
        return {
            "initialized": self._initialized,
            "routing_policy": self._routing_policy.value,
            "primary_broker": self._primary_broker,
            "brokers": {
                name: {
                    "health": s.health.value,
                    "connected": s.connected,
                    "latency_ms": round(s.latency_ms, 1),
                    "consecutive_failures": s.consecutive_failures,
                    "open_positions": s.open_positions,
                    "last_heartbeat": round(s.last_heartbeat, 1),
                }
                for name, s in self._status.items()
            },
        }

    def set_routing_policy(self, policy: OrderRoutingPolicy) -> None:
        """Change order routing policy at runtime."""
        self._routing_policy = policy
        self._logger.info("routing_policy_changed", policy=policy.value)

    def set_primary_broker(self, name: str) -> None:
        """Set the primary broker for routing."""
        self._primary_broker = name
        self._logger.info("primary_broker_changed", name=name)

    @property
    def primary_broker_name(self) -> str:
        return self._primary_broker

    @property
    def broker_names(self) -> list[str]:
        return list(self._brokers.keys())
