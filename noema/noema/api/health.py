"""
Noema Health API — FastAPI HTTP endpoints for health, readiness, and metrics.

Provides:
- GET /health          — Basic liveness check (Kubernetes liveness probe)
- GET /health/ready    — Readiness check (all components initialized)
- GET /health/detailed — Per-component status with full diagnostics
- GET /metrics         — Prometheus metrics endpoint
- POST /shutdown       — Trigger graceful shutdown (protected)

Usage:
    from noema.api.health import create_health_app
    app = create_health_app(health_checker, metrics_collector, shutdown_manager)

    # Run with uvicorn
    uvicorn noema.api.health:app --host 0.0.0.0 --port 8000

Integration with main.py:
    The health app binds to the same HealthChecker and MetricsCollector
    that the orchestrator uses, providing real-time system visibility.
"""

from __future__ import annotations

import os
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════
# FastAPI Application Factory
# ═══════════════════════════════════════════════════

def create_health_app(
    health_checker: Any = None,
    metrics_collector: Any = None,
    shutdown_manager: Any = None,
    orchestrator: Any = None,
    broker: Any = None,
    settings: Any = None,
    companion_services: Any = None,
    redis_cache: Any = None,
    trade_store: Any = None,
) -> Any:
    """Create a FastAPI application with health and metrics endpoints.

    Args:
        health_checker: HealthChecker instance from noema.core.health
        metrics_collector: MetricsCollector from noema.core.metrics
        shutdown_manager: ShutdownManager from noema.core.shutdown
        orchestrator: ModernOrchestrator instance
        broker: Broker instance
        settings: Settings instance
        companion_services: CompanionServices instance
        redis_cache: RedisCache instance
        trade_store: TradeStore instance

    Returns:
        FastAPI application ready to serve.
    """
    try:
        from fastapi import FastAPI, HTTPException, Request, status
        from fastapi.responses import JSONResponse, PlainTextResponse, Response
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        logger.error("fastapi_not_installed", hint="pip install fastapi uvicorn")
        raise

    app = FastAPI(
        title="Noema Health API",
        version="2.0.0",
        docs_url="/docs" if os.getenv("NOEMA_API_DOCS", "false").lower() == "true" else None,
        redoc_url=None,
    )

    # CORS — allow dashboard access
    cors_origins = os.getenv("Noema_CORS_ORIGIN", "http://localhost:3000").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins if o.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # Store references in app.state
    app.state.health_checker = health_checker
    app.state.metrics_collector = metrics_collector
    app.state.shutdown_manager = shutdown_manager
    app.state.orchestrator = orchestrator
    app.state.broker = broker
    app.state.settings = settings
    app.state.companion_services = companion_services
    app.state.redis_cache = redis_cache
    app.state.trade_store = trade_store
    app.state._start_time = time.time()

    # ═══════════════════════════════════════════════
    # GET /health — Basic Liveness
    # ═══════════════════════════════════════════════

    @app.get("/health")
    async def health_liveness(request: Request) -> Response:
        """Basic liveness check — faster than reading a heartbeat.

        Returns 200 if the process is alive and responding.
        Used by Kubernetes liveness probes and load balancers.
        """
        return JSONResponse(
            content={
                "status": "alive",
                "service": "noema",
                "version": "2.0.0",
                "timestamp": time.time(),
                "uptime_seconds": round(time.time() - request.app.state._start_time, 1),
            },
            status_code=200,
        )

    # ═══════════════════════════════════════════════
    # GET /health/ready — Readiness Check
    # ═══════════════════════════════════════════════

    @app.get("/health/ready")
    async def health_readiness(request: Request) -> Response:
        """Readiness check — verifies all components are initialized.

        Returns 200 if all required components are ready.
        Returns 503 if any required component is not initialized.

        Used by Kubernetes readiness probes to control traffic routing.
        """
        hc = request.app.state.health_checker
        orch = request.app.state.orchestrator
        components_ok = {}

        # Check health_checker
        if hc is not None:
            components_ok["health_checker"] = True
        else:
            components_ok["health_checker"] = False

        # Check orchestrator
        if orch is not None:
            components_ok["orchestrator"] = getattr(orch, "_running", False)

        # Check broker
        broker = request.app.state.broker
        if broker is not None:
            components_ok["broker"] = getattr(broker, "is_connected", True)
        else:
            components_ok["broker"] = True  # paper broker = always ready

        # Overall readiness
        all_ready = all(components_ok.values())
        status_code = 200 if all_ready else 503

        return JSONResponse(
            content={
                "status": "ready" if all_ready else "not_ready",
                "service": "noema",
                "version": "2.0.0",
                "timestamp": time.time(),
                "components": components_ok,
            },
            status_code=status_code,
        )

    # ═══════════════════════════════════════════════
    # GET /health/detailed — Full System Health
    # ═══════════════════════════════════════════════

    @app.get("/health/detailed")
    async def health_detailed(request: Request) -> Response:
        """Detailed health report with per-component status.

        Returns comprehensive system health including:
        - Overall status (healthy/degraded/unhealthy)
        - Per-agent health (state, latency, error rate, signal)
        - Connection health (MT5, PostgreSQL, Redis, NIM API)
        - Pipeline status (current phase, cycle count, errors)
        - Trading state (open positions, daily P&L, exposure)
        - Kill-switch state
        - System info (uptime, version, environment)
        """
        hc = request.app.state.health_checker

        if hc is None:
            return JSONResponse(
                content={
                    "status": "unavailable",
                    "error": "Health checker not initialized",
                    "timestamp": time.time(),
                },
                status_code=503,
            )

        try:
            health = hc.collect()
            return JSONResponse(
                content=health.to_dict(),
                status_code=200 if health.overall_status.value == "healthy" else 200,
            )
        except Exception as e:
            logger.error("health_detailed_failed", error=str(e))
            return JSONResponse(
                content={"status": "error", "error": str(e), "timestamp": time.time()},
                status_code=500,
            )

    # ═══════════════════════════════════════════════
    # GET /metrics — Prometheus Metrics Endpoint
    # ═══════════════════════════════════════════════

    @app.get("/metrics")
    async def prometheus_metrics(request: Request) -> Response:
        """Prometheus metrics endpoint.

        Returns metrics in Prometheus text format for scraping.
        Includes pipeline latency, LLM calls, trade counts, P&L,
        system health, and custom Noema metrics.

        Scraped by Prometheus every 10s (configurable in prometheus.yml).
        """
        mc = request.app.state.metrics_collector

        if mc is None:
            return PlainTextResponse(
                content="# Noema metrics collector not initialized\n",
                status_code=503,
            )

        try:
            # Update system-level metrics before scrape
            if hasattr(mc, 'update_uptime'):
                mc.update_uptime()

            metrics_body, content_type = mc.get_metrics_page()
            return Response(
                content=metrics_body,
                media_type=content_type,
                status_code=200,
            )
        except Exception as e:
            logger.error("metrics_scrape_failed", error=str(e))
            return PlainTextResponse(
                content=f"# Metrics scrape error: {e}\n",
                status_code=500,
            )

    # ═══════════════════════════════════════════════
    # POST /shutdown — Graceful Shutdown Trigger
    # ═══════════════════════════════════════════════

    @app.post("/shutdown")
    async def trigger_shutdown(request: Request) -> Response:
        """Trigger graceful shutdown of the Noema system.

        Protected by a secret token to prevent accidental shutdown.
        Sends Authorization: Bearer <NOEMA_SECRET_KEY> header.

        Body (optional):
            {"reason": "maintenance", "policy": "close_all"}

        Returns 202 with shutdown state, or 401 if unauthorized.
        """
        sm = request.app.state.shutdown_manager
        if sm is None:
            return JSONResponse(
                content={"status": "error", "error": "ShutdownManager not initialized"},
                status_code=503,
            )

        # ── Authorization ──────────────────────────────────────────
        auth_header = request.headers.get("Authorization", "")
        secret_key = os.getenv("NOEMA_SECRET_KEY", "")
        expected_token = f"Bearer {secret_key}"

        if secret_key and auth_header != expected_token:
            logger.warning("shutdown_unauthorized_attempt", ip=request.client.host if request.client else "unknown")
            return JSONResponse(
                content={"status": "error", "error": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        # ── Parse optional body ────────────────────────────────────
        reason = "api_request"
        try:
            body = await request.json()
            reason = body.get("reason", reason)
            if body.get("policy"):
                policy_map = {
                    "close_all": "close_all",
                    "close_losing": "close_losing",
                    "hold_all": "hold_all",
                }
                new_policy = policy_map.get(body["policy"])
                if new_policy and hasattr(sm.config, 'policy'):
                    from noema.core.shutdown import ShutdownPositionPolicy
                    policy_val = getattr(ShutdownPositionPolicy, new_policy.upper(), None)
                    if policy_val:
                        sm.config.policy = policy_val
        except Exception:
            pass

        # ── Trigger shutdown asynchronously ────────────────────────
        import asyncio
        loop = asyncio.get_event_loop()

        if not sm.state.initiated:
            loop.create_task(sm.shutdown(reason=reason))

        return JSONResponse(
            content={
                "status": "shutting_down",
                "reason": reason,
                "phase": sm.state.phase,
                "timestamp": time.time(),
            },
            status_code=202,
        )

    # ═══════════════════════════════════════════════
    # Exception Handlers
    # ═══════════════════════════════════════════════

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("api_unhandled_exception", error=str(exc), path=str(request.url))
        return JSONResponse(
            content={
                "status": "error",
                "error": "Internal server error",
                "timestamp": time.time(),
            },
            status_code=500,
        )

    logger.info("health_api_created", endpoints=["/health", "/health/ready", "/health/detailed", "/metrics", "/shutdown"])
    return app


# ═══════════════════════════════════════════════════
# Convenience: Direct app creation (for uvicorn CLI)
# ═══════════════════════════════════════════════════

# Uncomment below to run directly:
# import uvicorn
# if __name__ == "__main__":
#     app = create_health_app()
#     uvicorn.run(app, host="0.0.0.0", port=8000)
