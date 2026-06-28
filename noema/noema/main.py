"""Noema Main — Modern Agentic Trading System.

Uses the wave-based parallel orchestrator:
- Layer 1: Data agents (parallel, deterministic)
- Layer 2: Analysis agents (parallel, deterministic + LLM)
- Layer 3: Decision agents (sequential LLM debate)
- Layer 4: Execution (deterministic)
- Layer 5: Learning (background LLM reflection)
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Any

import structlog

from noema.core.settings import Settings, load_settings
from noema.core.platform import detect_platform, get_broker_class
from noema.core.nim_client import NIMClient, ModelTier
from noema.core.orchestrator_modern import ModernOrchestrator
from noema.core.metrics import MetricsCollector
from noema.core.metrics_exporter import MetricsExporter
from noema.core.health import HealthChecker
from noema.core.storage import TradeStore, RedisCache
from noema.core.observability import init_observability

# Phase 6: Production Hardening
from noema.core.logging_config import configure_logging as _configure_logging
from noema.core.config_validator import validate_config, format_validation_errors
from noema.core.shutdown import (
    ShutdownManager,
    ShutdownConfig,
    ShutdownPositionPolicy,
    load_shutdown_config_from_env,
)


# Self-learning + journaling + Telegram
from noema.agents.reflector import ReflectorAgent
from noema.database.journal import TradeJournal
from noema.telegram.bot import NoemaTelegramBot
from noema.telegram.handlers import CommandHandlers

# Agent Registry — auto-discovers agents via @AgentRegistry.register decorators
from noema.core.registry import AgentRegistry

# Guardian Agent — kill-switches wired into pipeline
from noema.agents.guardian import GuardianAgent, GuardianState

# Broker — auto-detected based on platform
from noema.core.platform import detect_platform, get_broker_class

logger = structlog.get_logger(__name__)


# ── Companion Services ───────────────────────────────────────────────


class CompanionServices:
    """ReflectorAgent + TradeJournal + Telegram — companion services
    that sit alongside the ModernOrchestrator and provide self-learning,
    trade journaling, and Telegram control surface."""

    def __init__(self) -> None:
        self.reflector = ReflectorAgent()
        self.journal = TradeJournal()
        self.telegram: NoemaTelegramBot | None = None
        self.telegram_handlers: CommandHandlers | None = None

    def record_trade(
        self,
        pair: str,
        decision: str,
        context: dict[str, Any],
        agent_reports: dict[str, dict],
    ) -> None:
        """Record an executed trade for self-learning and journaling."""
        try:
            trade_record = {
                "symbol": pair,
                "direction": "buy" if decision == "BUY" else "sell",
                "pnl": 0.0,
                "session": context.get("session", "unknown"),
                "market_regime": "unknown",
                "trend": context.get("trend", "unknown"),
                "confidence": agent_reports.get("thesis", {}).get("confidence", 0),
                "confluence_score": sum(
                    r.get("confidence", 0) for r in agent_reports.values()
                ) / max(len(agent_reports), 1),
                "exit_reason": "open",
                "agent_reports": agent_reports,
            }
            self.reflector.record_trade(trade_record)

            self.journal.record_trade(
                ticket=0,
                symbol=pair,
                direction="buy" if decision == "BUY" else "sell",
                entry_price=context.get("current_price", 0),
                exit_price=0,
                volume=context.get("lot_size", 0.01),
                sl=context.get("stop_loss", 0),
                tp=context.get("take_profit", 0),
                pnl=0,
                pnl_pips=0,
                entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc),
                exit_reason="open",
                session="unknown",
                settings_hash=self.journal.compute_config_hash({}),
                git_sha="",
                agent_reports=agent_reports,
            )
        except Exception as exc:
            logger.error("trade_recording_failed", error=str(exc))

    def get_learned_params(self) -> dict[str, Any]:
        """Get ReflectorAgent's adapted parameters."""
        return self.reflector.get_adapted_params()

    async def start(self) -> None:
        """Start Telegram bot."""
        adapted = self.reflector.get_adapted_params()
        if adapted.get("lessons"):
            logger.info(f"Loaded {len(adapted['lessons'])} lessons from ReflectorAgent")
        if self.telegram:
            await self.telegram.start()

    async def stop(self) -> None:
        """Stop Telegram bot and close journal."""
        if self.telegram:
            await self.telegram.stop()
        self.journal.close()


# ── Telegram Command Handlers (wired to CompanionServices) ──────────


def _build_telegram_bot(services: CompanionServices, broker: Any, orchestrator: ModernOrchestrator, nim_client: NIMClient, event_analyst: Any = None, settings: Any = None) -> NoemaTelegramBot:
    """Build the new NoemaTelegramBot with command handlers wired to system data."""
    handlers = CommandHandlers(
        broker=broker,
        guardian=orchestrator.guardian if orchestrator else None,
        orchestrator=orchestrator,
        event_analyst=event_analyst,
        nim_client=nim_client,
        journal=services.journal,
        reflector=services.reflector,
    )

    bot = NoemaTelegramBot(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        handlers=handlers,
        nim_client=nim_client,
    )

    services.telegram = bot
    services.telegram_handlers = handlers

    # Wire handlers into orchestrator for alert push
    if orchestrator:
        orchestrator.set_telegram_handlers(handlers)

    return bot


# ── Orchestrator Factory ────────────────────────────────────────────


async def ensure_mt5_running(settings: Settings) -> bool:
    """Ensure MT5 is running before the orchestrator starts.

    If Noema_MT5_HEADLESS=true in .env, auto-start MT5 headless.
    Otherwise, warn the user that MT5 needs to be started manually.

    Returns:
        True if MT5 is ready (or not needed), False if MT5 is required but unavailable
    """
    from noema.scripts.mt5_daemon import (
        is_mt5_running,
        start_mt5,
        wait_for_mt5_ready,
        generate_config,
        load_credentials_from_env,
    )
    from noema.scripts.start_mt5 import setup_mt5linux_ea, _find_mt5linux_ea

    # ── Pre-flight: mt5linux EA check ───────────────────────────
    ea_path = _find_mt5linux_ea()
    if ea_path and not ea_path.exists():
        logger.warning(
            "mt5linux_ea_missing_preflight",
            path=str(ea_path),
            hint="The Expert Advisor must be in MT5's Experts dir for the RPyC bridge.",
        )
        if setup_mt5linux_ea():
            logger.info("mt5linux_ea_auto_installed")
        else:
            logger.error(
                "mt5linux_ea_install_failed",
                fix=(
                    "Run: python -m noema.scripts.mt5_daemon setup-mt5-ea\n"
                    "Or: noema setup-mt5-ea"
                ),
            )

    status = is_mt5_running()

    if status["rpyc_listening"]:
        logger.info("mt5_already_running")
        return True

    headless = os.getenv("Noema_MT5_HEADLESS", "true").lower() in ("true", "1", "yes")
    startup_wait = int(os.getenv("Noema_MT5_STARTUP_WAIT", "120"))

    if headless:
        logger.info("mt5_auto_starting", headless=True)
        try:
            login, password, server = load_credentials_from_env()
            config_path = generate_config(login, password, server)
            process = start_mt5(config_path=config_path, headless=True)
            if process is None:
                logger.error("mt5_auto_start_failed")
                return False
            logger.info("mt5_process_started", pid=process.pid)
            ready = wait_for_mt5_ready(timeout=startup_wait)
            if ready:
                logger.info("mt5_auto_start_ready")
                return True
            else:
                logger.error(
                    "mt5_auto_start_timeout",
                    timeout=startup_wait,
                    hint="python -m noema.scripts.mt5_daemon start",
                )
                return False
        except ValueError as exc:
            logger.error("mt5_credentials_missing", error=str(exc))
            return False
    else:
        logger.warning(
            "mt5_not_running_headless_disabled",
            hint=(
                "MT5 is not running. Start it manually with:\n"
                "  python -m noema.scripts.mt5_daemon start\n"
                "Or set Noema_MT5_HEADLESS=true in .env for auto-start."
            ),
        )
        # Don't block — MT5 might be started externally
        return True


async def create_orchestrator(
    settings: Settings,
) -> tuple[ModernOrchestrator, CompanionServices]:
    """Build and configure the modern orchestrator with companion services.

    Returns (orchestrator, services) — the orchestrator runs the wave-based
    pipeline, while services provides self-learning, journaling, and Telegram.
    """

    # ── NIM Client ───────────────────────────────────────────────────
    api_key = settings.nim.api_key or os.getenv("NIM_API_KEY", "")
    if not api_key:
        logger.warning("NIM_API_KEY not set — LLM agents will use fallback logic")

    tier_map = {
        "fast": ModelTier.FAST,
        "standard": ModelTier.STANDARD,
        "heavy": ModelTier.HEAVY,
    }
    nim = NIMClient(
        api_key=api_key,
        base_url=settings.nim.base_url,
        default_tier=tier_map.get(settings.nim.default_tier, ModelTier.STANDARD),
        cache_ttl=settings.nim.cache_ttl,
        cache_enabled=settings.nim.cache_enabled,
        max_retries=settings.nim.max_retries,
        rpm_limit=settings.nim.rpm_limit,
    )

    # ── Broker (auto-detected from platform) ─────────────────────────
    platform_info = detect_platform()
    BrokerClass = get_broker_class(platform_info)
    broker = BrokerClass(settings)
    
    logger.info(
        "platform_detected",
        system=platform_info.system,
        broker=platform_info.recommended_broker,
        has_wine=platform_info.has_wine,
        has_mt5=platform_info.has_mt5,
    )

    # ── Storage ──────────────────────────────────────────────────────
    trade_store = None
    redis_cache = None

    if settings.database_url.startswith("postgresql"):
        trade_store = TradeStore(settings.database_url)
        await trade_store.initialize()

    redis_url = settings.redis_url or os.getenv("REDIS_URL", "")
    if redis_url:
        redis_cache = RedisCache(redis_url)
        await redis_cache.initialize()

    # ── Metrics ──────────────────────────────────────────────────────
    metrics = MetricsCollector(enabled=True)
    metrics.set_system_info(
        version="2.0.0",
        pairs=settings.trading.pairs,
    )

    # ── Observability ───────────────────────────────────────────────
    metrics_exporter = MetricsExporter(enabled=True)
    health_checker = HealthChecker()

    # ── Companion Services ───────────────────────────────────────────
    services = CompanionServices()

    # ── Guardian Kill-Switches ──────────────────────────────────────
    guardian_state = GuardianState(
        daily_loss_limit_pct=settings.risk.max_daily_loss * 100,
        weekly_loss_limit=settings.risk.max_weekly_loss * 100,
        max_lot_size=settings.risk.max_lot_size,
    )
    guardian = GuardianAgent(config=settings, guardian_state=guardian_state)

    # ── Event Analyst (Phase 1.5) ───────────────────────────────────
    event_analyst = None
    try:
        from noema.agents.event_analyst import EventAnalyst, EventAnalystState
        event_state = EventAnalystState()
        event_analyst = EventAnalyst(
            config=settings,
            guardian_agent=guardian,
            blackout_minutes=settings.event.blackout_minutes,
            high_impact_only=settings.event.high_impact_only,
            max_blackout_minutes=settings.event.max_blackout_minutes,
        )
    except ImportError:
        logger.debug("event_analyst_not_available")

    # ── Orchestrator ─────────────────────────────────────────────────
    orch = ModernOrchestrator(
        nim_client=nim,
        broker=broker,
        config=settings,
        guardian=guardian,
        guardian_state=guardian_state,
        metrics_exporter=metrics_exporter,
        health_checker=health_checker,
        event_analyst=event_analyst,
    )

    # ── Discover & Create Agents via Registry ─────────────────────
    # Agents self-register via @AgentRegistry.register decorators.
    # Import all agent modules to trigger registration.
    AgentRegistry.discover_agents("noema.agents")
    agents = AgentRegistry.create_all(config=settings, nim_client=nim, broker=broker)

    # Register agents with orchestrator by layer
    orch.register_data_agents(agents["data"])
    orch.register_analysis_agents(agents["analysis"])

    decision = agents["decision"]
    orch.register_decision_agents(
        thesis=decision["thesis"],
        devil=decision["devil"],
        cio=decision["cio"],
    )

    execution = agents["execution"]
    orch.register_execution_agents(
        risk=execution["risk"],
        execution=execution["execution"],
    )

    # Learning agent (single item in list)
    if agents["learning"]:
        orch.register_learning_agent(agents["learning"][0])

    # Wire Telegram handlers
    bot = _build_telegram_bot(
        services=services,
        broker=broker,
        orchestrator=orch,
        nim_client=nim,
        event_analyst=event_analyst,
        settings=settings,
    )

    # Wire Telegram bot into orchestrator for alert push
    orch._telegram_bot = bot

    return orch, services


# ── CLI Entry Point ──────────────────────────────────────────────────


async def main() -> None:
    """Noema entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Noema")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--interval", type=float, default=60.0, help="Cycle interval in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Use paper broker")
    parser.add_argument(
        "--mode", type=str, default="demo", choices=["demo", "live"],
        help="Trading mode: demo or live (real money). Default: demo",
    )
    parser.add_argument(
        "--capital", type=float, default=None,
        help="Starting capital in USD. <$100 enables micro mode with 0.01 lots",
    )
    parser.add_argument(
        "--broker-name", type=str, default=None,
        help="Broker name for display (e.g., FxPesa, FBS, IC Markets)",
    )
    parser.add_argument(
        "--broker-server", type=str, default=None,
        help="MT5 server name override (e.g., FxPesa-Demo, FBS-Real)",
    )
    parser.add_argument(
        "--mt5-auto", action="store_true",
        help="Auto-start MT5 headless daemon before trading",
    )
    parser.add_argument(
        "--no-mt5-auto", action="store_true",
        help="Skip MT5 auto-start even if configured",
    )
    parser.add_argument(
        "--no-validate", action="store_true",
        help="Skip configuration validation on startup",
    )
    parser.add_argument(
        "--first-run", action="store_true",
        help="Enforce first-run micro-lot safety cap (0.01 lots)",
    )
    args = parser.parse_args()

    # Load config
    settings = load_settings()
    if args.dry_run:
        settings.broker.type = "paper"
    
    # ── LIVE MODE SAFETY: Enforce MT5 broker + demo account ──────
    if args.mode == "live":
        # Force MT5 broker — never paper in live mode
        os.environ["NOEMA_BROKER"] = "mt5_linux"
        settings.broker.type = "mt5_linux"
        
        # Enforce first-run micro-lot if flag set
        if args.first_run:
            os.environ["Noema_FIRST_RUN"] = "true"
            os.environ.setdefault("Noema_MAX_LOT_SIZE", "0.01")
            settings.risk.max_lot_size = 0.01
            logger.info("first_run_micro_lot_enforced", max_lot=0.01)

    # ── Mode configuration ──────────────────────────────────
    from noema.core.mode_config import ModeConfig, MicroPositionSizer
    
    trading_mode = args.mode or "demo"
    starting_capital = args.capital
    if starting_capital is None:
        starting_capital = float(os.getenv("Noema_STARTING_CAPITAL", "0"))
    if starting_capital <= 0:
        starting_capital = 10.0  # Default $10 micro
    
    mode_config = ModeConfig(mode=trading_mode, capital=starting_capital)
    micro_sizer = MicroPositionSizer.for_capital(starting_capital)
    
    # Override broker server if provided
    if args.broker_server:
        os.environ["Noema_MT5_SERVER"] = args.broker_server
        settings.broker.mt5_server = args.broker_server
    if args.broker_name:
        os.environ["Noema_BROKER_NAME"] = args.broker_name
    
    # Live mode: extra warning banner
    if trading_mode == "live":
        logger.warning(
            "live_mode_active",
            capital=starting_capital,
            risk_per_trade=micro_sizer.get_risk_limits()["risk_per_trade_amount"],
        )

    # ── Phase 6: Configure structured logging ────────────────────────
    _configure_logging(
        level=settings.log_level,
        environment="production" if not args.dry_run else "development",
        json_format=os.getenv("NOEMA_LOG_JSON", "false").lower() == "true",
        log_to_file=os.getenv("NOEMA_LOG_TO_FILE", "false").lower() == "true",
        enable_request_id=True,
        redact_secrets=True,
    )

    logger.info("noema_starting", version="2.0.0", pairs=settings.trading.pairs)

    # ── Phase 6: Validate configuration before startup ───────────────
    if not args.no_validate:
        mode = "development" if args.dry_run else "production"
        result = validate_config(settings, env_file=".env", mode=mode)
        if not result.is_valid:
            # Print formatted errors to stderr for visibility
            print(format_validation_errors(result), file=sys.stderr)
            logger.critical("startup_aborted", reason="config_validation_failed")
            sys.exit(1)
        if result.warnings:
            for w in result.warnings:
                logger.warning("config_warning", field=w.field, message=w.message)
        logger.info("config_validation_passed")

    # ── MT5 Lifecycle ───────────────────────────────────────────────
    if args.mt5_auto:
        os.environ["Noema_MT5_HEADLESS"] = "true"
    elif args.no_mt5_auto:
        os.environ["Noema_MT5_HEADLESS"] = "false"

    if not args.dry_run:
        mt5_ready = await ensure_mt5_running(settings)
        if not mt5_ready:
            logger.error(
                "mt5_unavailable_exiting",
                hint="Start MT5 manually: python -m noema.scripts.mt5_daemon start",
            )
            sys.exit(1)
        
        # ── DEMO ACCOUNT VERIFICATION (live mode) ─────────────────
        if args.mode == "live":
            from noema.scripts.check_demo import verify_demo_account
            is_demo, server_name = verify_demo_account()
            if not is_demo:
                logger.critical(
                    "live_trading_blocked_not_demo",
                    server=server_name,
                    reason="Server name does not contain 'Demo' — REAL MONEY PROTECTION",
                )
                print(f"\n❌ LIVE TRADING BLOCKED!")
                print(f"   Server: {server_name}")
                print(f"   This does NOT appear to be a demo account.")
                print(f"   Noema will NEVER trade real money without explicit approval.\n")
                sys.exit(1)
            logger.info("demo_account_verified", server=server_name)
            print(f"✅ Demo account verified: {server_name}")

    # ── Initialize Observability ────────────────────────────────────
    init_observability(
        service_name="noema",
        environment="production" if not args.dry_run else "development",
        enabled=True,
    )

    # Create orchestrator + services
    orch, services = await create_orchestrator(settings)
    
    # Wire mode config into orchestrator
    orch.mode_config = mode_config
    orch.micro_sizer = micro_sizer

    # ── Phase 6: Graceful Shutdown Manager ───────────────────────────
    shutdown_config = load_shutdown_config_from_env()
    shutdown_mgr = ShutdownManager(
        orchestrator=orch,
        companion=services,
        broker=orch.broker if hasattr(orch, "broker") else None,
        health_checker=HealthChecker(),
        metrics_collector=MetricsCollector(enabled=True),
        trade_store=getattr(orch, "_trade_store", None),
        config=shutdown_config,
    )
    shutdown_mgr.register_signal_handlers()

    # Start companion services (Telegram, journal, reflector)
    await services.start()

    # Start orchestrator
    await orch.start(interval=args.interval)

    # ── Wait for graceful shutdown ───────────────────────────────────
    exit_code = await shutdown_mgr.wait_for_shutdown()

    # Perform final cleanup if shutdown wasn't already triggered
    if not shutdown_mgr.state.initiated:
        logger.info("noema_shutting_down")
        await orch.stop()
        await services.stop()

    logger.info("noema_stopped", exit_code=exit_code)
    shutdown_mgr.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
