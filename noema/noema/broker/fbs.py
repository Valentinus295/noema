"""FBSBroker integration via MT5 bridge.

FBS also uses MT5 infrastructure with different connection parameters.
"""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

import structlog

from noema.broker.base import BrokerBase, OrderResult, Position

logger = structlog.get_logger(__name__)


class FBSBroker(BrokerBase):
    """FBS broker connector — mirrors MT5Broker structure."""

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self._mt5 = None
        self._connected = False

    def initialize(self) -> bool:
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5
            if not mt5.initialize():
                self._logger.error("fbs_mt5_init_failed")
                return False
            self._connected = True
            return True
        except ImportError:
            self._logger.error("metatrader5_package_not_installed")
            return False

    def shutdown(self) -> None:
        if self._mt5:
            self._mt5.shutdown()
            self._connected = False

    def get_account_info(self) -> dict[str, Any]:
        if not self._connected:
            return {}
        info = self._mt5.account_info()
        if info is None:
            return {}
        return {
            "balance": info.balance, "equity": info.equity,
            "margin": info.margin, "free_margin": info.margin_free,
            "leverage": info.leverage, "currency": info.currency,
        }

    def get_tick(self, symbol: str) -> dict[str, float]:
        if not self._connected:
            return {"bid": 0, "ask": 0}
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"bid": 0, "ask": 0}
        return {"bid": tick.bid, "ask": tick.ask, "time": tick.time}

    def get_rates(self, symbol: str, timeframe: str, count: int = 100) -> Any:
        if not self._connected:
            return None
        from noema.broker.mt5 import TIMEFRAME_MAP
        tf_attr = TIMEFRAME_MAP.get(timeframe.upper())
        if not tf_attr:
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
        sl: float = 0, tp: float = 0, magic: int = 0, comment: str = "Noema-FBS"
    ) -> OrderResult:
        if not self._connected:
            return OrderResult(success=False, error="Not connected")
        info = self._mt5.symbol_info(symbol)
        if info is None:
            return OrderResult(success=False, error=f"Symbol {symbol} not found")
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(success=False, error="No tick data")
        price = tick.ask if direction.lower() == "buy" else tick.bid
        order_type = self._mt5.ORDER_TYPE_BUY if direction.lower() == "buy" else self._mt5.ORDER_TYPE_SELL
        request = {
            "action": self._mt5.TRADE_ACTION_DEAL, "symbol": symbol,
            "volume": volume, "type": order_type, "price": price,
            "deviation": 20, "magic": magic, "comment": comment,
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }
        if sl > 0: request["sl"] = sl
        if tp > 0: request["tp"] = tp
        result = self._mt5.order_send(request)
        if result is None:
            return OrderResult(success=False, error="order_send returned None")
        if result.retcode == self._mt5.TRADE_RETCODE_DONE:
            return OrderResult(success=True, ticket=result.order, price=result.price, volume=result.volume)
        return OrderResult(success=False, error=result.comment)

    def modify_position(self, ticket: int, sl: float = 0, tp: float = 0) -> bool:
        if not self._connected: return False
        positions = self._mt5.positions_get(ticket=ticket)
        if not positions: return False
        pos = positions[0]
        request = {
            "action": self._mt5.TRADE_ACTION_SLTP, "position": ticket,
            "symbol": pos.symbol,
            "sl": sl if sl > 0 else pos.sl,
            "tp": tp if tp > 0 else pos.tp,
        }
        result = self._mt5.order_send(request)
        return result is not None and result.retcode == self._mt5.TRADE_RETCODE_DONE

    def close_position(self, ticket: int) -> bool:
        if not self._connected: return False
        positions = self._mt5.positions_get(ticket=ticket)
        if not positions: return False
        pos = positions[0]
        tick = self._mt5.symbol_info_tick(pos.symbol)
        if tick is None: return False
        if pos.type == self._mt5.ORDER_TYPE_BUY:
            price, close_type = tick.bid, self._mt5.ORDER_TYPE_SELL
        else:
            price, close_type = tick.ask, self._mt5.ORDER_TYPE_BUY
        request = {
            "action": self._mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol,
            "volume": pos.volume, "type": close_type, "position": ticket,
            "price": price, "deviation": 20, "magic": pos.magic,
            "comment": "Noema-FBS Close",
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }
        result = self._mt5.order_send(request)
        return result is not None and result.retcode == self._mt5.TRADE_RETCODE_DONE

    def get_open_positions(self, magic: int = 0) -> list[Position]:
        if not self._connected: return []
        positions = self._mt5.positions_get(magic=magic) if magic else self._mt5.positions_get()
        if positions is None: return []
        return [
            Position(ticket=p.ticket, symbol=p.symbol,
                     type="buy" if p.type == 0 else "sell",
                     volume=p.volume, open_price=p.price_open,
                     current_price=p.price_current, sl=p.sl, tp=p.tp,
                     pnl=p.profit, magic=p.magic)
            for p in positions
        ]

    def get_daily_pnl(self) -> float:
        if not self._connected: return 0.0
        from datetime import datetime
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = self._mt5.history_deals_get(start, now)
        return sum(d.profit for d in deals) if deals else 0.0

    def get_weekly_pnl(self) -> float:
        if not self._connected: return 0.0
        from datetime import datetime, timedelta
        now = datetime.now()
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = self._mt5.history_deals_get(start, now)
        return sum(d.profit for d in deals) if deals else 0.0
