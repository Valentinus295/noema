"""Telegram control surface for VMPM.

Provides remote control of the trading system via Telegram bot commands.
Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.

Commands:
  /status    — System status, balance, open positions
  /positions — List all open positions with P&L
  /flatten   — Close ALL positions immediately
  /halt      — Halt trading, keep positions open
  /resume    — Resume trading after halt
  /balance   — Show account balance
  /lessons   — Show learned lessons from ReflectorAgent
  /learn     — Force ReflectorAgent to run learning cycle
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)


class TelegramBot:
    """Telegram bot for VMPM remote control."""

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        shared_secret: str = "",
    ) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.shared_secret = shared_secret or os.getenv("VMPM_TELEGRAM_SHARED_SECRET", "")
        self._bot: Any = None
        self._running = False
        self._handlers: dict[str, Callable] = {}

    def register_handlers(self, handlers: dict[str, Callable]) -> None:
        """Register command handlers."""
        self._handlers = handlers

    async def start(self) -> None:
        """Start the Telegram bot polling loop."""
        if not self.bot_token or not self.chat_id:
            logger.warning("telegram_not_configured")
            return

        try:
            from telegram import Update
            from telegram.ext import (
                Application, CommandHandler, ContextTypes,
            )

            self._bot = (
                Application.builder()
                .token(self.bot_token)
                .build()
            )

            # Register commands
            self._bot.add_command_handler("status", self._handle_status)
            self._bot.add_command_handler("positions", self._handle_positions)
            self._bot.add_command_handler("flatten", self._handle_flatten)
            self._bot.add_command_handler("halt", self._handle_halt)
            self._bot.add_command_handler("resume", self._handle_resume)
            self._bot.add_command_handler("balance", self._handle_balance)
            self._bot.add_command_handler("lessons", self._handle_lessons)
            self._bot.add_command_handler("learn", self._handle_learn)

            self._running = True
            await self._bot.initialize()
            await self._bot.start()
            await self._bot.updater.start_polling()

            await self.send_alert("✅ VMPM Telegram bot online")
            logger.info("telegram_bot_started")

        except ImportError:
            logger.warning("python_telegram_bot_not_installed")
        except Exception as exc:
            logger.error("telegram_start_failed", error=str(exc))

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        if self._bot:
            try:
                await self._bot.updater.stop()
                await self._bot.stop()
                await self._bot.shutdown()
            except Exception:
                pass
        logger.info("telegram_bot_stopped")

    async def send_alert(self, message: str) -> None:
        """Send an alert message to the configured chat."""
        if not self._bot or not self.chat_id:
            return
        try:
            await self._bot.bot.send_message(
                chat_id=int(self.chat_id),
                text=message,
                parse_mode=None,
            )
        except Exception as exc:
            logger.error("telegram_send_failed", error=str(exc))

    async def send_trade_alert(self, trade: dict[str, Any]) -> None:
        """Send a trade execution alert."""
        direction = trade.get("direction", "?").upper()
        symbol = trade.get("symbol", "?")
        price = trade.get("price", 0)
        lot = trade.get("volume", 0)
        sl = trade.get("sl", 0)
        tp = trade.get("tp", 0)

        msg = (
            f"📊 TRADE EXECUTED\n"
            f"  {direction} {lot} lots {symbol}\n"
            f"  Entry: {price:.5f}\n"
            f"  SL: {sl:.5f} | TP: {tp:.5f}\n"
            f"  Time: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        await self.send_alert(msg)

    # ── Command Handlers ──

    async def _handle_status(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        handler = self._handlers.get("status")
        if handler:
            status = await handler()
            await update.message.reply_text(status)
        else:
            await update.message.reply_text("Status handler not registered")

    async def _handle_positions(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        handler = self._handlers.get("positions")
        if handler:
            positions = await handler()
            await update.message.reply_text(positions)
        else:
            await update.message.reply_text("No open positions")

    async def _handle_flatten(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        if not self._verify_secret(update):
            await update.message.reply_text("❌ Invalid secret. Usage: /flatten <secret>")
            return
        handler = self._handlers.get("flatten")
        if handler:
            result = await handler()
            await update.message.reply_text(result)

    async def _handle_halt(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        if not self._verify_secret(update):
            await update.message.reply_text("❌ Invalid secret. Usage: /halt <secret>")
            return
        handler = self._handlers.get("halt")
        if handler:
            result = await handler()
            await update.message.reply_text(result)

    async def _handle_resume(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        if not self._verify_secret(update):
            await update.message.reply_text("❌ Invalid secret. Usage: /resume <secret>")
            return
        handler = self._handlers.get("resume")
        if handler:
            result = await handler()
            await update.message.reply_text(result)

    async def _handle_balance(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        handler = self._handlers.get("balance")
        if handler:
            balance = await handler()
            await update.message.reply_text(balance)

    async def _handle_lessons(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        handler = self._handlers.get("lessons")
        if handler:
            lessons = await handler()
            await update.message.reply_text(lessons)

    async def _handle_learn(self, update: Any, context: Any) -> None:
        if not self._auth(update):
            return
        handler = self._handlers.get("learn")
        if handler:
            result = await handler()
            await update.message.reply_text(result)

    def _auth(self, update: Any) -> bool:
        """Check if message is from authorized chat."""
        if str(update.effective_chat.id) != self.chat_id:
            logger.warning("unauthorized_telegram_access",
                           chat_id=update.effective_chat.id)
            return False
        return True

    def _verify_secret(self, update: Any) -> bool:
        """Verify shared secret in command."""
        if not self.shared_secret:
            return True  # No secret configured = allow all
        text = update.message.text or ""
        parts = text.split()
        return len(parts) > 1 and parts[1] == self.shared_secret
