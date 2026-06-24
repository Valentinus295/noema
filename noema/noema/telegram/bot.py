"""Noema Telegram Bot — NL-first chat-based trading dashboard.

Natural language chat is PRIMARY. Slash commands are shortcuts that route
through the same NL pipeline with the same personality and live system data.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Token-bucket rate limiter per chat."""

    def __init__(self, max_per_minute: int = 10) -> None:
        self.max_per_minute = max_per_minute
        self._buckets: dict[str, list[float]] = {}

    def check(self, chat_id: str) -> bool:
        now = time.monotonic()
        window = now - 60
        bucket = self._buckets.setdefault(chat_id, [])
        bucket[:] = [t for t in bucket if t > window]
        return len(bucket) < self.max_per_minute

    def record(self, chat_id: str) -> None:
        self._buckets.setdefault(chat_id, []).append(time.monotonic())


class NoemaTelegramBot:
    """NL-first Telegram bot for Noema.

    All messages — commands and free text — route through the same
    handler pipeline with live system data injection and session memory.
    """

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        handlers: Any = None,
        nim_client: Any = None,
    ) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._rate_limiter = RateLimiter(
            max_per_minute=int(os.getenv("Noema_TELEGRAM_RATE_LIMIT", "10"))
        )
        self._handlers = handlers
        self._nim = nim_client
        self._application: Any = None
        self._running = False
        self._start_time = time.monotonic()
        self._daily_summary_time = os.getenv("Noema_TELEGRAM_DAILY_SUMMARY_TIME", "21:00")
        self._daily_summary_task: asyncio.Task | None = None

    def set_handlers(self, handlers: Any) -> None:
        self._handlers = handlers

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        if not self.bot_token or not self.chat_id:
            logger.warning("telegram_not_configured")
            return

        try:
            from telegram.ext import (
                Application, CommandHandler, MessageHandler, filters,
            )

            self._application = Application.builder().token(self.bot_token).build()

            # Register all known command names → single wrapper
            known_commands = [
                "status", "positions", "pnl", "guardian", "events",
                "why", "exposure", "help", "start",
            ]
            for cmd in known_commands:
                self._application.add_handler(
                    CommandHandler(cmd, self._handle_command)
                )

            # Natural language text
            self._application.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
            )

            # Unknown commands
            self._application.add_handler(
                MessageHandler(filters.COMMAND, self._handle_unknown_command)
            )

            self._running = True
            await self._application.initialize()
            await self._application.start()
            await self._application.updater.start_polling()

            await self.send_alert("Noema Telegram bot online")
            self._daily_summary_task = asyncio.create_task(self._daily_summary_loop())
            logger.info("telegram_bot_started", daily_summary_time=self._daily_summary_time)

        except ImportError:
            logger.error("python_telegram_bot_not_installed")
        except Exception as exc:
            logger.error("telegram_start_failed", error=str(exc))

    async def stop(self) -> None:
        self._running = False
        if self._daily_summary_task and not self._daily_summary_task.done():
            self._daily_summary_task.cancel()
            try:
                await self._daily_summary_task
            except asyncio.CancelledError:
                pass
        if self._application:
            try:
                await self._application.updater.stop()
                await self._application.stop()
                await self._application.shutdown()
            except Exception:
                pass
        logger.info("telegram_bot_stopped")

    # ── Auth & Rate Limit ──────────────────────────────────────────

    def _auth(self, update: Any) -> bool:
        try:
            chat_id = str(getattr(update.effective_chat, "id", ""))
            return chat_id == self.chat_id
        except Exception:
            return False

    def _check_rate_limit(self, update: Any) -> bool:
        try:
            chat_id = str(getattr(update.effective_chat, "id", "0"))
            allowed = self._rate_limiter.check(chat_id)
            if not allowed:
                logger.warning("telegram_rate_limited", chat_id=chat_id)
            else:
                self._rate_limiter.record(chat_id)
            return allowed
        except Exception:
            return True

    # ── Message Handlers ───────────────────────────────────────────

    async def _handle_command(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        if not self._check_rate_limit(update):
            await update.message.reply_text("Rate limit exceeded. Max 10 per minute.")
            return

        chat_id = str(update.effective_chat.id)
        command = update.message.text.split()[0].lower()
        args = update.message.text[len(command):].strip()

        # Block trade commands before any processing
        from noema.telegram.handlers import BLOCKED_COMMANDS, BLOCKED_RESPONSE
        if command in BLOCKED_COMMANDS:
            await update.message.reply_text(BLOCKED_RESPONSE)
            return

        if self._handlers:
            response = await self._handlers.handle_command(chat_id, command, args)
            if response:
                await update.message.reply_text(response)
            else:
                # Unknown → treat as NL
                await self._handle_nl(update, update.message.text)
        else:
            await update.message.reply_text("Handlers not configured.")

    async def _handle_message(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        if not self._check_rate_limit(update):
            await update.message.reply_text("Rate limit exceeded. Max 10 per minute.")
            return
        text = update.message.text.strip()
        if text:
            await self._handle_nl(update, text)

    async def _handle_nl(self, update: Any, text: str) -> None:
        """Route text through the NL handler with typing indicator."""
        try:
            await self._application.bot.send_chat_action(
                chat_id=update.effective_chat.id, action="typing"
            )
        except Exception:
            pass

        chat_id = str(update.effective_chat.id)
        if self._handlers and hasattr(self._handlers, "handle_natural_language"):
            response = await self._handlers.handle_natural_language(chat_id, text)
            # Try MarkdownV2, fallback to plain text
            try:
                await update.message.reply_text(response, parse_mode="MarkdownV2")
            except Exception:
                await update.message.reply_text(response)
        else:
            await update.message.reply_text(
                "Natural language chat is not configured. Try /help for available commands."
            )

    async def _handle_unknown_command(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        if not self._check_rate_limit(update):
            await update.message.reply_text("Rate limit exceeded.")
            return

        from noema.telegram.handlers import BLOCKED_COMMANDS, BLOCKED_RESPONSE
        command = update.message.text.split()[0].lower()
        if command in BLOCKED_COMMANDS:
            await update.message.reply_text(BLOCKED_RESPONSE)
            return

        # Unknown commands → try NL
        await self._handle_nl(update, update.message.text)

    # ── Alert Methods ──────────────────────────────────────────────

    async def send_alert(self, message: str) -> bool:
        if not self._application or not self.chat_id:
            return False
        try:
            await self._application.bot.send_message(
                chat_id=int(self.chat_id), text=message
            )
            return True
        except Exception as exc:
            logger.error("telegram_send_alert_failed", error=str(exc))
            return False

    async def send_markdown_alert(self, message: str) -> bool:
        if not self._application or not self.chat_id:
            return False
        try:
            await self._application.bot.send_message(
                chat_id=int(self.chat_id),
                text=message,
                parse_mode="MarkdownV2",
            )
            return True
        except Exception:
            try:
                await self._application.bot.send_message(
                    chat_id=int(self.chat_id), text=message
                )
                return True
            except Exception as exc:
                logger.error("telegram_send_markdown_failed", error=str(exc))
                return False

    async def send_broker_disconnect_alert(self, reason: str = "", duration: float = 0.0) -> None:
        if self._handlers and hasattr(self._handlers, "send_broker_disconnect_alert"):
            msg = await self._handlers.send_broker_disconnect_alert(reason, duration)
            await self.send_markdown_alert(msg)

    async def send_killswitch_alert(self, switch_id: str, reason: str = "", symbol: str = "") -> None:
        if self._handlers and hasattr(self._handlers, "send_killswitch_alert"):
            msg = await self._handlers.send_killswitch_alert(switch_id, reason, symbol)
            await self.send_markdown_alert(msg)

    async def send_news_blackout_alert(self, event_name: str, pair: str = "", minutes: int = 0) -> None:
        if self._handlers and hasattr(self._handlers, "send_news_blackout_alert"):
            msg = await self._handlers.send_news_blackout_alert(event_name, pair, minutes)
            await self.send_markdown_alert(msg)

    # ── Daily Summary ──────────────────────────────────────────────

    async def _daily_summary_loop(self) -> None:
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                target = datetime.strptime(
                    f"{now.strftime('%Y-%m-%d')} {self._daily_summary_time}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=timezone.utc)
                if target <= now:
                    target += timedelta(days=1)

                wait = (target - now).total_seconds()
                while wait > 0 and self._running:
                    await asyncio.sleep(min(wait, 60))
                    wait -= 60

                if not self._running:
                    break

                if self._handlers and hasattr(self._handlers, "send_daily_summary"):
                    msg = await self._handlers.send_daily_summary()
                    await self.send_markdown_alert(msg)
                    logger.info("daily_summary_sent")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("daily_summary_error", error=str(e))
                await asyncio.sleep(300)
