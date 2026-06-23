"""MetaTrader 5 broker for Linux (Wine + mt5linux).

Uses the mt5linux package which runs a Python server inside the Wine
environment and exposes MT5 functions via RPyC (Remote Python Call).

This is the PRIMARY broker for Pop!_OS / Ubuntu / any Linux running MT5 via Wine.

Architecture:
    Noema (Python, Linux)
        │
        ▼
    mt5linux (RPyC client, port 18812)
        │
        ▼
    Wine ─► MT5 Terminal ─► Broker Server

Resilience features (v2.0):
    - MT5ConnectionManager: reconnect + reconciliation on disconnect
    - BrokerHealthMonitor: background async health pings (5s interval)
    - Stale-data protection: blocks orders if last tick > 5s old
    - RPyC latency instrumentation: Prometheus gauge + WARNING threshold
    - Telegram disconnect/reconnect alerts

Requirements:
    - Wine with MT5 installed
    - mt5linux package (pip install mt5linux)
    - MT5 terminal running under Wine (see scripts/start_mt5.py)
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import structlog

from noema.broker.base import BrokerBase, OrderResult, Position
from noema.broker.connection import MT5ConnectionManager

logger = structlog.get_logger(__name__)

# Default paths for Pop!_OS / Ubuntu
DEFAULT_WINE_MT5_PATH = Path.home() / ".wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
DEFAULT_RPYC_PORT = 18812
DEFAULT_RPYC_HOST = "127.0.0.1"
DEFAULT_STARTUP_WAIT = 120  # seconds

# Health monitoring
HEALTH_PING_INTERVAL = 5.0         # seconds
STALE_DATA_THRESHOLD = 5.0         # seconds — blocks orders if last tick older
RPYC_LATENCY_WARNING = 50.0        # ms — log WARNING if RPyC latency exceeds
DISCONNECT_ALERT_DELAY = 15.0      # seconds — send Telegram alert after this long

TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1", "MN1": "TIMEFRAME_MN1",
}


# ── Prometheus gauge for RPyC latency (lazy import to avoid hard dependency) ──

def _init_rpyc_latency_gauge():
    """Initialize the Prometheus gauge for RPyC latency."""
    try:
        from prometheus_client import Gauge
        return Gauge(
            "noema_broker_rpyc_latency_ms",
            "RPyC bridge round-trip latency in milliseconds",
        )
    except ImportError:
        return None


_rpyc_latency_gauge: Any = None


def _record_rpyc_latency(latency_ms: float) -> None:
    """Record RPyC latency to Prometheus gauge if available."""
    global _rpyc_latency_gauge
    if _rpyc_latency_gauge is None:
        _rpyc_latency_gauge = _init_rpyc_latency_gauge()
    if _rpyc_latency_gauge is not None:
        _rpyc_latency_gauge.set(latency_ms)


# ── BrokerHealthMonitor ─────────────────────────────────────────────


class BrokerHealthMonitor:
    """Background async health monitor for MT5 broker connectivity.

    Runs as an asyncio.Task in the orchestrator (NOT blocking the pipeline).

    Responsibilities:
    - Ping MT5 every HEALTH_PING_INTERVAL seconds (port check + RPyC call)
    - Track tick freshness via last_tick_timestamp
    - Trigger reconnect via MT5ConnectionManager on disconnect
    - Send Telegram alerts on prolonged disconnects (>15s)
    - Track consecutive failures and set critical/guardian flags
    - Expose RPyC latency as Prometheus gauge
    """

    def __init__(
        self,
        broker: "MT5LinuxBroker",
        connection_manager: MT5ConnectionManager,
        telegram_callback: Callable | None = None,
        guardian_data_stale_callback: Callable[[], None] | None = None,
        subscribed_pairs: list[str] | None = None,
    ) -> None:
        self._broker = broker
        self._conn_mgr = connection_manager
        self._telegram = telegram_callback
        self._guardian_cb = guardian_data_stale_callback
        self._subscribed_pairs = subscribed_pairs or []
        self._running = False
        self._task: asyncio.Task | None = None
        self._disconnect_alerted = False

    async def start(self) -> asyncio.Task:
        """Start the health monitor as a background task. Returns the task."""
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("broker_health_monitor_started", interval=HEALTH_PING_INTERVAL)
        return self._task

    async def stop(self) -> None:
        """Stop the health monitor gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("broker_health_monitor_stopped")

    async def _run(self) -> None:
        """Main loop: ping MT5, check ticks, handle disconnect."""
        while self._running:
            try:
                await self._health_check()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("health_monitor_error", error=str(exc))
            await asyncio.sleep(HEALTH_PING_INTERVAL)

    async def _health_check(self) -> None:
        """Single health-check cycle."""
        broker = self._broker

        # 1. Check RPyC port is open (lightweight TCP check)
        port_open = broker._port_is_open(broker._host, broker._port, timeout=1.0)

        # 2. Check tick freshness (did we get a tick recently?)
        tick_fresh = not self._conn_mgr.is_data_stale()

        # 3. If broker not connected or port closed, we're disconnected
        is_connected = broker.is_connected and port_open

        if not is_connected:
            # Record start of disconnect for 15-second alert threshold
            self._conn_mgr.mark_disconnect_start()

            # Check if disconnect has exceeded alert threshold
            disconnect_dur = self._conn_mgr.get_disconnect_duration()
            if disconnect_dur >= DISCONNECT_ALERT_DELAY and not self._disconnect_alerted:
                self._disconnect_alerted = True
                await self._send_alert(
                    f"⚠️ MT5 DISCONNECTED for {disconnect_dur:.0f}s!\n"
                    f"Port open: {port_open}\n"
                    f"Tick fresh: {tick_fresh}\n"
                    f"Attempting reconnect…"
                )

            # Record failure and check threshold
            self._conn_mgr.record_failure()

            if self._conn_mgr.is_critical:
                logger.critical(
                    "broker_health_critical",
                    consecutive_failures=self._conn_mgr.consecutive_failures,
                )
                # Trigger guardian data_stale flag
                if self._guardian_cb:
                    try:
                        self._guardian_cb()
                    except Exception:
                        pass

            # Attempt reconnect via connection manager
            await self._conn_mgr.on_disconnect(broker)

            # Try to reconnect with exponential backoff
            reconnected = await self._conn_mgr.wait_for_reconnect(
                lambda: broker._reconnect_attempt()
            )
            if reconnected:
                await self._conn_mgr.on_reconnect(broker)
                self._conn_mgr.mark_reconnect()
                self._disconnect_alerted = False
                await self._send_alert("✅ MT5 RECONNECTED")
            return

        # Connected — record success
        self._conn_mgr.record_success()

        # If we were previously disconnected and now reconnected, send alert
        if self._disconnect_alerted:
            self._disconnect_alerted = False
            await self._send_alert("✅ MT5 RECONNECTED")

        # 4. Measure RPyC latency
        latency_ms = broker.get_latency_ms()
        _record_rpyc_latency(latency_ms)
        if latency_ms > RPYC_LATENCY_WARNING:
            logger.warning(
                "rpyc_latency_high",
                latency_ms=round(latency_ms, 1),
                threshold_ms=RPYC_LATENCY_WARNING,
            )

        # 5. Poll ticks for subscribed pairs (updates last_tick_timestamp)
        for symbol in self._subscribed_pairs:
            try:
                tick = broker.get_tick(symbol)
                if tick:
                    self._conn_mgr.update_tick_timestamp()
            except Exception:
                pass  # Individual tick failures are non-fatal

        # 6. Check stale-data and trigger guardian if needed
        if tick_fresh is False and self._conn_mgr.is_data_stale():
            if self._guardian_cb:
                try:
                    self._guardian_cb()
                except Exception:
                    pass

    async def _send_alert(self, message: str) -> None:
        """Send Telegram alert if callback is configured."""
        if self._telegram:
            try:
                if asyncio.iscoroutinefunction(self._telegram):
                    await self._telegram(message)
                else:
                    self._telegram(message)
            except Exception:
                pass


# ── MT5LinuxBroker ──────────────────────────────────────────────────


class MT5LinuxBroker(BrokerBase):
    """MetaTrader 5 broker for Linux via Wine + RPyC.

    This broker wraps mt5linux to provide the same interface as the
    Windows-native MT5Broker, but works on Pop!_OS and Ubuntu.

    Resilience (v2.0):
        Connection manager handles disconnect/reconnect/reconciliation.
        Health monitor runs in background (async task, never blocks pipeline).
        Stale-data protection blocks orders on stale prices.

    Usage:
        broker = MT5LinuxBroker(config)
        broker.initialize()
        broker.place_order(symbol="EURUSD", ...)
    """

    def __init__(
        self,
        config: Any = None,
        telegram_callback: Callable | None = None,
    ) -> None:
        super().__init__(config)
        self._mt5 = None          # mt5linux client
        self._rpyc_process = None
        self._connected = False
        self._host = DEFAULT_RPYC_HOST
        self._port = DEFAULT_RPYC_PORT
        self._data_stale = False
        self._conn_mgr: MT5ConnectionManager | None = None
        self._health_monitor: BrokerHealthMonitor | None = None
        self._telegram_callback = telegram_callback

    # ── Connection ─────────────────────────────────────────────

    def wait_for_ready(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float = DEFAULT_STARTUP_WAIT,
        poll_interval: float = 2.0,
    ) -> bool:
        """Wait for the MT5 RPyC bridge to become available.

        Call this BEFORE initialize() to ensure MT5 is running.
        Useful when Noema is starting and MT5 may still be booting.

        Args:
            host: RPyC host (default: 127.0.0.1)
            port: RPyC port (default: 18812)
            timeout: Maximum wait time in seconds
            poll_interval: Time between polls in seconds

        Returns:
            True if MT5 bridge became ready, False if timeout expired
        """
        h = host or self._host
        p = port or self._port

        logger.info(
            "mt5_waiting_for_ready",
            host=h, port=p, timeout=timeout,
        )

        start = time.monotonic()
        while (time.monotonic() - start) < timeout:
            if self._port_is_open(h, p, timeout=1.0):
                elapsed = time.monotonic() - start
                logger.info(
                    "mt5_bridge_ready",
                    host=h, port=p,
                    elapsed_seconds=round(elapsed, 1),
                )
                return True
            time.sleep(poll_interval)

        logger.error(
            "mt5_bridge_timeout",
            host=h, port=p, timeout=timeout,
            hint="MT5 daemon not running. Start with: python -m noema.scripts.mt5_daemon start",
        )
        return False

    def initialize(self) -> bool:
        """Connect to MT5 via mt5linux RPyC bridge.

        The MT5 terminal must already be running under Wine.
        Use python -m noema.scripts.mt5_daemon start to launch it headless,
        or start it manually with wine.

        If wait_for_ready() was called first, MT5 should already be listening.
        If not, we check the port and give a helpful error.

        Wires the MT5ConnectionManager for disconnect/reconnect/reconciliation.
        """
        # Quick pre-check: is the RPyC port open?
        if not self._port_is_open(self._host, self._port, timeout=2.0):
            logger.error(
                "mt5_not_running",
                host=self._host,
                port=self._port,
                hint=(
                    "MT5 daemon not running. Start it with:\n"
                    "  python -m noema.scripts.mt5_daemon start\n"
                    "Or if MT5 is still booting, wait with:\n"
                    "  python -m noema.scripts.mt5_daemon wait"
                ),
            )
            return False

        try:
            from mt5linux import MetaTrader5
            self._mt5 = MetaTrader5(
                host=self._host,
                port=self._port,
            )
        except ImportError:
            logger.error(
                "mt5linux_not_installed",
                fix="pip install mt5linux",
            )
            return False
        except Exception as exc:
            logger.error("mt5linux_import_failed", error=str(exc))
            return False

        # Test the connection
        try:
            if not self._mt5.initialize():
                logger.error(
                    "mt5_init_failed",
                    host=self._host,
                    port=self._port,
                    hint=(
                        "MT5 is running but RPyC initialization failed.\n"
                        "Check: 1) mt5linux server active in MT5? 2) Credentials correct?\n"
                        "Try restarting MT5: python -m noema.scripts.mt5_daemon restart"
                    ),
                )
                return False
        except Exception as exc:
            logger.error(
                "mt5_connection_failed",
                error=str(exc),
                hint=(
                    "Check: 1) Wine installed? 2) MT5 running?\n"
                    "  3) mt5linux server active in MT5?\n"
                    "  Start MT5: python -m noema.scripts.mt5_daemon start"
                ),
            )
            return False

        # Get account info
        try:
            info = self._mt5.account_info()
            if info:
                logger.info(
                    "mt5_connected",
                    login=info.login,
                    server=info.server,
                    balance=float(info.balance),
                    equity=float(info.equity),
                    currency=info.currency,
                    leverage=info.leverage,
                )
        except Exception:
            logger.warning("mt5_account_info_failed")

        self._connected = True

        # ── Wire MT5ConnectionManager ─────────────────────────────
        self._conn_mgr = MT5ConnectionManager(
            telegram_callback=self._telegram_callback,
        )
        self._conn_mgr.state.connected = True
        self._conn_mgr.state.last_connected = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )
        self._conn_mgr.update_tick_timestamp()
        logger.info("mt5_connection_manager_wired")

        return True

    def shutdown(self) -> None:
        """Disconnect from MT5."""
        # Stop health monitor first
        if self._health_monitor:
            # Fire-and-forget stop; orchestrator handles cancellation.
            pass
        if self._mt5 and self._connected:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
        self._connected = False
        if self._conn_mgr:
            self._conn_mgr.state.connected = False

    async def async_shutdown(self) -> None:
        """Async shutdown: stop health monitor, then disconnect."""
        if self._health_monitor:
            await self._health_monitor.stop()
        self.shutdown()

    # ── Health monitor lifecycle ────────────────────────────────────

    def start_health_monitor(
        self,
        subscribed_pairs: list[str] | None = None,
        guardian_data_stale_callback: Callable[[], None] | None = None,
    ) -> BrokerHealthMonitor | None:
        """Start the background health monitor task.

        Called by the orchestrator AFTER initialize().
        Returns the monitor instance or None if already running.
        """
        if self._health_monitor is not None:
            logger.warning("health_monitor_already_running")
            return self._health_monitor
        if self._conn_mgr is None:
            logger.error("health_monitor_no_connection_manager")
            return None

        self._health_monitor = BrokerHealthMonitor(
            broker=self,
            connection_manager=self._conn_mgr,
            telegram_callback=self._telegram_callback,
            guardian_data_stale_callback=guardian_data_stale_callback,
            subscribed_pairs=subscribed_pairs,
        )
        # Fire-and-forget: task is stored on the monitor
        self._health_monitor._task_h = asyncio.ensure_future(
            self._health_monitor._run()
        )
        self._health_monitor._running = True
        logger.info(
            "broker_health_monitor_started",
            interval=HEALTH_PING_INTERVAL,
            pairs=subscribed_pairs,
        )
        return self._health_monitor

    async def stop_health_monitor(self) -> None:
        """Stop the health monitor gracefully."""
        if self._health_monitor:
            await self._health_monitor.stop()
            self._health_monitor = None

    @property
    def connection_manager(self) -> MT5ConnectionManager | None:
        return self._conn_mgr

    @property
    def data_stale(self) -> bool:
        """True if last tick is stale (>5s old or never received)."""
        if self._conn_mgr:
            return self._conn_mgr.is_data_stale()
        return self._data_stale

    @property
    def is_connected(self) -> bool:
        return self._connected

    def can_trade(self) -> bool:
        """Check if trading is allowed (connected + data not stale)."""
        if not self._connected:
            return False
        if self._conn_mgr and not self._conn_mgr.can_trade():
            return False
        if self.data_stale:
            return False
        return True

    def _reconnect_attempt(self) -> bool:
        """Attempt to re-establish the RPyC connection.

        Used as the check function for MT5ConnectionManager.wait_for_reconnect().
        Returns True if reconnect succeeds.
        """
        if self._mt5 is None:
            try:
                from mt5linux import MetaTrader5
                self._mt5 = MetaTrader5(host=self._host, port=self._port)
            except Exception:
                return False
        try:
            if self._mt5.initialize():
                self._connected = True
                if self._conn_mgr:
                    self._conn_mgr.state.connected = True
                    self._conn_mgr.update_tick_timestamp()
                return True
        except Exception as exc:
            logger.warning("reconnect_attempt_failed", error=str(exc))
        return False

    def get_latency_ms(self) -> float:
        """Measure RPyC bridge round-trip latency.

        Makes a lightweight RPyC call (symbol_info_tick on a known symbol)
        and times the round-trip. Logs WARNING if >50ms.

        Returns:
            Latency in milliseconds, or -1 if measurement fails.
        """
        if not self._connected or self._mt5 is None:
            return -1.0
        try:
            start = time.monotonic()
            _ = self._mt5.symbol_info_tick("EURUSD")
            elapsed = (time.monotonic() - start) * 1000
            if elapsed > RPYC_LATENCY_WARNING:
                logger.warning(
                    "rpyc_latency_high",
                    latency_ms=round(elapsed, 1),
                    threshold_ms=RPYC_LATENCY_WARNING,
                )
            return elapsed
        except Exception as exc:
            logger.warning("rpyc_latency_measure_failed", error=str(exc))
            return -1.0

    # ── Account ─────────────────────────────────────────────────

    def account_info(self) -> dict | None:
        if not self._connected:
            return None
        try:
            info = self._mt5.account_info()
            if info is None:
                return None
            return {
                "login": info.login,
                "balance": float(info.balance),
                "equity": float(info.equity),
                "margin": float(info.margin) if hasattr(info, "margin") else 0,
                "margin_free": float(info.margin_free) if hasattr(info, "margin_free") else 0,
                "margin_level": float(info.margin_level) if hasattr(info, "margin_level") else 0,
                "currency": info.currency,
                "leverage": info.leverage,
                "server": info.server,
            }
        except Exception as exc:
            logger.error("account_info_failed", error=str(exc))
            return None

    # ── Market Data ─────────────────────────────────────────────

    def get_candles(
        self, symbol: str, timeframe: str, count: int = 200
    ) -> list[dict] | None:
        """Fetch OHLCV candles via mt5linux."""
        if not self._connected:
            return None

        try:
            # mt5linux uses the same copy_rates_from_pos API
            rates = self._mt5.copy_rates_from_pos(symbol, self._tf_map(timeframe), 0, count)
            if rates is None or len(rates) == 0:
                return None

            import pandas as pd
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            return df.to_dict("records")
        except Exception as exc:
            logger.error(
                "candles_failed",
                symbol=symbol,
                timeframe=timeframe,
                error=str(exc),
            )
            return None

    def get_tick(self, symbol: str) -> dict | None:
        """Get current tick. Updates last_tick_timestamp for stale-data protection."""
        if not self._connected:
            return None
        try:
            tick = self._mt5.symbol_info_tick(symbol)
            if tick is None:
                return None
            # ── Update tick timestamp for stale-data protection ──
            if self._conn_mgr:
                self._conn_mgr.update_tick_timestamp()
            return {
                "bid": float(tick.bid),
                "ask": float(tick.ask),
                "last": float(tick.last) if hasattr(tick, "last") else 0,
                "time": tick.time,
                "volume": tick.volume if hasattr(tick, "volume") else 0,
            }
        except Exception as exc:
            logger.error("tick_failed", symbol=symbol, error=str(exc))
            return None

    def symbol_info(self, symbol: str) -> dict | None:
        """Get symbol information."""
        if not self._connected:
            return None
        try:
            info = self._mt5.symbol_info(symbol)
            if info is None:
                return None
            return {
                "digits": info.digits,
                "point": float(info.point),
                "spread": info.spread,
                "trade_tick_size": float(getattr(info, "trade_tick_size", info.point * 10)),
                "trade_tick_value": float(getattr(info, "trade_tick_value", 0)),
                "volume_min": float(getattr(info, "volume_min", 0.01)),
                "volume_max": float(getattr(info, "volume_max", 100)),
                "volume_step": float(getattr(info, "volume_step", 0.01)),
            }
        except Exception as exc:
            logger.error("symbol_info_failed", symbol=symbol, error=str(exc))
            return None

    def ensure_symbol(self, symbol: str) -> bool:
        """Add symbol to Market Watch if needed."""
        if not self._connected:
            return False
        try:
            info = self._mt5.symbol_info(symbol)
            if info is None:
                return False
            if not info.visible:
                return self._mt5.symbol_select(symbol, True)
            return True
        except Exception:
            return False

    # ── Trading ─────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        price: float = 0,
        sl: float = 0,
        tp: float = 0,
        comment: str = "Noema",
        magic: int = 0,
    ) -> OrderResult:
        """Place a trade via mt5linux.

        Args:
            symbol: Trading symbol (EURUSD, GBPUSD, etc.)
            order_type: 'buy', 'sell', 'buy_limit', 'sell_limit',
                       'buy_stop', 'sell_stop'
            volume: Lot size
            price: Entry price (for pending orders)
            sl: Stop loss price
            tp: Take profit price
            comment: Order comment
            magic: Magic number for identification
        """
        if not self._connected:
            return OrderResult(success=False, error="Not connected to MT5")

        # ── Stale-data protection: block order if last tick is > 5s old ──
        if self.data_stale:
            stale_msg = "Data is stale — last tick > 5s old. Order blocked."
            logger.warning(
                "order_blocked_stale_data",
                symbol=symbol,
                last_tick_age_secs=round(
                    time.monotonic() - (self._conn_mgr._last_tick_timestamp if self._conn_mgr else 0), 1
                ),
            )
            self._data_stale = True
            return OrderResult(success=False, error=stale_msg)

        # Ensure symbol is available
        if not self.ensure_symbol(symbol):
            return OrderResult(success=False, error=f"Symbol {symbol} not available")

        # Get symbol info for rounding
        sym_info = self.symbol_info(symbol)
        digits = sym_info.get("digits", 5) if sym_info else 5

        # Map order type
        type_map = {
            "buy": self._mt5.ORDER_TYPE_BUY,
            "sell": self._mt5.ORDER_TYPE_SELL,
            "buy_limit": self._mt5.ORDER_TYPE_BUY_LIMIT,
            "sell_limit": self._mt5.ORDER_TYPE_SELL_LIMIT,
            "buy_stop": self._mt5.ORDER_TYPE_BUY_STOP,
            "sell_stop": self._mt5.ORDER_TYPE_SELL_STOP,
        }

        mt_type = type_map.get(order_type.lower())
        if mt_type is None:
            return OrderResult(success=False, error=f"Unknown order type: {order_type}")

        # Get current price for market orders
        if price <= 0:
            tick = self.get_tick(symbol)
            if tick is None:
                return OrderResult(success=False, error="Cannot get current price")
            price = tick["ask"] if order_type.lower() in ("buy",) else tick["bid"]

        # Build request
        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt_type,
            "price": round(float(price), digits),
            "sl": round(float(sl), digits) if sl else 0,
            "tp": round(float(tp), digits) if tp else 0,
            "deviation": 20,
            "magic": int(magic),
            "comment": comment[:31],
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }

        # For pending orders
        if order_type.lower() in ("buy_limit", "sell_limit", "buy_stop", "sell_stop"):
            request["action"] = self._mt5.TRADE_ACTION_PENDING

        try:
            result = self._mt5.order_send(request)
            if result is None:
                return OrderResult(success=False, error="order_send returned None")

            ok = result.retcode == self._mt5.TRADE_RETCODE_DONE
            logger.info(
                "order_result",
                symbol=symbol,
                type=order_type,
                volume=volume,
                success=ok,
                retcode=result.retcode,
                comment=str(result.comment),
            )
            return OrderResult(
                success=ok,
                order_id=result.order if ok else 0,
                error="" if ok else f"retcode={result.retcode}: {result.comment}",
                price=price,
                volume=volume,
            )
        except Exception as exc:
            logger.error("order_send_failed", symbol=symbol, error=str(exc))
            return OrderResult(success=False, error=str(exc))

    def close_position(self, ticket: int, volume: float = 0) -> OrderResult:
        """Close an open position."""
        if not self._connected:
            return OrderResult(success=False, error="Not connected")

        try:
            positions = self._mt5.positions_get(ticket=int(ticket))
            if not positions:
                return OrderResult(success=False, error=f"Position {ticket} not found")

            pos = positions[0]
            tick = self._mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                return OrderResult(success=False, error="Cannot get price")

            order_type = (
                self._mt5.ORDER_TYPE_SELL if pos.type == self._mt5.POSITION_TYPE_BUY
                else self._mt5.ORDER_TYPE_BUY
            )
            price = tick.bid if pos.type == self._mt5.POSITION_TYPE_BUY else tick.ask
            close_volume = float(volume) if volume > 0 else float(pos.volume)

            request = {
                "action": self._mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": close_volume,
                "type": order_type,
                "position": int(ticket),
                "price": price,
                "deviation": 20,
                "magic": pos.magic,
                "comment": "Noema close",
                "type_time": self._mt5.ORDER_TIME_GTC,
                "type_filling": self._mt5.ORDER_FILLING_IOC,
            }

            result = self._mt5.order_send(request)
            if result is None:
                return OrderResult(success=False, error="order_send returned None")

            ok = result.retcode == self._mt5.TRADE_RETCODE_DONE
            return OrderResult(
                success=ok,
                order_id=result.order if ok else 0,
                error="" if ok else f"retcode={result.retcode}",
            )
        except Exception as exc:
            return OrderResult(success=False, error=str(exc))

    def get_positions(self) -> list[Position]:
        """Get all open positions."""
        if not self._connected:
            return []

        try:
            raw = self._mt5.positions_get()
            if raw is None:
                return []

            positions = []
            for p in raw:
                positions.append(Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    type="buy" if p.type == self._mt5.POSITION_TYPE_BUY else "sell",
                    volume=float(p.volume),
                    open_price=float(p.price_open),
                    current_price=float(p.price_current),
                    sl=float(p.sl),
                    tp=float(p.tp),
                    profit=float(p.profit),
                    swap=float(p.swap) if hasattr(p, "swap") else 0.0,
                    comment=p.comment,
                    magic=p.magic,
                    open_time=p.time,
                ))
            return positions
        except Exception as exc:
            logger.error("get_positions_failed", error=str(exc))
            return []

    def modify_position(
        self, ticket: int, sl: float = 0, tp: float = 0
    ) -> OrderResult:
        """Modify SL/TP of an open position."""
        if not self._connected:
            return OrderResult(success=False, error="Not connected")

        try:
            positions = self._mt5.positions_get(ticket=int(ticket))
            if not positions:
                return OrderResult(success=False, error=f"Position {ticket} not found")

            pos = positions[0]
            sym_info = self._mt5.symbol_info(pos.symbol)
            digits = sym_info.digits if sym_info else 5

            request = {
                "action": self._mt5.TRADE_ACTION_SLTP,
                "position": int(ticket),
                "symbol": pos.symbol,
                "sl": round(float(sl), digits) if sl else pos.sl,
                "tp": round(float(tp), digits) if tp else pos.tp,
            }

            result = self._mt5.order_send(request)
            if result is None:
                return OrderResult(success=False, error="order_send returned None")

            ok = result.retcode == self._mt5.TRADE_RETCODE_DONE
            return OrderResult(
                success=ok,
                order_id=result.order if ok else 0,
                error="" if ok else f"retcode={result.retcode}",
            )
        except Exception as exc:
            return OrderResult(success=False, error=str(exc))

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _port_is_open(host: str, port: int, timeout: float = 1.0) -> bool:
        """Check if a TCP port is accepting connections."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _tf_map(self, timeframe: str) -> int:
        """Map string timeframe to MT5 constant."""
        from mt5linux import MetaTrader5
        mapping = {
            "M1": MetaTrader5.TIMEFRAME_M1,
            "M5": MetaTrader5.TIMEFRAME_M5,
            "M15": MetaTrader5.TIMEFRAME_M15,
            "M30": MetaTrader5.TIMEFRAME_M30,
            "H1": MetaTrader5.TIMEFRAME_H1,
            "H4": MetaTrader5.TIMEFRAME_H4,
            "D1": MetaTrader5.TIMEFRAME_D1,
            "W1": MetaTrader5.TIMEFRAME_W1,
            "MN1": MetaTrader5.TIMEFRAME_MN1,
        }
        return mapping.get(timeframe.upper(), MetaTrader5.TIMEFRAME_H1)
