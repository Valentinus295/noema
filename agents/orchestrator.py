"""Orchestrator — schedules cadences, fans events over the in-process bus.

Contract pinned in docs/ARCHITECTURE.md §1.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from noema.core.types import Bar, Bias, Direction, Setup, Verdict
from noema.agents.trend import analyze_trend
from noema.agents.structure import analyze_structure
from noema.agents.confluence import ConfluenceState, conflate
from noema.agents.risk import RiskParams, compute_sl_tp, compute_position_size
from noema.agents.guardian import GuardianState, guardian_guard
from noema.broker.base import BrokerProtocol, OrderRequest


@dataclass
class OrchestratorState:
    symbol: str
    bars: dict[str, list[Bar]] = field(default_factory=dict)
    current_setup: Setup | None = None
    guardian_state: GuardianState = field(default_factory=GuardianState)
    risk_params: RiskParams = field(default_factory=RiskParams)
    position_count: int = 0
    last_check: datetime | None = None


class Orchestrator:
    def __init__(self, broker: BrokerProtocol, state: OrchestratorState):
        self.broker = broker
        self.state = state
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def _fetch_data(self) -> list[Bar]:
        bars = await self.broker.bars(self.state.symbol, "H1", 200)
        self.state.bars["H1"] = list(bars)
        return list(bars)

    async def _run_agents(self, bars: list[Bar]) -> ConfluenceState:
        trend_verdict = analyze_trend(self.state.symbol, {"H1": bars})
        structure_verdict = analyze_structure(self.state.symbol, bars)

        rsi_val = 50.0
        candle_pat = None

        return ConfluenceState(
            symbol=self.state.symbol,
            trend_verdict=trend_verdict,
            structure_verdict=structure_verdict,
            bars=bars,
            rsi_value=rsi_val,
            candle_pattern=candle_pat,
        )

    async def _evaluate_and_trade(self, state: ConfluenceState) -> None:
        setup = conflate(state)
        if not setup:
            return

        approved, reason = await guardian_guard(
            self.state.guardian_state, setup, self.state.guardian_state.daily_pnl
        )

        if not approved:
            return

        self.state.current_setup = setup

        symbol_info = await self.broker.symbol_info(setup.symbol)
        lot_size = compute_position_size(
            (await self.broker.account_state()).balance,
            setup.entry_zone_lo,
            setup.sl_reference,
            self.state.risk_params,
            symbol_info,
        )

        sl, tp = compute_sl_tp(
            setup.bars if setup.bars else [], setup.entry_zone_lo, setup.direction, 1.5, 3.0
        )

        order = OrderRequest(
            symbol=setup.symbol,
            side="buy" if setup.direction == Direction("bullish") else "sell",
            type="market",
            volume=lot_size,
            price=None,
            sl=sl,
            tp=tp,
            comment=f"Noema {hashlib.md5(str(setup).encode()).hexdigest()[:8]}",
        )

        await self.broker.send_order(order)

    async def run_cycle(self) -> None:
        try:
            bars = await self._fetch_data()
            conf_state = await self._run_agents(bars)
            await self._evaluate_and_trade(conf_state)
            self.state.last_check = datetime.now(timezone.utc)
        except Exception as e:
            print(f"Orchestration error: {e}")

    async def start(self, interval: float = 60.0) -> None:
        self._running = True
        self._tasks.append(asyncio.create_task(self._run_loop(interval)))

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    async def _run_loop(self, interval: float) -> None:
        while self._running:
            await self.run_cycle()
            await asyncio.sleep(interval)
