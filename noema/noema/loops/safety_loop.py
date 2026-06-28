"""Safety Loop — Guardian check_all() every second.

Priority: 0 (highest — can interrupt any other loop)
Cadence: 1 second

This loop is the "innate immune system" of NOEMA. It runs
GuardianAgent.check_all() every second and can halt the entire
system if a kill-switch triggers.

Rules:
- Never pauses (unless system halts)
- Never stops (unless system halts)
- Can interrupt any other loop (highest priority)
- Must be deterministic — no LLM in the critical path
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from noema.core.loop import TradingLoop

logger = structlog.get_logger(__name__)


class SafetyLoop(TradingLoop):
    """Runs Guardian check_all() every second.

    If any kill-switch triggers, this loop can halt trading
    and pause lower-priority loops via the LoopManager.
    """

    def __init__(
        self,
        guardian: Any,  # GuardianAgent — avoid circular import
        guardian_state: Any = None,  # GuardianState
        on_kill_switch: Any = None,  # async callback(triggered: list[dict])
        account_state_provider: Any = None,  # async callable -> dict
    ):
        super().__init__(
            name="safety",
            cadence_seconds=1.0,
            priority=0,
            max_consecutive_errors=3,  # Safety is strict
        )
        self.guardian = guardian
        self.guardian_state = guardian_state
        self._on_kill_switch = on_kill_switch
        self._account_state_provider = account_state_provider

    async def tick(self) -> None:
        """Run Guardian check_all(). Alert on kill-switch triggers."""
        # Get current account state if provider is available
        account_state: Optional[dict[str, float]] = None
        if self._account_state_provider:
            try:
                account_state = await self._account_state_provider()
            except Exception as e:
                self.logger.warning("account_state_fetch_failed", error=str(e))

        # Run Guardian checks
        triggered = await self.guardian.check_all(account_state)

        if triggered:
            self.logger.warning(
                "safety_kill_switch_triggered",
                count=len(triggered),
                switches=[t.get("id", "unknown") for t in triggered],
            )
            # Notify LoopManager via callback
            if self._on_kill_switch:
                try:
                    await self._on_kill_switch(triggered)
                except Exception as e:
                    self.logger.error("kill_switch_callback_failed", error=str(e))
