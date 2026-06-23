"""Pretty formatters for Telegram responses.

All formatting is deterministic — numbers come from the statistical layer,
not the LLM. The LLM's role is language only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def bold(text: str) -> str:
    """Telegram MarkdownV2 bold."""
    return f"*{escape_mdv2(text)}*"


def mono(text: str) -> str:
    """Telegram MarkdownV2 monospace."""
    return f"`{escape_mdv2(str(text))}`"


def escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


# ── Section Separators ───────────────────────────────────────────────


SEPARATOR = "─────────────────────────"


# ── Status Formatter ─────────────────────────────────────────────────


def format_status(
    uptime_seconds: float,
    open_positions_count: int,
    margin_pct: float,
    guardian_state: dict[str, Any],
    broker_connected: bool,
    daily_pnl: float = 0.0,
    weekly_pnl: float = 0.0,
    balance: float = 0.0,
    equity: float = 0.0,
) -> str:
    """Format /status response."""
    hours = int(uptime_seconds // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    uptime_str = f"{hours}h {minutes}m"

    guardian_status = "🟢 Active" if not guardian_state.get("trading_halted", False) else "🔴 Halted"
    halt_reason = guardian_state.get("halt_reason", "")
    broker_status = "🟢 Connected" if broker_connected else "🔴 Disconnected"

    pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
    weekly_emoji = "🟢" if weekly_pnl >= 0 else "🔴"

    lines = [
        "📊 *Noema Status*",
        SEPARATOR,
        f"⏱ Uptime: {uptime_str}",
        f"🔌 Broker: {broker_status}",
        f"🛡 Guardian: {guardian_status}",
    ]
    if halt_reason:
        lines.append(f"  └ Reason: _{escape_mdv2(halt_reason)}_")

    lines.extend([
        SEPARATOR,
        f"💰 Balance: ${balance:,.2f}",
        f"   Equity: ${equity:,.2f}",
        f"   Margin: {margin_pct:.1f}%",
        SEPARATOR,
        f"{pnl_emoji} Daily P&L: ${daily_pnl:,.2f}",
        f"{weekly_emoji} Weekly P&L: ${weekly_pnl:,.2f}",
        SEPARATOR,
        f"📈 Open Positions: {open_positions_count}",
    ])

    return "\n".join(lines)


# ── Positions Formatter ──────────────────────────────────────────────


def format_positions(positions: list[dict[str, Any]]) -> str:
    """Format /positions response."""
    if not positions:
        return "📋 *Open Positions*\n" + SEPARATOR + "\nNo open positions."

    total_pnl = sum(p.get("pnl", 0.0) for p in positions)
    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

    lines = [
        f"📋 *Open Positions* ({len(positions)})",
        SEPARATOR,
    ]

    for p in positions:
        symbol = p.get("symbol", "?")
        direction = p.get("direction", "?").upper()
        dir_emoji = "🟢" if direction == "BUY" else "🔴"
        entry = p.get("open_price", 0)
        current = p.get("current_price", 0)
        sl = p.get("stop_loss", 0)
        tp = p.get("take_profit", 0)
        pnl = p.get("pnl", 0.0)
        lot = p.get("volume", 0.0)
        pnl_item = "🟢" if pnl >= 0 else "🔴"

        lines.append(
            f"{dir_emoji} *{escape_mdv2(symbol)}* {direction} {lot} lots"
        )
        lines.append(f"   Entry: {escape_mdv2(str(entry))}  |  SL: {escape_mdv2(str(sl))}  |  TP: {escape_mdv2(str(tp))}")
        lines.append(f"   {pnl_item} P&L: ${pnl:,.2f}")

    lines.extend([
        SEPARATOR,
        f"Total P&L: {pnl_emoji} ${total_pnl:,.2f}",
    ])

    return "\n".join(lines)


# ── P&L Formatter ────────────────────────────────────────────────────


def format_pnl(
    daily_pnl: float = 0.0,
    weekly_pnl: float = 0.0,
    monthly_pnl: float = 0.0,
    total_trades_today: int = 0,
    total_trades_week: int = 0,
    total_trades_month: int = 0,
    win_rate_today: float = 0.0,
    win_rate_week: float = 0.0,
    win_rate_month: float = 0.0,
) -> str:
    """Format /pnl response."""
    d_emoji = "🟢" if daily_pnl >= 0 else "🔴"
    w_emoji = "🟢" if weekly_pnl >= 0 else "🔴"
    m_emoji = "🟢" if monthly_pnl >= 0 else "🔴"

    lines = [
        "📈 *P&L Summary*",
        SEPARATOR,
        f"{d_emoji} *Daily*: ${daily_pnl:,.2f}  ({total_trades_today} trades, {win_rate_today:.0%} WR)",
        f"{w_emoji} *Weekly*: ${weekly_pnl:,.2f}  ({total_trades_week} trades, {win_rate_week:.0%} WR)",
        f"{m_emoji} *Monthly*: ${monthly_pnl:,.2f}  ({total_trades_month} trades, {win_rate_month:.0%} WR)",
    ]

    return "\n".join(lines)


# ── Guardian Formatter ───────────────────────────────────────────────


def format_guardian(switches: list[dict[str, Any]], guardian_state: dict[str, Any]) -> str:
    """Format /guardian response showing all kill-switch states."""
    triggered_ids = {s["id"] for s in (guardian_state.get("triggered_switches", []) or [])}

    lines = [
        "🛡 *Guardian Kill-Switches*",
        SEPARATOR,
    ]

    for sw in switches:
        sw_id = sw.get("id", "?")
        name = sw.get("name", sw_id)
        is_ok = sw_id not in triggered_ids
        status_emoji = "🟢" if is_ok else "🔴"
        status_text = "OK" if is_ok else "TRIGGERED"

        lines.append(f"{status_emoji} *{escape_mdv2(name)}* — {status_text}")

    # Summary
    triggered_count = len(triggered_ids)
    summary = "All systems clear ✅" if triggered_count == 0 else f"{triggered_count} switch(es) triggered ⚠️"

    lines.extend([
        SEPARATOR,
        summary,
    ])

    return "\n".join(lines)


# ── Events Formatter ─────────────────────────────────────────────────


def format_events(
    upcoming_events: list[dict[str, Any]],
    blackout_active: bool = False,
    blackout_details: list[dict[str, Any]] | None = None,
) -> str:
    """Format /events response."""
    blackout_status = "🔴 ACTIVE" if blackout_active else "🟢 CLEAR"
    blackout_emoji = "🔴" if blackout_active else "🟢"

    lines = [
        "📅 *Economic Events*",
        SEPARATOR,
        f"{blackout_emoji} Blackout: {blackout_status}",
    ]

    if blackout_active and blackout_details:
        for detail in blackout_details:
            event_name = detail.get("event", "Unknown")
            pair = detail.get("pair", "")
            minutes = detail.get("minutes_remaining", 0)
            lines.append(f"  ⏳ {escape_mdv2(event_name)} ({escape_mdv2(pair)}) — {minutes} min remaining")

    if upcoming_events:
        lines.append(SEPARATOR)
        lines.append("*Upcoming Events:*")
        for ev in upcoming_events[:10]:  # Show max 10
            name = ev.get("name", "Unknown")
            currency = ev.get("currency", "")
            time_str = ev.get("time", "")
            impact = ev.get("impact", "").upper()
            impact_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(impact, "⚪")
            lines.append(f"  {impact_emoji} {escape_mdv2(name)} ({escape_mdv2(currency)}) — {escape_mdv2(time_str)}")
    else:
        lines.append(SEPARATOR)
        lines.append("No upcoming high-impact events.")

    return "\n".join(lines)


# ── Why Formatter ────────────────────────────────────────────────────


def format_why(
    symbol: str,
    analysis_signals: dict[str, str],
    analysis_confidence: dict[str, float],
    decision_reasoning: str = "",
    current_price: float = 0.0,
    entry_price: float = 0.0,
    pnl_pips: float = 0.0,
) -> str:
    """Format /why SYMBOL response."""
    lines = [
        f"🔍 *Why {escape_mdv2(symbol)}?*",
        SEPARATOR,
        "📊 *Statistical Signals:*",
    ]

    for agent, signal in analysis_signals.items():
        conf = analysis_confidence.get(agent, 0.0) * 100
        signal_emoji = {
            "BULLISH": "🟢", "BUY": "🟢",
            "BEARISH": "🔴", "SELL": "🔴",
            "NEUTRAL": "⚪", "NO_TRADE": "⚪",
            "APPROVE": "🟢", "REJECT": "🔴",
        }.get(signal.upper(), "⚪")
        agent_short = agent.replace("_", " ").title()
        lines.append(f"  {signal_emoji} {escape_mdv2(agent_short)}: {escape_mdv2(signal)} ({conf:.0f}%)")

    if current_price:
        lines.append(SEPARATOR)
        lines.append(f"💰 Current: {current_price:.5f}")
        if entry_price:
            lines.append(f"   Entry: {entry_price:.5f} ({pnl_pips:+.1f} pips)")

    if decision_reasoning:
        lines.append(SEPARATOR)
        lines.append(f"💬 *Analysis:*")
        # Truncate long reasoning
        max_len = 800
        reason = decision_reasoning[:max_len]
        if len(decision_reasoning) > max_len:
            reason += "..."
        lines.append(reason)

    return "\n".join(lines)


# ── Exposure Formatter ───────────────────────────────────────────────


def format_exposure(
    positions: list[dict[str, Any]],
    balance: float = 0.0,
    equity: float = 0.0,
    margin_used: float = 0.0,
) -> str:
    """Format /exposure response."""
    if not positions:
        return (
            "📊 *Net Exposure*\n"
            + SEPARATOR + "\n"
            "No open positions."
        )

    # Aggregate by currency
    currency_exposure: dict[str, float] = {}
    for p in positions:
        symbol = p.get("symbol", "")
        if len(symbol) >= 6:
            base = symbol[:3]
            quote = symbol[3:6]
            direction = p.get("direction", "").lower()
            lot = p.get("volume", 0.0)

            if direction == "buy":
                currency_exposure[base] = currency_exposure.get(base, 0.0) + lot
                currency_exposure[quote] = currency_exposure.get(quote, 0.0) - lot
            else:
                currency_exposure[base] = currency_exposure.get(base, 0.0) - lot
                currency_exposure[quote] = currency_exposure.get(quote, 0.0) + lot

    total_risk = margin_used / equity * 100 if equity > 0 else 0.0

    lines = [
        "📊 *Net Exposure*",
        SEPARATOR,
    ]

    for currency, exposure in sorted(currency_exposure.items(), key=lambda x: abs(x[1]), reverse=True):
        if abs(exposure) < 0.001:
            continue
        emoji = "🟢" if exposure >= 0 else "🔴"
        lines.append(f"  {emoji} {currency}: {exposure:+.2f} lots")

    lines.extend([
        SEPARATOR,
        f"💰 Balance: ${balance:,.2f}",
        f"   Equity: ${equity:,.2f}",
        f"   Margin Used: ${margin_used:,.2f} ({total_risk:.1f}% risk)",
        f"   Open Positions: {len(positions)}",
    ])

    return "\n".join(lines)


# ── Help Formatter ───────────────────────────────────────────────────


def format_help() -> str:
    """Format /help response."""
    commands = [
        ("/status", "Uptime, positions, margin%, Guardian status"),
        ("/positions", "All open positions with entry/SL/TP/P&L"),
        ("/pnl", "Daily, weekly, monthly P&L summary"),
        ("/guardian", "All kill-switch states"),
        ("/events", "Upcoming economic events, blackout status"),
        ("/why SYMBOL", "Statistical basis for a trade (e.g. /why EURUSD)"),
        ("/exposure", "Net exposure by currency, total risk"),
        ("/help", "This help message"),
    ]

    lines = [
        "🤖 *Noema Telegram Commands*",
        SEPARATOR,
    ]

    for cmd, desc in commands:
        lines.append(f"  {mono(cmd)} — {escape_mdv2(desc)}")

    lines.extend([
        SEPARATOR,
        "_💬 You can also ask natural language questions\\!_",
        "_Example: \"How is EURUSD doing?\" or \"What\\'s my risk?\"_",
        SEPARATOR,
        "⚠️ *Trading via chat is disabled by Guardian policy\\.",
        "  Use the dashboard for administrative actions.*",
    ])
    return "\n".join(lines)


# ── Natural Language Response Formatter ──────────────────────────────


def format_nl_response(
    stats_section: str,
    analysis_section: str,
) -> str:
    """Format a natural language response with clear statistical vs analysis labeling.

    Args:
        stats_section: Pre-formatted statistical data (numbers from the system)
        analysis_section: LLM-generated natural language analysis
    """
    lines = [
        "📊 *Statistical*",
        stats_section,
        "",
        "💬 *Analysis*",
        analysis_section,
        "",
        "_⚠️ Numbers above are from the statistical layer\\. Analysis is LLM\\-generated for language only\\._",
    ]
    return "\n".join(lines)


# ── Alert Formatters ─────────────────────────────────────────────────


def format_alert_broker_disconnect(reason: str = "", duration_seconds: float = 0.0) -> str:
    """Format broker disconnect alert."""
    duration_str = f" ({duration_seconds:.0f}s)" if duration_seconds > 0 else ""
    lines = [
        "🚨 *BROKER DISCONNECTED*",
        SEPARATOR,
        f"Broker connection lost{duration_str}",
    ]
    if reason:
        lines.append(f"Reason: {escape_mdv2(reason)}")
    lines.extend([
        SEPARATOR,
        "⚠️ Guardian will halt trading after 30s timeout.",
    ])
    return "\n".join(lines)


def format_alert_killswitch(kill_switch_id: str, reason: str = "", symbol: str = "") -> str:
    """Format kill-switch trigger alert."""
    name = kill_switch_id.replace("_", " ").title()
    lines = [
        f"🛡 *KILL-SWITCH: {escape_mdv2(name)}*",
        SEPARATOR,
    ]
    if symbol:
        lines.append(f"Symbol: {escape_mdv2(symbol)}")
    if reason:
        lines.append(f"Reason: {escape_mdv2(reason)}")
    lines.extend([
        SEPARATOR,
        "⚠️ Trading has been halted. Check the dashboard for details.",
    ])
    return "\n".join(lines)


def format_alert_news_blackout(event_name: str, pair: str = "", minutes: int = 0) -> str:
    """Format news blackout alert."""
    lines = [
        f"📰 *News Blackout Active*",
        SEPARATOR,
        f"Event: {escape_mdv2(event_name)}",
    ]
    if pair:
        lines.append(f"Pair: {escape_mdv2(pair)}")
    if minutes:
        lines.append(f"Duration: {minutes} min window")
    lines.extend([
        SEPARATOR,
        "⚠️ New trades suspended until event window passes.",
    ])
    return "\n".join(lines)


def format_daily_summary(
    daily_pnl: float,
    weekly_pnl: float,
    open_positions: int,
    total_trades: int,
    win_rate: float,
    guardian_ok: bool,
    broker_ok: bool,
) -> str:
    """Format daily summary message."""
    pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
    guardian_status = "🟢 OK" if guardian_ok else "🔴 TRIGGERED"
    broker_status = "🟢 Connected" if broker_ok else "🔴 Disconnected"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"📊 *Noema Daily Summary — {escape_mdv2(now)}*",
        SEPARATOR,
        f"{pnl_emoji} Daily P&L: ${daily_pnl:,.2f}",
        f"   Weekly P&L: ${weekly_pnl:,.2f}",
        f"   Trades Today: {total_trades}",
        f"   Win Rate: {win_rate:.0%}",
        SEPARATOR,
        f"🛡 Guardian: {guardian_status}",
        f"🔌 Broker: {broker_status}",
        f"📈 Open Positions: {open_positions}",
        SEPARATOR,
        "_Use /status for live details._",
    ]
    return "\n".join(lines)
