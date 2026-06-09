"""FBSBroker integration via MT5 bridge.

FBS also uses MT5 infrastructure with different connection parameters.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

import rpyc

from vmpm.broker.base import BrokerProtocol, Bar, Tick, AccountState, OrderRequest, Position


class FBSBroker(BrokerProtocol):
    name = "fbs"

    def __init__(self, host: str = "127.0.0.1", port: int = 22223, password: str = ""):
        self._host = host
        self._port = port
        self._password = password
        self._conn: rpyc.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if self._conn:
                return
            loop = asyncio.get_event_loop()
            self._conn = await loop.run_in_executor(None, rpyc.connect, self._host, self._port)
            if self._password:
                self._conn.root.auth(self._password)

    async def disconnect(self) -> None:
        async with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    async def is_connected(self) -> bool:
        return self._conn is not None

    async def account_state(self) -> AccountState:
        if not self._conn:
            raise RuntimeError("Not connected")
        state = await asyncio.get_event_loop().run_in_executor(None, self._conn.root.account_state)
        return AccountState(**state)

    async def bars(self, symbol: str, timeframe: str, count: int) -> Sequence[Bar]:
        if not self._conn:
            raise RuntimeError("Not connected")
        data = await asyncio.get_event_loop().run_in_executor(
            None, self._conn.root.bars, symbol, timeframe, count
        )
        return [Bar(**bar) for bar in data]

    async def tick(self, symbol: str) -> Tick:
        if not self._conn:
            raise RuntimeError("Not connected")
        data = await asyncio.get_event_loop().run_in_executor(None, self._conn.root.tick, symbol)
        return Tick(**data)

    async def symbol_info(self, symbol: str) -> dict:
        if not self._conn:
            raise RuntimeError("Not connected")
        return await asyncio.get_event_loop().run_in_executor(
            None, self._conn.root.symbol_info, symbol
        )

    async def positions(self) -> Sequence[Position]:
        if not self._conn:
            raise RuntimeError("Not connected")
        data = await asyncio.get_event_loop().run_in_executor(None, self._conn.root.positions)
        return [Position(**p) for p in data]

    async def send_order(self, req: OrderRequest) -> Position:
        if not self._conn:
            raise RuntimeError("Not connected")
        data = await asyncio.get_event_loop().run_in_executor(
            None, self._conn.root.send_order, req.__dict__
        )
        return Position(**data)

    async def modify_position(self, ticket: int, sl: float | None, tp: float | None) -> Position:
        if not self._conn:
            raise RuntimeError("Not connected")
        data = await asyncio.get_event_loop().run_in_executor(
            None, self._conn.root.modify_position, ticket, sl, tp
        )
        return Position(**data)

    async def close_position(self, ticket: int, volume: float | None = None) -> Position:
        if not self._conn:
            raise RuntimeError("Not connected")
        data = await asyncio.get_event_loop().run_in_executor(
            None, self._conn.root.close_position, ticket, volume
        )
        return Position(**data)

    async def close_all_positions(self, reason: str) -> Sequence[Position]:
        if not self._conn:
            raise RuntimeError("Not connected")
        data = await asyncio.get_event_loop().run_in_executor(
            None, self._conn.root.close_all_positions, reason
        )
        return [Position(**p) for p in data]
