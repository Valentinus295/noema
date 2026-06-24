"""
Noema Observability — OpenTelemetry + Langfuse integration.

Traces every agent decision, LLM call, and trade execution.
All spans include: agent name, pipeline phase, symbol, timeframe, duration.

Architecture:
    Agent → OTel Span (distributed trace) → OTLP Collector
    Agent → Langfuse (LLM observability: prompts, tokens, latency)
    Both paths converge in Langfuse Cloud/Self-hosted for a single-pane view.

Running agents without tracing = flying blind with real money.
"""

from __future__ import annotations

import functools
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import structlog

logger = structlog.get_logger(__name__)

# ── Feature flags ────────────────────────────────────────────────────
_OTEL_AVAILABLE = False
_LANGFUSE_AVAILABLE = False
_TRACING_ENABLED = False

# ── Try imports ──────────────────────────────────────────────────────
try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.trace import Status, StatusCode, Span, SpanKind, Tracer
    _OTEL_AVAILABLE = True
except ImportError:
    logger.warning("opentelemetry_not_installed", hint="pip install opentelemetry-sdk opentelemetry-exporter-otlp")

try:
    import langfuse  # type: ignore[import-untyped]
    _LANGFUSE_AVAILABLE = True
except ImportError:
    logger.info("langfuse_not_installed", hint="pip install langfuse")


# ── Globals ──────────────────────────────────────────────────────────
_tracer: Any = None
_langfuse_client: Any = None
_provider: Any = None

F = TypeVar("F", bound=Callable[..., Any])


# ── Initialization ───────────────────────────────────────────────────

def init_observability(
    service_name: str = "noema",
    otlp_endpoint: str | None = None,
    langfuse_public_key: str | None = None,
    langfuse_secret_key: str | None = None,
    langfuse_host: str | None = None,
    environment: str = "development",
    enabled: bool = True,
) -> bool:
    """Initialize OpenTelemetry tracing + Langfuse LLM observability.

    Configures:
        - OTLP exporter → local collector OR direct to Langfuse
        - Langfuse client for prompt/token/trace-level LLM observability
        - Batch span processor with sensible defaults

    Returns True if observability was initialized successfully.
    """
    global _tracer, _langfuse_client, _provider, _TRACING_ENABLED

    if not enabled:
        logger.info("observability_disabled")
        return False

    otlp_endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    langfuse_public_key = langfuse_public_key or os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key = langfuse_secret_key or os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_host = langfuse_host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    otel_ok = False
    langfuse_ok = False

    # ── OpenTelemetry Tracer ────────────────────────────────────────
    if _OTEL_AVAILABLE and otlp_endpoint:
        try:
            resource = Resource(attributes={
                SERVICE_NAME: service_name,
                "deployment.environment": environment,
                "service.version": "2.0.0",
            })
            _provider = TracerProvider(resource=resource)

            exporter = OTLPSpanExporter(
                endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces",
                timeout=10,
            )
            _provider.add_span_processor(
                BatchSpanProcessor(
                    exporter,
                    max_export_batch_size=512,
                    schedule_delay_millis=5000,
                )
            )
            otel_trace.set_tracer_provider(_provider)
            _tracer = otel_trace.get_tracer(__name__, instrumentor="noema")
            otel_ok = True
            logger.info("otel_initialized", endpoint=otlp_endpoint, service=service_name)
        except Exception as e:
            logger.warning("otel_init_failed", error=str(e))
    elif otlp_endpoint:
        logger.warning("otel_skipped", reason="opentelemetry packages not installed")
    else:
        logger.info("otel_skipped", reason="no OTLP endpoint configured")

    # ── Langfuse Client ─────────────────────────────────────────────
    if _LANGFUSE_AVAILABLE and langfuse_public_key and langfuse_secret_key:
        try:
            _langfuse_client = langfuse.Langfuse(
                public_key=langfuse_public_key,
                secret_key=langfuse_secret_key,
                host=langfuse_host,
                release="2.0.0",
                environment=environment,
            )
            langfuse_ok = True
            logger.info("langfuse_initialized", host=langfuse_host)
        except Exception as e:
            logger.warning("langfuse_init_failed", error=str(e))
    elif langfuse_public_key:
        logger.warning("langfuse_skipped", reason="langfuse package not installed")
    else:
        logger.info("langfuse_skipped", reason="no credentials configured")

    _TRACING_ENABLED = otel_ok or langfuse_ok

    if not _TRACING_ENABLED:
        logger.info("tracing_disabled", reason="neither OTel nor Langfuse configured")

    return _TRACING_ENABLED


def is_tracing_enabled() -> bool:
    """Check if any tracing backend is active."""
    return _TRACING_ENABLED


# ── TraceAgent: context manager for agent execution ──────────────────

class TraceAgent:
    """Context manager that wraps agent execution in an OTel span + Langfuse generation.

    Usage:
        async with TraceAgent(
            agent_name="market-structure",
            pipeline_phase="analysis",
            symbol="EURUSD",
            timeframe="H1",
        ) as span:
            result = await agent.process(context)
            span.set_attributes(confidence=0.85, signal="BULLISH")
    """

    def __init__(
        self,
        agent_name: str,
        pipeline_phase: str,
        symbol: str = "",
        timeframe: str = "H1",
        nim_model: str = "",
    ):
        self.agent_name = agent_name
        self.pipeline_phase = pipeline_phase
        self.symbol = symbol
        self.timeframe = timeframe
        self.nim_model = nim_model
        self._otel_span: Any = None
        self._langfuse_generation: Any = None
        self._start_time: float = 0.0
        self._confidence: float = 0.0
        self._signal: str = "NEUTRAL"
        self._tokens_prompt: int = 0
        self._tokens_completion: int = 0
        self._llm_latency_ms: float = 0.0
        self._error: str | None = None

    async def __aenter__(self) -> "TraceAgent":
        self._start_time = time.monotonic()

        # ── OTel Span ──────────────────────────────────────────────
        if _tracer is not None:
            try:
                span_name = f"{self.pipeline_phase}:{self.agent_name}"
                self._otel_span = _tracer.start_span(
                    name=span_name,
                    kind=SpanKind.INTERNAL,
                    attributes={
                        "agent.name": self.agent_name,
                        "pipeline.phase": self.pipeline_phase,
                        "trade.symbol": self.symbol,
                        "trade.timeframe": self.timeframe,
                        "service.name": "noema",
                    },
                )
            except Exception as e:
                logger.debug("otel_span_start_failed", error=str(e))

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        duration_ms = (time.monotonic() - self._start_time) * 1000

        # ── Finalize OTel Span ─────────────────────────────────────
        if self._otel_span is not None:
            try:
                attrs = {
                    "agent.confidence": self._confidence,
                    "agent.duration_ms": round(duration_ms, 1),
                    "trade.signal": self._signal,
                    "trade.symbol": self.symbol,
                }
                if self.nim_model:
                    attrs["llm.model"] = self.nim_model
                    attrs["llm.tokens"] = self._tokens_prompt + self._tokens_completion
                    attrs["llm.latency_ms"] = round(self._llm_latency_ms, 1)

                self._otel_span.set_attributes(attrs)

                if exc_val is not None:
                    self._otel_span.set_status(Status(StatusCode.ERROR, str(exc_val)))
                    self._otel_span.record_exception(exc_val)
                else:
                    self._otel_span.set_status(Status(StatusCode.OK))

                self._otel_span.end()
            except Exception as e:
                logger.debug("otel_span_end_failed", error=str(e))

        # ── Langfuse Generation ────────────────────────────────────
        if self._langfuse_generation is not None:
            try:
                self._langfuse_generation.end(
                    output=self._signal,
                    metadata={
                        "agent.confidence": self._confidence,
                        "agent.duration_ms": round(duration_ms, 1),
                        "trade.symbol": self.symbol,
                        "pipeline.phase": self.pipeline_phase,
                    },
                )
            except Exception as e:
                logger.debug("langfuse_end_failed", error=str(e))

        # Don't suppress exceptions
        return False

    def set_attributes(
        self,
        confidence: float = 0.0,
        signal: str = "NEUTRAL",
        error: str | None = None,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
        llm_latency_ms: float = 0.0,
        **extra: Any,
    ) -> None:
        """Set span attributes (called during agent execution)."""
        self._confidence = confidence
        self._signal = signal
        self._error = error
        self._tokens_prompt = tokens_prompt
        self._tokens_completion = tokens_completion
        self._llm_latency_ms = llm_latency_ms

        if self._otel_span is not None and extra:
            try:
                self._otel_span.set_attributes(extra)
            except Exception:
                pass

    def track_llm_generation(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        input_prompt: str = "",
        output_text: str = "",
    ) -> None:
        """Track LLM generation in Langfuse with detailed token/latency metadata.

        Creates a Langfuse generation nested under the current trace.
        """
        self.nim_model = model
        self._tokens_prompt = prompt_tokens
        self._tokens_completion = completion_tokens
        self._llm_latency_ms = latency_ms

        if _langfuse_client is not None:
            try:
                trace = _langfuse_client.trace(
                    name=f"{self.pipeline_phase}:{self.agent_name}",
                    metadata={
                        "agent.name": self.agent_name,
                        "trade.symbol": self.symbol,
                        "pipeline.phase": self.pipeline_phase,
                    },
                )
                self._langfuse_generation = trace.generation(
                    name=f"llm:{self.agent_name}",
                    model=model,
                    input=input_prompt[:4096] if input_prompt else None,
                    output=output_text[:4096] if output_text else None,
                    usage={
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                    metadata={
                        "latency_ms": round(latency_ms, 1),
                        "agent.name": self.agent_name,
                        "trade.symbol": self.symbol,
                    },
                )
            except Exception as e:
                logger.debug("langfuse_track_failed", error=str(e))


# ── trace_llm_call: decorator for LLM API calls ──────────────────────

def trace_llm_call(
    agent_name: str = "unknown",
    model: str = "unknown",
    pipeline_phase: str = "decision",
    symbol: str = "",
) -> Callable[[F], F]:
    """Decorator that traces an LLM API call in OTel + Langfuse.

    Wraps the NIMClient.chat_completion method or any LLM call function.
    Captures: tokens, latency, model, cache hit/miss, errors.

    Usage:
        @trace_llm_call(agent_name="thesis", model="nemotron-3", pipeline_phase="decision")
        async def chat_completion(self, messages, ...):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            span_name = f"llm:{agent_name}"

            # OTel span
            otel_span = None
            if _tracer is not None:
                try:
                    otel_span = _tracer.start_span(
                        name=span_name,
                        kind=SpanKind.CLIENT,
                        attributes={
                            "agent.name": agent_name,
                            "llm.model": model,
                            "pipeline.phase": pipeline_phase,
                            "trade.symbol": symbol,
                            "llm.tier": kwargs.get("tier", "standard"),
                        },
                    )
                except Exception:
                    pass

            try:
                result = await func(*args, **kwargs)
                latency_ms = (time.monotonic() - start) * 1000

                # Extract token counts from result if available
                prompt_tokens = 0
                completion_tokens = 0
                if isinstance(result, dict):
                    usage = result.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    completion_tokens = usage.get("completion_tokens", 0)

                # Finalize OTel span
                if otel_span is not None:
                    otel_span.set_attributes({
                        "llm.latency_ms": round(latency_ms, 1),
                        "llm.tokens_prompt": prompt_tokens,
                        "llm.tokens_completion": completion_tokens,
                        "llm.total_tokens": prompt_tokens + completion_tokens,
                        "llm.cache_hit": getattr(result, "cached", False),
                    })
                    otel_span.set_status(Status(StatusCode.OK))
                    otel_span.end()

                # Langfuse generation
                if _langfuse_client is not None:
                    try:
                        trace = _langfuse_client.trace(
                            name=span_name,
                            metadata={
                                "agent.name": agent_name,
                                "trade.symbol": symbol,
                            },
                        )
                        trace.generation(
                            name=f"llm:{agent_name}",
                            model=model,
                            usage={
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                            },
                            metadata={
                                "latency_ms": round(latency_ms, 1),
                                "pipeline.phase": pipeline_phase,
                            },
                        )
                    except Exception:
                        pass

                return result
            except Exception as e:
                latency_ms = (time.monotonic() - start) * 1000
                if otel_span is not None:
                    otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                    otel_span.record_exception(e)
                    otel_span.end()
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            span_name = f"llm:{agent_name}"
            otel_span = None
            if _tracer is not None:
                try:
                    otel_span = _tracer.start_span(
                        name=span_name,
                        kind=SpanKind.CLIENT,
                        attributes={
                            "agent.name": agent_name,
                            "llm.model": model,
                            "pipeline.phase": pipeline_phase,
                            "trade.symbol": symbol,
                        },
                    )
                except Exception:
                    pass

            try:
                result = func(*args, **kwargs)
                latency_ms = (time.monotonic() - start) * 1000
                if otel_span is not None:
                    otel_span.set_attributes({"llm.latency_ms": round(latency_ms, 1)})
                    otel_span.set_status(Status(StatusCode.OK))
                    otel_span.end()
                return result
            except Exception as e:
                if otel_span is not None:
                    otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                    otel_span.record_exception(e)
                    otel_span.end()
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


# ── log_trade_decision: records trade decisions as OTel events ───────

def log_trade_decision(
    symbol: str,
    decision: str,
    confidence: float,
    consensus_score: float,
    agent_scores: dict[str, float],
    reasoning: str = "",
    price: float = 0.0,
    session: str = "",
    lot_size: float = 0.0,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    pipeline_phase: str = "execution",
) -> None:
    """Record a trade decision with full context as OTel events + Langfuse score.

    Called whenever the CIO makes a final BUY/SELL/NO_TRADE decision.

    Args:
        symbol: Trading symbol (EURUSD, etc.)
        decision: BUY, SELL, NO_TRADE
        confidence: CIO confidence 0.0-1.0
        consensus_score: Average agent confidence
        agent_scores: {agent_name: confidence} for all contributing agents
        reasoning: Trade thesis text (first 500 chars)
        price: Current price
        session: Trading session (Asian/London/NY)
        lot_size: Position size
        stop_loss: SL price
        take_profit: TP price
        pipeline_phase: Current pipeline phase
    """
    # ── OTel Span Event ─────────────────────────────────────────────
    if _tracer is not None:
        try:
            with _tracer.start_as_current_span(
                name=f"trade_decision:{symbol}",
                kind=SpanKind.INTERNAL,
                attributes={
                    "trade.symbol": symbol,
                    "trade.signal": decision.lower(),
                    "trade.decision": decision,
                    "agent.confidence": confidence,
                    "trade.consensus_score": consensus_score,
                    "trade.price": price,
                    "trade.session": session,
                    "trade.lot_size": lot_size,
                    "trade.stop_loss": stop_loss,
                    "trade.take_profit": take_profit,
                    "pipeline.phase": pipeline_phase,
                    "trade.agent_count": len(agent_scores),
                    "trade.reasoning": reasoning[:300],
                },
            ) as span:
                # Add individual agent scores as span events
                for agent, score in agent_scores.items():
                    span.add_event(
                        "agent_score",
                        attributes={"agent.name": agent, "agent.confidence": score},
                    )
                span.set_status(Status(StatusCode.OK))
        except Exception:
            pass

    # ── Langfuse Score ──────────────────────────────────────────────
    if _langfuse_client is not None:
        try:
            trace = _langfuse_client.trace(
                name=f"trade:{symbol}",
                input={"symbol": symbol, "price": price, "session": session},
                output={"decision": decision, "confidence": confidence},
                metadata={
                    "agent_scores": agent_scores,
                    "consensus_score": consensus_score,
                    "lot_size": lot_size,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                },
            )
            # Record decision quality score (to be updated later with actual P&L)
            trace.score(
                name="trade_decision_confidence",
                value=confidence,
                comment=f"CIO {decision} on {symbol} at {price}",
            )
        except Exception:
            pass

    # Always log
    logger.info(
        "trade_decision_recorded",
        symbol=symbol,
        decision=decision,
        confidence=round(confidence, 3),
        consensus=round(consensus_score, 3),
        agents=len(agent_scores),
        price=price,
    )


# ── log_kill_switch: records kill-switch activations ─────────────────

def log_kill_switch(
    reason: str,
    symbol: str = "",
    triggered_by: str = "risk_manager",
    current_exposure_pct: float = 0.0,
    daily_pnl_pct: float = 0.0,
    pipeline_phase: str = "execution",
) -> None:
    """Record when kill-switches activate and why.

    Kill-switches are the most critical safety mechanism — every activation
    must be traceable and auditable.

    Args:
        reason: Why the kill-switch fired
        symbol: Symbol that triggered it (empty = system-wide)
        triggered_by: Which agent/component triggered it
        current_exposure_pct: Current account exposure %
        daily_pnl_pct: Daily P&L %
        pipeline_phase: Pipeline phase when triggered
    """
    # ── OTel Span ───────────────────────────────────────────────────
    if _tracer is not None:
        try:
            with _tracer.start_as_current_span(
                name=f"kill_switch: {reason[:60]}",
                kind=SpanKind.INTERNAL,
                attributes={
                    "kill_switch.reason": reason,
                    "kill_switch.symbol": symbol or "system_wide",
                    "kill_switch.triggered_by": triggered_by,
                    "trade.exposure_pct": current_exposure_pct,
                    "trade.daily_pnl_pct": daily_pnl_pct,
                    "pipeline.phase": pipeline_phase,
                },
            ) as span:
                span.set_status(Status(StatusCode.OK))
                span.add_event(
                    "kill_switch_activated",
                    attributes={
                        "reason": reason,
                        "exposure": current_exposure_pct,
                        "daily_pnl": daily_pnl_pct,
                    },
                )
        except Exception:
            pass

    # ── Langfuse ────────────────────────────────────────────────────
    if _langfuse_client is not None:
        try:
            trace = _langfuse_client.trace(
                name=f"kill_switch:{triggered_by}",
                metadata={
                    "reason": reason,
                    "symbol": symbol,
                    "triggered_by": triggered_by,
                    "exposure_pct": current_exposure_pct,
                    "daily_pnl_pct": daily_pnl_pct,
                },
            )
            trace.score(
                name="kill_switch_severity",
                value=1.0 if current_exposure_pct > 5.0 else 0.5,
                comment=reason,
            )
        except Exception:
            pass

    # Always log — this is critical
    logger.warning(
        "kill_switch_activated",
        reason=reason,
        symbol=symbol,
        triggered_by=triggered_by,
        exposure_pct=current_exposure_pct,
        daily_pnl_pct=daily_pnl_pct,
    )


# ── get_trace_url: returns Langfuse trace URL for debugging ──────────

def get_trace_url(trace_id: str = "", langfuse_host: str = "") -> str:
    """Return Langfuse trace URL for direct inspection.

    Args:
        trace_id: Langfuse trace ID (optional, uses current if available)
        langfuse_host: Langfuse host URL (defaults to env LANGFUSE_HOST)

    Returns:
        Full URL to the trace in Langfuse UI, or empty string if unavailable.
    """
    host = langfuse_host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    host = host.rstrip("/")

    if _langfuse_client is not None and not trace_id:
        try:
            # Try to get the current trace ID from Langfuse
            trace_id = getattr(_langfuse_client, "get_trace_id", lambda: "")()
        except Exception:
            pass

    if trace_id:
        return f"{host}/trace/{trace_id}"

    return f"{host}" if _LANGFUSE_AVAILABLE else ""


# ── Pipeline Phase Tracing ───────────────────────────────────────────

@contextmanager
def trace_pipeline_phase(
    phase_name: str,
    symbol: str = "",
    extra_attrs: dict[str, Any] | None = None,
):
    """Context manager for tracing a complete pipeline phase.

    Usage:
        with trace_pipeline_phase("data_collection", symbol="EURUSD") as span:
            results = await gather_agents()
    """
    start = time.monotonic()
    otel_span = None
    attrs = {
        "pipeline.phase": phase_name,
        "trade.symbol": symbol,
    }
    if extra_attrs:
        attrs.update(extra_attrs)

    if _tracer is not None:
        try:
            otel_span = _tracer.start_span(
                name=f"pipeline:{phase_name}",
                kind=SpanKind.INTERNAL,
                attributes=attrs,
            )
        except Exception:
            pass

    try:
        yield otel_span
        duration_ms = (time.monotonic() - start) * 1000
        if otel_span is not None:
            otel_span.set_attribute("pipeline.duration_ms", round(duration_ms, 1))
            otel_span.set_status(Status(StatusCode.OK))
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        if otel_span is not None:
            otel_span.set_attribute("pipeline.duration_ms", round(duration_ms, 1))
            otel_span.set_status(Status(StatusCode.ERROR, str(e)))
            otel_span.record_exception(e)
        raise
    finally:
        if otel_span is not None:
            otel_span.end()


def record_pipeline_phase_transition(
    from_phase: str,
    to_phase: str,
    symbol: str = "",
    latency_ms: float = 0.0,
) -> None:
    """Record a transition between pipeline phases."""
    if _tracer is not None:
        try:
            span = _tracer.start_span(
                name=f"transition:{from_phase}→{to_phase}",
                kind=SpanKind.INTERNAL,
                attributes={
                    "pipeline.from_phase": from_phase,
                    "pipeline.to_phase": to_phase,
                    "trade.symbol": symbol,
                    "pipeline.transition_latency_ms": round(latency_ms, 1),
                },
            )
            span.set_status(Status(StatusCode.OK))
            span.end()
        except Exception:
            pass

    logger.debug(
        "phase_transition",
        from_phase=from_phase,
        to_phase=to_phase,
        symbol=symbol,
    )
