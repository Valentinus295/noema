"""Telegram handler — NATURAL LANGUAGE FIRST, commands are shortcuts.

The LLM is the primary interface. Every message — including slash commands —
goes through Noema's persona with live system data injected as context.
Numbers come from the statistical layer. The LLM does language and personality.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import structlog

from noema.telegram.formatters import (
    format_alert_broker_disconnect,
    format_alert_killswitch,
    format_alert_news_blackout,
    format_daily_summary,
)

logger = structlog.get_logger(__name__)

# ── Blocked commands — rejected before any processing ────────────────

BLOCKED_COMMANDS = frozenset({
    "/trade", "/buy", "/sell", "/close", "/flatten", "/halt", "/resume",
    "/modify", "/sl", "/tp", "/order", "/cancel", "/admin", "/config",
    "/settings", "/set", "/risk", "/lot", "/margin",
    "/stop", "/restart", "/shutdown",
})

BLOCKED_RESPONSE = (
    "⚠️ I can't execute trades or change settings via chat\\. "
    "Guardian blocks remote trading commands\\."
)

# ── Session memory (per chat) ────────────────────────────────────────

MAX_CONTEXT_TURNS = 8  # Keep last N conversation turns


class ChatSession:
    """Per-chat conversation memory."""

    def __init__(self) -> None:
        self.history: deque[dict[str, str]] = deque(maxlen=MAX_CONTEXT_TURNS)

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def get_context(self) -> list[dict[str, str]]:
        return list(self.history)


# ── System Prompt — Personality + Rules ──────────────────────────────

SYSTEM_PROMPT = """You are Noema — Valentine's AI trading partner and the chat interface to his multi-agent forex trading system.

PERSONALITY:
- Professional. Direct. Data-first.
- Your tone is a quantitative researcher talking to their partner — not customer service.
- Be warm when appropriate (greetings, encouragement), clinical when discussing data.
- Admit uncertainty. Say "I don't have that data" rather than guessing.
- Short replies by default. Expand only when asked for depth.

CADENCE:
- Greetings → 1-liner plus top-level state ("☀️ Morning Valentine. Noema green — EURUSD +23p, Guardian clear.")
- Status questions → concise bullet with key numbers
- Analysis questions → cite specific signals with confidence scores
- Worry questions → acknowledge concern, cite data, give measured assessment
- Trade requests → politely decline (you can't trade from chat)

RULES — VIOLATING ANY OF THESE IS A FAILURE:
1. ALL numbers MUST come from the [SYSTEM DATA] block below. Never invent, estimate, or hallucinate a number.
2. If [SYSTEM DATA] lacks a number you need, say exactly: "I don't have that data right now."
3. Your role is LANGUAGE + JUDGMENT — never data generation.
4. You CANNOT execute trades, modify settings, close positions, or override Guardian.
5. If asked to trade: "I can't execute trades via chat — Guardian blocks remote commands. But [current state of the trade]."
6. If asked about things outside trading (weather, news, jokes): respond briefly, then pivot back.
7. Keep trade-related advice analytical, not prescriptive. "Consider" not "You should."
8. Format numbers consistently: prices to 5 decimals, pips as integers ("+23 pips"), P&L as "$X.XX".

RESPONSE STRUCTURE (use naturally, not as headers):
- If the query is about system data: weave numbers into natural language.
- If the query asks for interpretation: separate data from analysis.
  Use "📊" for data citations, "💬" for your analysis.
- End with contextually useful next step if helpful (e.g., "/status for details").

[SYSTEM DATA]
{stats_context}

Additional context from recent analysis cycles:
{analysis_context}"""

# ── Slash command → natural language mappings ────────────────────────

# Commands become structured prompts for the LLM. The LLM gets both the
# structured prompt AND the live system data, so it can respond with
# personality while citing real numbers.

COMMAND_PROMPTS: dict[str, str] = {
    "/status": (
        "Give me a concise status update: account balance and equity, daily P&L, "
        "weekly P&L, open positions count, broker connection status, Guardian state "
        "(trading halted? any kill-switches triggered?), and uptime. "
        "Use the numbers from [SYSTEM DATA] above. Keep it brief — one paragraph plus a bullet list of key metrics."
    ),
    "/positions": (
        "Show all open positions: symbol, direction, entry price, current price, "
        "stop loss, take profit, lot size, unrealized P&L in dollars and pips. "
        "List each position on its own line. Include total portfolio P&L at the end. "
        "Use ONLY the numbers from [SYSTEM DATA]."
    ),
    "/pnl": (
        "Give me the P&L summary: daily, weekly, monthly P&L in dollars, "
        "number of trades in each period, and win rate for each period. "
        "Show as a clean list. Use ONLY the numbers from [SYSTEM DATA]."
    ),
    "/guardian": (
        "List ALL kill-switch states. For each switch show: name, status (OK or TRIGGERED), "
        "current value vs threshold. Group by category: Risk Limits, Statistical Monitors, "
        "Infrastructure, Phase 1 Protections. Flag any triggered switches prominently. "
        "Use ONLY the guardian data from [SYSTEM DATA]."
    ),
    "/events": (
        "Show upcoming economic events: name, currency, time, impact level (HIGH/MEDIUM/LOW). "
        "Also show current news blackout status — is any pair blacked out right now? "
        "If so, which events, which pairs, and how many minutes remain. "
        "Use ONLY the data from [SYSTEM DATA]."
    ),
    "/why": (
        "For {args}, explain the statistical basis of our position: "
        "what signals drove the entry (list agents and their signals with confidence scores), "
        "the decision reasoning, current P&L in pips, and current price vs entry. "
        "If we have no position in {args}, say so and show why we're not in it. "
        "Use ONLY the data from [SYSTEM DATA]."
    ),
    "/exposure": (
        "Show net exposure by currency: long vs short lots per currency, "
        "account balance and equity, margin used as percentage of equity. "
        "Highlight any currency with concentrated exposure (>2 lots net). "
        "Use ONLY the numbers from [SYSTEM DATA]."
    ),
    "/help": (
        "List the available Telegram commands and what they do. "
        "Mention that natural language chat is the primary interface — "
        "people can just talk normally. Keep it friendly."
    ),
    "/start": (
        "Welcome the user to Noema Telegram. Introduce yourself briefly, "
        "mention that natural language chat is the primary way to interact, "
        "and list the key available commands."
    ),
}


class CommandHandlers:
    """NL-first handler: all messages go through Noema's persona with live data.

    Slash commands are shortcuts that prepend a structured prompt.
    Natural language passes through directly with full context.
    """

    def __init__(
        self,
        broker: Any,
        guardian: Any,
        orchestrator: Any = None,
        event_analyst: Any = None,
        nim_client: Any = None,
        journal: Any = None,
        reflector: Any = None,
    ) -> None:
        self._broker = broker
        self._guardian = guardian
        self._orchestrator = orchestrator
        self._event_analyst = event_analyst
        self._nim = nim_client
        self._journal = journal
        self._reflector = reflector
        self._start_time = time.monotonic()

        # Per-chat session memory
        self._sessions: dict[str, ChatSession] = {}

    def _get_session(self, chat_id: str) -> ChatSession:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = ChatSession()
        return self._sessions[chat_id]

    # ── Public Interface ─────────────────────────────────────────────

    async def handle_command(self, chat_id: str, command: str, args: str = "") -> str | None:
        """Route a slash command. Returns None if unrecognized → try NL."""
        cmd = command.lower().strip()

        # Block trade commands immediately — no LLM call
        if cmd in BLOCKED_COMMANDS or any(cmd.startswith(b + " ") for b in BLOCKED_COMMANDS):
            return BLOCKED_RESPONSE

        # Known command → build structured prompt, route through NL
        prompt_template = COMMAND_PROMPTS.get(cmd)
        if prompt_template:
            query = prompt_template.replace("{args}", args.strip())
            return await self.handle_natural_language(chat_id, query)

        return None  # Unknown command → bot tries NL

    async def handle_natural_language(self, chat_id: str, text: str) -> str:
        """Primary handler. All messages — commands and free text — pass through here.

        Injects live system data + session memory into the LLM context.
        The LLM generates a response using its persona while citing real numbers.
        """
        if not self._nim:
            return self._fallback_text_response(text)

        # ── Gather live system data ────────────────────────────────
        stats = await self._gather_stats()
        analysis = await self._gather_analysis_signals()

        # ── Build context injection ─────────────────────────────────
        stats_block = self._build_stats_block(stats)
        analysis_block = self._build_analysis_block(analysis)

        system_content = SYSTEM_PROMPT.format(
            stats_context=stats_block,
            analysis_context=analysis_block,
        )

        # ── Session memory ─────────────────────────────────────────
        session = self._get_session(chat_id)
        history = session.get_context()

        messages = [
            {"role": "system", "content": system_content},
            *history,
            {"role": "user", "content": text},
        ]

        # ── Call LLM ───────────────────────────────────────────────
        try:
            result = await asyncio.wait_for(
                self._nim.chat_completion(
                    messages=messages,
                    tier="fast",
                    agent_name="telegram_chat",
                    temperature=0.5,  # Slightly warmer for personality
                    max_tokens=600,
                    use_cache=False,
                ),
                timeout=20.0,
            )

            content = result.get("content", "") if isinstance(result, dict) else str(result)
            if not content or not content.strip():
                return "Hmm, I didn't catch that. Try again?"

            # ── Update session ─────────────────────────────────────
            session.add("user", text)
            session.add("assistant", content)

            return content.strip()

        except asyncio.TimeoutError:
            return "That took too long — try again?"
        except Exception as e:
            logger.error("nl_chat_error", error=str(e))
            return "Something went wrong on my end. Try again?"

    # ── Statistical Data Gatherers ───────────────────────────────────

    async def _gather_stats(self) -> dict[str, Any]:
        """Gather all live system state for LLM context injection."""
        stats: dict[str, Any] = {
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "uptime_hours": round((time.monotonic() - self._start_time) / 3600, 1),
        }

        # ── Broker ───────────────────────────────────────────────
        try:
            if hasattr(self._broker, "get_account_info"):
                account = await asyncio.to_thread(self._broker.get_account_info)
                if account:
                    stats["balance"] = float(account.get("balance", 0) or 0)
                    stats["equity"] = float(account.get("equity", 0) or 0)
                    stats["margin"] = float(account.get("margin", 0) or 0)
                    stats["margin_level"] = float(account.get("margin_level", 0) or 0)
                    stats["free_margin"] = float(account.get("free_margin", 0) or 0)
                    stats["broker_connected"] = True
                else:
                    stats["broker_connected"] = False
        except Exception:
            stats["broker_connected"] = False

        # ── Positions ────────────────────────────────────────────
        try:
            positions = []
            if hasattr(self._broker, "get_open_positions"):
                raw = await asyncio.to_thread(self._broker.get_open_positions)
                if raw:
                    for p in raw:
                        pos = self._normalize_position(p)
                        if pos:
                            positions.append(pos)
            stats["open_positions"] = positions
            stats["open_positions_count"] = len(positions)
            stats["total_pnl"] = sum(p.get("pnl", 0.0) for p in positions)
            stats["total_pnl_pips"] = sum(p.get("pnl_pips", 0.0) for p in positions)
        except Exception:
            stats["open_positions"] = []
            stats["open_positions_count"] = 0

        # ── Guardian ─────────────────────────────────────────────
        try:
            if self._guardian:
                health = await self._guardian.system_health_check()
                triggered = []
                try:
                    triggered = await self._guardian.check_all()
                except Exception:
                    pass

                stats["guardian"] = {
                    "trading_halted": health.get("trading_halted", False),
                    "halt_reason": health.get("halt_reason", ""),
                    "heartbeat_ok": health.get("heartbeat_ok", True),
                    "daily_pnl": health.get("daily_pnl", 0.0),
                    "weekly_pnl": health.get("weekly_pnl", 0.0),
                    "consecutive_losses": health.get("consecutive_losses", 0),
                    "max_consecutive_losses": health.get("max_consecutive_losses", 5),
                    "win_rate": health.get("win_rate", 0.0),
                    "total_trades": health.get("total_trades", 0),
                    "winning_trades": health.get("winning_trades", 0),
                    "triggered_switches": [
                        {"id": t["id"], "value": t.get("value", ""), "threshold": t.get("threshold", "")}
                        for t in triggered
                    ] if triggered else [],
                }
        except Exception:
            stats["guardian"] = {}
            stats["guardian_connected"] = False

        # ── Events ───────────────────────────────────────────────
        try:
            if self._event_analyst:
                blackout_status = self._event_analyst.get_blackout_status() if hasattr(self._event_analyst, "get_blackout_status") else {}
                stats["event_blackout_active"] = blackout_status.get("active_count", 0) > 0
                stats["event_blackout_count"] = blackout_status.get("active_count", 0)
                stats["event_blackouts"] = blackout_status.get("blackouts", [])[:5]

                # Also get upcoming events directly
                if hasattr(self._event_analyst, "_state"):
                    snap = getattr(self._event_analyst._state, "last_calendar_snapshot", None)
                    if snap:
                        upcoming = []
                        for ev in snap.events[:8]:
                            upcoming.append({
                                "name": ev.name,
                                "currency": ev.currency,
                                "impact": ev.impact,
                                "time_utc": ev.event_time.strftime("%Y-%m-%d %H:%M") if ev.event_time else "?",
                                "minutes_away": round(ev.minutes_away) if hasattr(ev, "minutes_away") else None,
                            })
                        stats["upcoming_events"] = upcoming
        except Exception:
            stats["event_blackout_active"] = False
            stats["event_blackout_count"] = 0

        # ── Kill-switch definitions (for /guardian) ────────────────
        try:
            if self._guardian:
                ks = getattr(self._guardian, "KILLSWITCHES", None)
                if not ks:
                    from noema.agents.guardian import GuardianAgent
                    ks = GuardianAgent.KILLSWITCHES
                triggered_ids = {t["id"] for t in (stats.get("guardian", {}).get("triggered_switches", []) or [])}
                stats["guardian_switches"] = [
                    {"id": k[0], "name": k[1], "description": k[2], "triggered": k[0] in triggered_ids}
                    for k in ks
                ]
        except Exception:
            pass

        return stats

    async def _gather_analysis_signals(self) -> dict[str, Any]:
        """Gather agent analysis signals from recent orchestrator cycles."""
        analysis: dict[str, Any] = {
            "signals": {},
            "confidences": {},
        }

        if not self._orchestrator:
            return analysis

        try:
            metrics_list = getattr(self._orchestrator, "_total_metrics", [])
            # Get the most recent cycle per symbol
            seen: set[str] = set()
            for m in reversed(metrics_list):
                symbol = getattr(m, "symbol", "")
                if symbol in seen:
                    continue
                seen.add(symbol)
                signals = getattr(m, "agent_signals", {})
                confidences = getattr(m, "agent_confidences", {})
                decision = getattr(m, "decision", "NO_TRADE")
                reasoning = getattr(m, "decision_reasoning", "")
                if signals and symbol not in analysis:
                    analysis[f"{symbol}_signals"] = signals
                    analysis[f"{symbol}_confidences"] = confidences
                    analysis[f"{symbol}_decision"] = decision
                    if reasoning:
                        analysis[f"{symbol}_reasoning"] = reasoning[:400]
                if len(seen) >= 6:
                    break
        except Exception as e:
            logger.debug("analysis_signals_fetch_failed", error=str(e))

        return analysis

    # ── Context Block Builders ───────────────────────────────────────

    def _build_stats_block(self, stats: dict[str, Any]) -> str:
        """Build the [SYSTEM DATA] block for LLM context injection.

        This is the SOURCE OF TRUTH for all numbers the LLM can cite.
        """
        lines = []

        # Timestamp
        lines.append(f"As of: {stats.get('timestamp_utc', 'unknown')}")
        lines.append(f"Uptime: {stats.get('uptime_hours', 0)}h")

        # Account
        if "balance" in stats:
            lines.append("")
            lines.append("--- ACCOUNT ---")
            lines.append(f"Balance: ${stats['balance']:,.2f}")
            lines.append(f"Equity: ${stats['equity']:,.2f}")
            lines.append(f"Margin Used: ${stats.get('margin', 0):,.2f}")
            lines.append(f"Margin Level: {stats.get('margin_level', 0):.1f}%")
            lines.append(f"Free Margin: ${stats.get('free_margin', 0):,.2f}")
            lines.append(f"Broker Connected: {stats.get('broker_connected', False)}")

        # Guardian
        guardian = stats.get("guardian", {})
        if guardian:
            lines.append("")
            lines.append("--- GUARDIAN ---")
            lines.append(f"Trading Halted: {guardian.get('trading_halted', False)}")
            if guardian.get("halt_reason"):
                lines.append(f"Halt Reason: {guardian['halt_reason']}")
            lines.append(f"Daily P&L: ${guardian.get('daily_pnl', 0.0):,.2f}")
            lines.append(f"Weekly P&L: ${guardian.get('weekly_pnl', 0.0):,.2f}")
            lines.append(f"Win Rate: {guardian.get('win_rate', 0.0):.1%} ({guardian.get('winning_trades', 0)}/{guardian.get('total_trades', 0)} trades)")
            lines.append(f"Consecutive Losses: {guardian.get('consecutive_losses', 0)} (max: {guardian.get('max_consecutive_losses', 5)})")

            triggered = guardian.get("triggered_switches", [])
            if triggered:
                lines.append(f"TRIGGERED SWITCHES: {[t['id'] for t in triggered]}")

        # Kill-switch definitions
        switches = stats.get("guardian_switches", [])
        if switches:
            lines.append("")
            lines.append("--- KILL-SWITCH STATES ---")
            for sw in switches:
                status = "TRIGGERED" if sw["triggered"] else "OK"
                lines.append(f"  [{status}] {sw['name']}: {sw.get('description', '')}")

        # Positions
        positions = stats.get("open_positions", [])
        lines.append("")
        lines.append(f"--- OPEN POSITIONS ({len(positions)}) ---")
        if positions:
            for p in positions:
                dir_short = "LONG" if p.get("direction", "").lower() in ("buy", "long") else "SHORT"
                lines.append(
                    f"  {p['symbol']} {dir_short} {p['lot']} lot(s) | "
                    f"Entry: {p['open_price']} | Current: {p['current_price']} | "
                    f"SL: {p['sl']} | TP: {p['tp']} | "
                    f"P&L: ${p.get('pnl', 0):,.2f} ({p.get('pnl_pips', 0):+.1f} pips)"
                )
            total = stats.get("total_pnl", 0.0)
            total_pips = stats.get("total_pnl_pips", 0.0)
            lines.append(f"  TOTAL: ${total:,.2f} ({total_pips:+.1f} pips)")
        else:
            lines.append("  No open positions.")

        # Events / Blackout
        if "event_blackout_active" in stats:
            lines.append("")
            lines.append("--- NEWS & EVENTS ---")
            lines.append(f"Blackout Active: {stats['event_blackout_active']}")
            blackouts = stats.get("event_blackouts", [])
            if blackouts:
                for b in blackouts:
                    lines.append(
                        f"  BLACKOUT: {b.get('event', '?')} on {b.get('pair', '?')} — "
                        f"{b.get('minutes_remaining', 0)} min remaining"
                    )

        upcoming = stats.get("upcoming_events", [])
        if upcoming:
            lines.append("  Upcoming Events:")
            for ev in upcoming:
                mins = f" ({ev['minutes_away']} min)" if ev.get("minutes_away") is not None else ""
                lines.append(f"    [{ev.get('impact', '?')}] {ev.get('name', '?')} ({ev.get('currency', '?')}) — {ev.get('time_utc', '?')}{mins}")

        return "\n".join(lines)

    def _build_analysis_block(self, analysis: dict[str, Any]) -> str:
        """Build the analysis context block from recent agent signals."""
        if not analysis or not any(k.endswith("_signals") for k in analysis):
            return "(No recent analysis cycle data available)"

        lines = []
        for key, val in sorted(analysis.items()):
            if key.endswith("_signals") and val:
                symbol = key.replace("_signals", "")
                lines.append(f"\n{symbol}:")
                lines.append(f"  Decision: {analysis.get(f'{symbol}_decision', '?')}")
                lines.append(f"  Signals: {val}")
                confs = analysis.get(f"{symbol}_confidences", {})
                if confs:
                    conf_str = ", ".join(f"{k.split('_')[0]}={v:.0%}" for k, v in confs.items())
                    lines.append(f"  Confidence: {conf_str}")
                reasoning = analysis.get(f"{symbol}_reasoning", "")
                if reasoning:
                    lines.append(f"  Reasoning: {reasoning[:300]}")

        return "\n".join(lines) if lines else "(No agent signals available)"

    # ── Fallback (no LLM available) ──────────────────────────────────

    def _fallback_text_response(self, text: str) -> str:
        """Simple rule-based fallback when LLM is unavailable."""
        text_lower = text.lower()

        if any(w in text_lower for w in ("hi", "hello", "hey", "good morning", "morning")):
            return "👋 Hey. Noema is running but LLM chat is not configured. Try /status for system info."

        if "status" in text_lower:
            return "LLM unavailable. Use /status for system info, /positions for open trades."

        if any(w in text_lower for w in ("trade", "buy", "sell", "close", "position")):
            return f"{BLOCKED_RESPONSE}\n\nUse /status, /positions, /pnl, /guardian, /events, /why SYMBOL, /exposure, or /help."

        return (
            "Noema's chat uses an LLM for natural language, but it's not configured right now. "
            "Try these commands: /status, /positions, /pnl, /guardian, /events, "
            "/why SYMBOL, /exposure, /help"
        )

    # ── Helper: normalize position objects to dicts ──────────────────

    def _normalize_position(self, p: Any) -> dict[str, Any] | None:
        """Normalize a position from broker (dict, dataclass, etc.) to a flat dict."""
        try:
            if hasattr(p, "to_dict"):
                p = p.to_dict()
            if isinstance(p, dict):
                return {
                    "symbol": p.get("symbol", ""),
                    "direction": str(p.get("type", p.get("direction", ""))),
                    "lot": float(p.get("volume", 0) or 0),
                    "open_price": float(p.get("open_price", 0) or 0),
                    "current_price": float(p.get("current_price", 0) or 0),
                    "sl": float(p.get("sl", p.get("stop_loss", 0)) or 0),
                    "tp": float(p.get("tp", p.get("take_profit", 0)) or 0),
                    "pnl": float(p.get("pnl", 0) or 0),
                    "pnl_pips": float(p.get("pnl_pips", 0) or 0),
                }
            else:
                return {
                    "symbol": str(getattr(p, "symbol", "?")),
                    "direction": str(getattr(p, "type", getattr(p, "direction", "?"))),
                    "lot": float(getattr(p, "volume", 0) or 0),
                    "open_price": float(getattr(p, "open_price", 0) or 0),
                    "current_price": float(getattr(p, "current_price", 0) or 0),
                    "sl": float(getattr(p, "sl", getattr(p, "stop_loss", 0)) or 0),
                    "tp": float(getattr(p, "tp", getattr(p, "take_profit", 0)) or 0),
                    "pnl": float(getattr(p, "pnl", 0) or 0),
                    "pnl_pips": float(getattr(p, "pnl_pips", 0) or 0),
                }
        except Exception:
            return None

    # ── Alert Methods (called by orchestrator) ───────────────────────

    async def send_broker_disconnect_alert(self, reason: str = "", duration: float = 0.0) -> str:
        return format_alert_broker_disconnect(reason, duration)

    async def send_killswitch_alert(self, switch_id: str, reason: str = "", symbol: str = "") -> str:
        return format_alert_killswitch(switch_id, reason, symbol)

    async def send_news_blackout_alert(self, event_name: str, pair: str = "", minutes: int = 0) -> str:
        return format_alert_news_blackout(event_name, pair, minutes)

    async def send_daily_summary(self) -> str:
        """Generate daily summary text."""
        daily_pnl = 0.0
        weekly_pnl = 0.0
        open_positions = 0
        total_trades = 0
        wins = 0
        guardian_ok = True
        broker_ok = False

        try:
            if hasattr(self._broker, "get_account_info"):
                account = await asyncio.to_thread(self._broker.get_account_info)
                broker_ok = bool(account)
            if hasattr(self._broker, "get_open_positions"):
                raw = await asyncio.to_thread(self._broker.get_open_positions)
                if raw:
                    open_positions = len(raw) if isinstance(raw, list) else 0
        except Exception:
            pass

        if self._guardian:
            try:
                health = await self._guardian.system_health_check()
                daily_pnl = health.get("daily_pnl", 0.0)
                weekly_pnl = health.get("weekly_pnl", 0.0)
                total_trades = health.get("total_trades", 0)
                wins = health.get("winning_trades", 0)
                guardian_ok = not health.get("trading_halted", False)
            except Exception:
                pass

        win_rate = wins / max(total_trades, 1) if total_trades > 0 else 0.0
        return format_daily_summary(
            daily_pnl=daily_pnl,
            weekly_pnl=weekly_pnl,
            open_positions=open_positions,
            total_trades=total_trades,
            win_rate=win_rate,
            guardian_ok=guardian_ok,
            broker_ok=broker_ok,
        )
