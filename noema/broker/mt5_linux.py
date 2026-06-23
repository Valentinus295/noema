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

Requirements:
    - Wine with MT5 installed
    - mt5linux package (pip install mt5linux)
    - MT5 terminal running under Wine (see scripts/start_mt5.py)
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from noema.broker.base import BrokerBase, OrderResult, Position

logger = structlog.get_logger(__name__)

# Default paths for Pop!_OS / Ubuntu
DEFAULT_WINE_MT5_PATH = Path.home() / ".wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
DEFAULT_RPYC_PORT = 18812
DEFAULT_RPYC_HOST = "127.0.0.1"
DEFAULT_STARTUP_WAIT = 120  # seconds

TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1", "MN1": "TIMEFRAME_MN1",
}


class MT5LinuxBroker(BrokerBase):
    """MetaTrader 5 broker for Linux via Wine + RPyC.

    This broker wraps mt5linux to provide the same interface as the
    Windows-native MT5Broker, but works on Pop!_OS and Ubuntu.

    Usage:
        broker = MT5LinuxBroker(config)
        broker.initialize()
        broker.place_order(symbol="EURUSD", ...)
    """

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._mt5 = None          # mt5linux client
        self._rpyc_process = None
        self._connected = False
        self._host = DEFAULT_RPYC_HOST
        self._port = DEFAULT_RPYC_PORT

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
        return True

    def shutdown(self) -> None:
        """Disconnect from MT5."""
        if self._mt5 and self._connected:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

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
        """Get current tick."""
        if not self._connected:
            return None
        try:
            tick = self._mt5.symbol_info_tick(symbol)
            if tick is None:
                return None
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
