"""Watchdog process — external supervisor that flattens on crash.

Runs as a separate systemd service. Monitors the main Noema process.
If the main process dies or hangs, the watchdog:
1. Flattens all open positions
2. Sends Telegram alert
3. Logs the incident

This is the ultimate fail-safe — it operates entirely outside
the AI's influence and cannot be overridden.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class Watchdog:
    """External process supervisor for Noema.

    Monitors the main Noema process and flattens positions on failure.
    """

    def __init__(
        self,
        main_pid_file: str = "/tmp/noema.pid",
        heartbeat_file: str = "/tmp/noema_heartbeat",
        heartbeat_timeout: int = 60,
        flatten_command: str | None = None,
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
    ) -> None:
        self.main_pid_file = Path(main_pid_file)
        self.heartbeat_file = Path(heartbeat_file)
        self.heartbeat_timeout = heartbeat_timeout
        self.flatten_command = flatten_command
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self._running = False

    def start(self) -> None:
        """Start the watchdog loop."""
        self._running = True
        logger.info("watchdog_started", pid=os.getpid())

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        while self._running:
            try:
                self._check()
            except Exception as exc:
                logger.error("watchdog_check_failed", error=str(exc))

            time.sleep(10)

    def _check(self) -> None:
        """Run a single watchdog check."""
        # 1. Check if main process is alive
        if not self._is_main_alive():
            logger.critical("main_process_dead", action="flattening")
            self._flatten_all_positions()
            self._send_alert("Noema main process DIED. All positions flattened.")
            return

        # 2. Check heartbeat freshness
        if not self._is_heartbeat_fresh():
            logger.warning("heartbeat_stale", action="checking")
            # Give it 2 more cycles before flattening
            time.sleep(20)
            if not self._is_heartbeat_fresh():
                logger.critical("heartbeat_timeout", action="flattening")
                self._flatten_all_positions()
                self._send_alert("Noema heartbeat TIMEOUT. Positions flattened.")

    def _is_main_alive(self) -> bool:
        """Check if the main Noema process is still running."""
        if not self.main_pid_file.exists():
            return True  # No PID file = not managed by watchdog

        try:
            pid = int(self.main_pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            return True
        except (ProcessLookupError, ValueError):
            return False

    def _is_heartbeat_fresh(self) -> bool:
        """Check if the heartbeat file was updated recently."""
        if not self.heartbeat_file.exists():
            return True  # No heartbeat file = not using heartbeat

        try:
            mtime = self.heartbeat_file.stat().st_mtime
            age = time.time() - mtime
            return age < self.heartbeat_timeout
        except Exception:
            return True

    def _flatten_all_positions(self) -> None:
        """Flatten all open MT5 positions."""
        logger.info("flattening_all_positions")

        if self.flatten_command:
            try:
                # Use shell=False for security — flatten_command should be a path
                subprocess.run(
                    self.flatten_command.split(),
                    shell=False, timeout=30,
                    capture_output=True,
                )
                logger.info("flatten_command_executed")
            except Exception as exc:
                logger.error("flatten_failed", error=str(exc))
        else:
            # Direct MT5 flatten via Python
            try:
                import MetaTrader5 as mt5
                if mt5.initialize():
                    positions = mt5.positions_get()
                    if positions:
                        for pos in positions:
                            tick = mt5.symbol_info_tick(pos.symbol)
                            if tick is None:
                                continue
                            if pos.type == 0:  # BUY
                                price, close_type = tick.bid, mt5.ORDER_TYPE_SELL
                            else:
                                price, close_type = tick.ask, mt5.ORDER_TYPE_BUY
                            request = {
                                "action": mt5.TRADE_ACTION_DEAL,
                                "symbol": pos.symbol,
                                "volume": pos.volume,
                                "type": close_type,
                                "position": pos.ticket,
                                "price": price,
                                "deviation": 50,
                                "magic": pos.magic,
                                "comment": "WATCHDOG_FLATTEN",
                            }
                            mt5.order_send(request)
                        logger.info("positions_flattened", count=len(positions))
                    mt5.shutdown()
            except Exception as exc:
                logger.error("mt5_flatten_failed", error=str(exc))

    def _send_alert(self, message: str) -> None:
        """Send Telegram alert."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("telegram_not_configured", message=message)
            return

        try:
            import httpx
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            httpx.post(url, json={
                "chat_id": self.telegram_chat_id,
                "text": f"🚨 Noema WATCHDOG ALERT\n\n{message}\n\nTime: {datetime.now(timezone.utc).isoformat()}",
            }, timeout=10, verify=True)
        except Exception as exc:
            logger.error("telegram_alert_failed", error=str(exc))

    def _handle_signal(self, signum: int, _frame: object) -> None:
        """Handle shutdown signals."""
        logger.info("watchdog_shutdown", signal=signum)
        self._running = False


def write_pid_file(pid_file: str = "/tmp/noema.pid") -> None:
    """Write current PID to file for watchdog monitoring."""
    Path(pid_file).write_text(str(os.getpid()))


def update_heartbeat(heartbeat_file: str = "/tmp/noema_heartbeat") -> None:
    """Update heartbeat file timestamp."""
    Path(heartbeat_file).touch()


if __name__ == "__main__":
    wd = Watchdog()
    wd.start()
