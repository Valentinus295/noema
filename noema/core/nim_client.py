"""NVIDIA NIM LLM Client with caching, retry, rate limiting, and instructor integration.

Provides a production-grade interface to NVIDIA NIM API for all Noema agents.
Features:
- OpenAI-compatible API (works with NIM endpoint)
- Exponential backoff retry on failures
- Decision caching (same market state → same decision)
- Rate limiting (respects NIM's 40-200 RPM limits)
- Structured output via Pydantic model enforcement
- Instructor patching for guaranteed valid structured outputs
- Model tier configuration from llm_models.yaml
- Retry with exponential backoff on validation failures
- Cost tracking per model/tier/agent
- Streaming support for long responses
- Model tiering (fast/small for analysis, big for decisions)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar, Generic

import httpx
import structlog
from pathlib import Path

from pydantic import BaseModel, ValidationError

from noema.core.llm_structured import (
    load_model_config,
    parse_tiers,
    parse_providers,
    get_cost_rates,
    CostTracker,
    ModelTierConfig,
    ProviderConfig,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class ModelTier(str, Enum):
    """Model tiers for different agent types."""
    FAST = "fast"        # Nemotron-3-Nano-9B — ~200ms, for momentum/price action
    STANDARD = "standard"  # Nemotron-3-Super-120B — ~1-2s, for analysis
    HEAVY = "heavy"      # Nemotron-3-Ultra-550B — ~3-5s, for critical decisions


# Model name mapping
MODEL_MAP: dict[ModelTier, str] = {
    ModelTier.FAST: "nvidia/nemotron-3-nano-9b-v2",
    ModelTier.STANDARD: "nvidia/nemotron-3-super-120b-a12b",
    ModelTier.HEAVY: "nvidia/nemotron-3-ultra-550b-a55b",
}

# Default latency budgets per tier (seconds)
LATENCY_BUDGET: dict[ModelTier, float] = {
    ModelTier.FAST: 2.0,
    ModelTier.STANDARD: 5.0,
    ModelTier.HEAVY: 10.0,
}


@dataclass
class CacheEntry:
    """A cached LLM decision."""
    result: Any
    created_at: float
    hits: int = 0


class DecisionCache:
    """Cache LLM decisions for identical market states.

    Avoids redundant NIM calls when market state hasn't changed.
    Cache key = hash of (agent_name, symbol, last N candles, current price, session).
    """

    def __init__(self, ttl_seconds: int = 60, max_entries: int = 500):
        self._cache: dict[str, CacheEntry] = {}
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._hits = 0
        self._misses = 0

    def _make_key(self, agent_name: str, context: dict[str, Any]) -> str:
        """Create deterministic cache key from agent name + market context."""
        # Extract only the data that affects the decision
        relevant = {
            "agent": agent_name,
            "symbol": context.get("symbol", ""),
            "price": context.get("current_price", 0),
            "session": context.get("session", ""),
        }
        # Include last few candles if available
        bars = context.get("bars", [])
        if bars:
            relevant["last_5_bars"] = [
                {"o": b.open, "h": b.high, "l": b.low, "c": b.close}
                for b in (bars[-5:] if hasattr(bars[0], "open") else bars[-5:])
            ]

        raw = json.dumps(relevant, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, agent_name: str, context: dict[str, Any]) -> Any | None:
        """Look up cached result. Returns None on miss."""
        key = self._make_key(agent_name, context)
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None
        if time.time() - entry.created_at > self.ttl:
            del self._cache[key]
            self._misses += 1
            return None
        entry.hits += 1
        self._hits += 1
        logger.debug("cache_hit", agent=agent_name, key=key, hits=entry.hits)
        return entry.result

    def set(self, agent_name: str, context: dict[str, Any], result: Any) -> None:
        """Store result in cache."""
        if len(self._cache) >= self.max_entries:
            self._evict()
        key = self._make_key(agent_name, context)
        self._cache[key] = CacheEntry(result=result, created_at=time.time())

    def _evict(self) -> None:
        """Evict oldest entries when cache is full."""
        now = time.time()
        expired = [k for k, v in self._cache.items() if now - v.created_at > self.ttl]
        for k in expired:
            del self._cache[k]
        # If still full, remove oldest by creation time
        if len(self._cache) >= self.max_entries:
            oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
            del self._cache[oldest_key]

    @property
    def stats(self) -> dict[str, int]:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total * 100, 1) if total else 0,
            "entries": len(self._cache),
        }


class RateLimiter:
    """Token bucket rate limiter for NIM API calls.

    Respects NIM's 40-200 RPM limits with configurable burst.
    """

    def __init__(self, rpm: int = 40, burst: int = 5):
        self.rpm = rpm
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self.burst,
                self._tokens + elapsed * (self.rpm / 60.0),
            )
            self._last_refill = now

            if self._tokens < 1.0:
                wait_time = (1.0 - self._tokens) * (60.0 / self.rpm)
                logger.debug("rate_limit_wait", wait_seconds=round(wait_time, 2))
                await asyncio.sleep(wait_time)
                self._tokens = 1.0
                self._last_refill = time.monotonic()

            self._tokens -= 1.0


class NIMClient:
    """Production-grade NVIDIA NIM client for Noema.

    Usage:
        client = NIMClient(api_key="nvapi-...")
        decision = await client.chat_completion(
            messages=[{"role": "system", "content": "..."}, ...],
            response_model=TradeDecision,
            tier=ModelTier.STANDARD,
            agent_name="trade-thesis",
            context=market_context,
        )
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        default_tier: ModelTier = ModelTier.STANDARD,
        cache_ttl: int = 60,
        cache_enabled: bool = True,
        max_retries: int = 3,
        rpm_limit: int = 40,
        use_instructor: bool = False,
        config_path: str | Path | None = None,
        provider: str = "nvidia_nim",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_tier = default_tier
        self.max_retries = max_retries
        self.use_instructor = use_instructor

        self._cache = DecisionCache(ttl_seconds=cache_ttl) if cache_enabled else None
        self._rate_limiter = RateLimiter(rpm=rpm_limit)
        self._client: httpx.AsyncClient | None = None

        # Model tier configuration
        raw_config = load_model_config(config_path)
        self._model_tiers = parse_tiers(raw_config)
        self._providers = parse_providers(raw_config)
        self._cost_rates = get_cost_rates(raw_config)

        # Cost tracking
        self.cost_tracker = CostTracker()
        self.cost_tracker.set_cost_rates(self._cost_rates)

        # Instructor client (lazy-init)
        self._instructor_client = None

        # Metrics
        self._total_calls = 0
        self._total_errors = 0
        self._total_latency_ms = 0.0
        self._total_validation_retries = 0
        self._total_fallback_used = 0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        response_model: type[T] | None = None,
        tier: ModelTier | None = None,
        agent_name: str = "unknown",
        context: dict[str, Any] | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        use_cache: bool = True,
    ) -> dict[str, Any] | T:
        """Call NIM chat completion with retry, caching, and optional Pydantic parsing.

        Args:
            messages: Chat messages in OpenAI format
            response_model: Pydantic model to parse response into
            tier: Model tier (FAST/STANDARD/HEAVY)
            agent_name: Name of calling agent (for cache key + logging)
            context: Market context (for cache key)
            tools: Function calling tool definitions
            tool_choice: Tool choice strategy
            temperature: LLM temperature (0.0-1.0)
            max_tokens: Max response tokens
            use_cache: Whether to check/store cache

        Returns:
            Parsed Pydantic model (if response_model given) or raw dict
        """
        tier = tier or self.default_tier
        model = MODEL_MAP[tier]
        context = context or {}

        # Check cache
        if use_cache and self._cache and response_model:
            cached = self._cache.get(agent_name, context)
            if cached is not None:
                return cached

        # Rate limit
        await self._rate_limiter.acquire()

        # Build request body
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Structured output: force JSON if response_model given
        if response_model and not tools:
            body["response_format"] = {"type": "json_object"}

        # Function calling
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice

        # Execute with retry
        result = await self._call_with_retry(body, tier)

        # Parse response
        parsed = self._parse_response(result, response_model)

        # Cache result
        if use_cache and self._cache and response_model:
            self._cache.set(agent_name, context, parsed)

        return parsed

    async def _call_with_retry(
        self, body: dict[str, Any], tier: ModelTier
    ) -> dict[str, Any]:
        """Execute API call with exponential backoff retry."""
        client = await self._get_client()
        last_error = None

        for attempt in range(self.max_retries):
            start = time.monotonic()
            try:
                response = await client.post("/chat/completions", json=body)
                elapsed_ms = (time.monotonic() - start) * 1000

                if response.status_code == 429:
                    # Rate limited — wait and retry
                    retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
                    logger.warning(
                        "nim_rate_limited",
                        attempt=attempt + 1,
                        retry_after=retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                response.raise_for_status()
                result = response.json()

                # Track metrics
                self._total_calls += 1
                self._total_latency_ms += elapsed_ms
                logger.info(
                    "nim_call_success",
                    agent=body.get("messages", [{}])[0].get("content", "")[:50],
                    model=body["model"],
                    latency_ms=round(elapsed_ms, 1),
                    attempt=attempt + 1,
                    tier=tier.value,
                )
                return result

            except httpx.TimeoutException:
                elapsed_ms = (time.monotonic() - start) * 1000
                last_error = f"Timeout after {elapsed_ms:.0f}ms"
                self._total_errors += 1
                logger.warning(
                    "nim_timeout",
                    attempt=attempt + 1,
                    latency_ms=round(elapsed_ms, 1),
                    tier=tier.value,
                )

            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}"
                self._total_errors += 1
                logger.warning(
                    "nim_http_error",
                    status=e.response.status_code,
                    attempt=attempt + 1,
                    tier=tier.value,
                )
                if e.response.status_code >= 500:
                    # Server error — retry
                    pass
                elif e.response.status_code == 401:
                    # Auth error — don't retry
                    raise
                else:
                    # Client error — don't retry
                    raise

            except Exception as e:
                last_error = str(e)
                self._total_errors += 1
                logger.error("nim_unexpected_error", error=str(e), attempt=attempt + 1)

            # Exponential backoff
            if attempt < self.max_retries - 1:
                wait = min(2 ** attempt, 8) + 0.5 * (attempt + 1)
                await asyncio.sleep(wait)

        raise RuntimeError(
            f"NIM API failed after {self.max_retries} attempts: {last_error}"
        )

    def _parse_response(
        self, result: dict[str, Any], response_model: type[T] | None
    ) -> dict[str, Any] | T:
        """Parse NIM response into Pydantic model or raw dict."""
        choice = result.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")

        # Handle tool calls
        if message.get("tool_calls"):
            return {
                "type": "tool_calls",
                "tool_calls": message["tool_calls"],
                "content": content,
            }

        # Parse as JSON for structured output
        if response_model:
            try:
                # Try to extract JSON from content
                parsed = self._extract_json(content)
                return response_model(**parsed)
            except (ValidationError, json.JSONDecodeError) as e:
                logger.warning(
                    "nim_parse_failed",
                    model=response_model.__name__,
                    error=str(e),
                    content_preview=content[:200],
                )
                # Return raw content as fallback
                return {"type": "raw", "content": content, "parse_error": str(e)}

        return {"type": "raw", "content": content}

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from LLM response, handling markdown code blocks."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from ```json ... ``` blocks
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())

        # Try extracting from ``` ... ``` blocks
        if "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            return json.loads(text[start:end].strip())

        # Try finding first { ... } block
        brace_start = text.find("{")
        brace_end = text.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            return json.loads(text[brace_start:brace_end])

        raise json.JSONDecodeError("No JSON found", text, 0)

    # ── Instructor-patched structured output ────────────────────────

    def _ensure_instructor_client(self):
        """Lazy-init the instructor-patched client."""
        if self._instructor_client is not None:
            return

        try:
            import instructor
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "instructor mode requires 'instructor' and 'openai' packages. "
                "Install with: pip install instructor openai"
            ) from e

        self._instructor_openai = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=60.0,
            max_retries=0,
        )

        self._instructor_client = instructor.from_openai(
            self._instructor_openai,
            mode=instructor.Mode.MD_JSON,
        )

        logger.info(
            "instructor_client_initialized",
            base_url=self.base_url[:50],
            mode="MD_JSON",
        )

    async def structured_complete(
        self,
        model: str,
        prompt: str,
        response_model: type[T],
        system_prompt: str = "",
        tier_name: str = "analysis",
        agent_name: str = "unknown",
        temperature: float | None = None,
        max_tokens: int | None = None,
        messages: list[dict[str, str]] | None = None,
        validation_context: dict[str, Any] | None = None,
    ) -> T:
        """Get a validated structured output via instructor.

        This method patches the NIM API with instructor, guaranteeing
        Pydantic-valid responses on every call. On validation failure,
        it retries with exponential backoff up to max_retries times.

        Args:
            model: Model name (e.g., 'claude-4-sonnet')
            prompt: User prompt
            response_model: Pydantic model to validate against
            system_prompt: System instructions
            tier_name: Tier name for config lookup ('decision', 'analysis', 'fast', 'local')
            agent_name: Calling agent name for logging/cost tracking
            temperature: Override temperature (uses tier default if None)
            max_tokens: Override max_tokens (uses tier default if None)
            messages: Full message list (overrides prompt/system_prompt if set)
            validation_context: Extra context for Pydantic validators

        Returns:
            Validated instance of response_model

        Raises:
            RuntimeError: If all retries fail
        """
        self._ensure_instructor_client()
        assert self._instructor_client is not None

        # Resolve tier config
        tier_cfg = self._model_tiers.get(tier_name)

        if messages is None:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

        # Resolve parameters with tier defaults
        temp = temperature if temperature is not None else (tier_cfg.temperature if tier_cfg else 0.1)
        tokens = max_tokens or (tier_cfg.max_tokens if tier_cfg else 1024)

        effective_model = model
        last_error = None

        for attempt in range(self.max_retries + 1):
            start = time.monotonic()
            try:
                response, completion = await self._instructor_client.chat.completions.create_with_completion(
                    model=effective_model,
                    response_model=response_model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=tokens,
                    validation_context=validation_context,
                )

                elapsed_ms = (time.monotonic() - start) * 1000

                # Extract token usage
                usage = completion.usage
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0

                # Track cost
                self.cost_tracker.record(
                    model=effective_model,
                    tier=tier_name,
                    agent=agent_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=elapsed_ms,
                )

                self._total_calls += 1
                self._total_latency_ms += elapsed_ms
                logger.info(
                    "structured_completion_success",
                    agent=agent_name,
                    model=effective_model,
                    tier=tier_name,
                    response_model=response_model.__name__,
                    latency_ms=round(elapsed_ms, 1),
                    attempt=attempt + 1,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

                return response

            except Exception as e:
                last_error = e
                error_name = type(e).__name__
                elapsed_ms = (time.monotonic() - start) * 1000

                # Track validation failures
                if "validation" in error_name.lower() or "pydantic" in error_name.lower():
                    self._total_validation_retries += 1

                logger.warning(
                    "structured_completion_retry",
                    agent=agent_name,
                    model=effective_model,
                    attempt=attempt + 1,
                    error=error_name,
                    error_msg=str(e)[:200],
                    latency_ms=round(elapsed_ms, 1),
                )

                # Try fallback model if primary fails after 2+ attempts
                if attempt >= 2 and tier_cfg and tier_cfg.fallback and effective_model == tier_cfg.primary:
                    logger.info(
                        "model_fallback",
                        agent=agent_name,
                        from_model=effective_model,
                        to_model=tier_cfg.fallback,
                        attempt=attempt + 1,
                    )
                    effective_model = tier_cfg.fallback
                    self._total_fallback_used += 1

                # Exponential backoff with jitter
                if attempt < self.max_retries:
                    wait = min(2 ** attempt, 8) + 0.5 * attempt
                    await asyncio.sleep(wait)

        # All retries exhausted
        self._total_calls += 1
        self._total_errors += 1
        logger.error(
            "structured_completion_failed",
            agent=agent_name,
            model=effective_model,
            tier=tier_name,
            retries=self.max_retries,
            last_error=str(last_error)[:300],
        )
        raise RuntimeError(
            f"NIMClient.structured_complete: Failed to get valid {response_model.__name__} "
            f"from {effective_model} after {self.max_retries + 1} attempts. "
            f"Last error: {last_error}"
        )

    def get_tier_config(self, tier_name: str) -> ModelTierConfig | None:
        """Get configuration for a model tier by name."""
        return self._model_tiers.get(tier_name)

    def get_tier_model(self, tier_name: str) -> str:
        """Resolve the effective model name for a tier (primary or fallback)."""
        tier_cfg = self._model_tiers.get(tier_name)
        if tier_cfg:
            return tier_cfg.primary or tier_cfg.fallback
        return MODEL_MAP.get(self.default_tier, "claude-4-sonnet")

    @property
    def metrics(self) -> dict[str, Any]:
        """Return client metrics for monitoring."""
        cache_stats = self._cache.stats if self._cache else {"hits": 0, "misses": 0, "hit_rate": 0}
        avg_latency = (
            self._total_latency_ms / self._total_calls
            if self._total_calls > 0
            else 0
        )
        return {
            "total_calls": self._total_calls,
            "total_errors": self._total_errors,
            "avg_latency_ms": round(avg_latency, 1),
            "error_rate": round(
                self._total_errors / self._total_calls * 100, 1
            ) if self._total_calls else 0,
            "validation_retries": self._total_validation_retries,
            "fallback_used": self._total_fallback_used,
            "cache": cache_stats,
            "cost": self.cost_tracker.summary,
        }
