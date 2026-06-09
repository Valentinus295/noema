"""MetaTrader 5 broker implementation for VMPM.

Requires: Windows OS, MT5 terminal running, MetaTrader5 Python package.
Compatible with FX Pesa, FBS, and any MT5 broker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog

from vmpm.broker.base import BrokerBase, OrderResult, Position

logger = structlog.get_logger(__name__)

# MT5 timeframe mapping
TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1", "MN1": "TIMEFRAME_MN1",
}


class MT5Broker(BrokerBase):
    """MetaTrader 5 broker connector.

    Works with FX Pesa, FBS, and any MT5-compatible broker.
    Requires the MT5 terminal to be running on Windows.
    """

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._mt5 = None
        self._connected = False

    def initialize(self) -> bool:
        """Connect to MT5 terminal."""
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5

            path = self.config.broker.mt5_path if self.config else ""
            login = self.config.broker.mt5_login if self.config else 0
            password = self.config.broker.mt5_password if self.config else ""
            server = self.config.broker.mt5_server if self.config else ""

            kwargs = {}
            if path:
                kwargs["path"] = path
            if login:
                kwargs["login"] = login
            if password:
                kwargs["password"] = password
            if server:
                kwargs["server"] = server

            if not mt5.initialize(**kwargs):
                error = mt5.last_error()
                self._logger.error("mt5_init_failed", error=str(error))
                return False

            info = mt5.account_info()
            if info:
                self._logger.info(
                    "mt5_connected",
                    login=info.login,
                    server=info.server,
                    balance=info.balance,
                )

            self._connected = True
            return True

        except ImportError:
            self._logger.error("metatrader5_package_not_installed")
            return False

    def shutdown(self) -> None:
        """Shutdown MT5 connection."""
        if self._mt5:
            self._mt5.shutdown()
            self._connected = False
            self._logger.info("mt5_disconnected")

    def get_account_info(self) -> dict[str, Any]:
        """Get MT5 account info."""
        if not self._connected:
            return {}
        info = self._mt5.account_info()
        if info is None:
            return {}
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "leverage": info.leverage,
            "currency": info.currency,
            "login": info.login,
            "server": info.server,
        }

    def get_tick(self, symbol: str) -> dict[str, float]:
        """Get current bid/ask tick."""
        if not self._connected:
            return {"bid": 0, "ask": 0}
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"bid": 0, "ask": 0}
        return {"bid": tick.bid, "ask": tick.ask, "time": tick.time}

    def get_rates(self, symbol: str, timeframe: str, count: int = 100) -> Any:
        """Get OHLCV rates from MT5."""
        if not self._connected:
            return None

        tf_attr = TIMEFRAME_MAP.get(timeframe.upper())
        if not tf_attr:
            self._logger.error("invalid_timeframe", timeframe=timeframe)
            return None

        tf = getattr(self._mt5, tf_attr)
        rates = self._mt5.copy_rates_from_pos(symbol, tf, 0, count)

        if rates is None or len(rates) == 0:
            return None

        import pandas as pd
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def place_order(
        self, symbol: str, direction: str, volume: float,
        sl: float = 0, tp: float = 0, magic: int = 0, comment: str = "VMPM"
    ) -> OrderResult:
        """Place a market order on MT5."""
        if not self._connected:
            return OrderResult(success=False, error="Not connected to MT5")

        info = self._mt5.symbol_info(symbol)
        if info is None:
            return OrderResult(success=False, error=f"Symbol {symbol} not found")

        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(success=False, error="No tick data")

        point = info.point

        if direction.lower() == "buy":
            price = tick.ask
            order_type = self._mt5.ORDER_TYPE_BUY
        else:
            price = tick.bid
            order_type = self._mt5.ORDER_TYPE_SELL

        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }

        if sl > 0:
            request["sl"] = sl
        if tp > 0:
            request["tp"] = tp

        result = self._mt5.order_send(request)

        if result is None:
            return OrderResult(success=False, error="order_send returned None")

        if result.retcode == self._mt5.TRADE_RETCODE_DONE:
            self._logger.info(
                "order_executed",
                ticket=result.order,
                symbol=symbol,
                direction=direction,
                volume=result.volume,
                price=result.price,
            )
            return OrderResult(
                success=True,
                ticket=result.order,
                price=result.price,
                volume=result.volume,
            )
        else:
            error = result.comment
            self._logger.error("order_failed", error=error, retcode=result.retcode)
            return OrderResult(success=False, error=error)

    def modify_position(self, ticket: int, sl: float = 0, tp: float = 0) -> bool:
        """Modify SL/TP of an open position."""
        if not self._connected:
            return False

        positions = self._mt5.positions_get(ticket=ticket)
        if not positions:
            return False

        pos = positions[0]
        request = {
            "action": self._mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": pos.symbol,
            "sl": sl if sl > 0 else pos.sl,
            "tp": tp if tp > 0 else pos.tp,
        }

        result = self._mt5.order_send(request)
        return result is not None and result.retcode == self._mt5.TRADE_RETCODE_DONE

    def close_position(self, ticket: int) -> bool:
        """Close an open position."""
        if not self._connected:
            return False

        positions = self._mt5.positions_get(ticket=ticket)
        if not positions:
            return False

        pos = positions[0]
        tick = self._mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False

        if pos.type == self._mt5.ORDER_TYPE_BUY:
            price = tick.bid
            close_type = self._mt5.ORDER_TYPE_SELL
        else:
            price = tick.ask
            close_type = self._mt5.ORDER_TYPE_BUY

        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": pos.magic,
            "comment": "VMPM Close",
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }

        result = self._mt5.order_send(request)
        return result is not None and result.retcode == self._mt5.TRADE_RETCODE_DONE

    def get_open_positions(self, magic: int = 0) -> list[Position]:
        """Get open positions, optionally filtered by magic."""
        if not self._connected:
            return []

        if magic:
            positions = self._mt5.positions_get(magic=magic)
        else:
            positions = self._mt5.positions_get()

        if positions is None:
            return []

        return [
            Position(
                ticket=p.ticket,
                symbol=p.symbol,
                type="buy" if p.type == 0 else "sell",
                volume=p.volume,
                open_price=p.price_open,
                current_price=p.price_current,
                sl=p.sl,
                tp=p.tp,
                pnl=p.profit,
                magic=p.magic,
            )
            for p in positions
        ]

    def get_daily_pnl(self) -> float:
        """Get today's realized P&L from deal history."""
        if not self._connected:
            return 0.0
        from datetime import datetime, timedelta
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = self._mt5.history_deals_get(start, now)
        if deals is None:
            return 0.0
        return sum(d.profit for d in deals)

    def get_weekly_pnl(self) -> float:
        """Get this week's realized P&L."""
        if not self._connected:
            return 0.0
        from datetime import datetime, timedelta
        now = datetime.now()
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = self._mt5.history_deals_get(start, now)
        if deals is None:
            return 0.0
        return sum(d.profit for d in deals)
