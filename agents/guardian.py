"""GuardianAgent — pre-trade AND pre-order-send veto + global kill-switches.

Contract pinned in docs/ARCHITECTURE.md §10.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from noema.core.types import Bias, Direction, Setup


@dataclass
class GuardianState:
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    daily_loss_limit: float = 3.0
    weekly_loss_limit: float = 8.0
    last_heartbeat: datetime | None = None
    heartbeat_timeout: int = 30
    news_blackout: bool = False
    news_blackout_until: datetime | None = None
    spread_multiplier: float = 2.0


def check_daily_loss(state: GuardianState) -> bool:
    return abs(state.daily_pnl) >= state.daily_loss_limit


def check_weekly_loss(state: GuardianState) -> bool:
    return abs(state.weekly_pnl) >= state.weekly_loss_limit


def check_news_blackout(state: GuardianState, symbol: str) -> bool:
    if state.news_blackout:
        return True
    if state.news_blackout_until:
        return datetime.now(timezone.utc) < state.news_blackout_until
    return False


def check_heartbeat(state: GuardianState) -> bool:
    if not state.last_heartbeat:
        return False
    elapsed = (datetime.now(timezone.utc) - state.last_heartbeat).total_seconds()
    return elapsed < state.heartbeat_timeout


async def guardian_guard(
    state: GuardianState, setup: Setup | None, current_pnl: float
) -> tuple[bool, str]:
    state.daily_pnl = current_pnl
    state.weekly_pnl = current_pnl

    if check_daily_loss(state):
        return False, f"Daily loss limit reached: {state.daily_pnl:.2f}%"

    if check_weekly_loss(state):
        return False, f"Weekly loss limit reached: {state.weekly_pnl:.2f}%"

    if setup:
        if check_news_blackout(state, setup.symbol):
            return False, "News blackout active"

    return True, "Approved"


async def heartbeat_task(state: GuardianState, interval: float = 5.0):
    while True:
        state.last_heartbeat = datetime.now(timezone.utc)
        await asyncio.sleep(interval)
