"""Noema Telegram Integration — chat-based trading dashboard.

Provides:
- Command handlers (/status, /positions, /pnl, /guardian, /events, /why, /exposure, /help)
- Natural language chat via MiniMax M3 (NIM)
- Alert push for broker disconnect, kill-switch, news blackout
- Daily summary at configured time
- Anti-abuse: rate limiting, authentication, no trade commands via chat
"""

from noema.telegram.bot import NoemaTelegramBot
from noema.telegram.handlers import CommandHandlers

__all__ = ["NoemaTelegramBot", "CommandHandlers"]
