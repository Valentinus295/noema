"""PydanticAI + instructor integration layer for Noema structured LLM outputs.

Provides type-safe structured output extraction from LLMs using:
- instructor: Guaranteed Pydantic-valid responses via client patching
- PydanticAI patterns: Agent definition with typed input/output models

Architecture:
    Agent → LLMStructuredClient.complete(model, prompt, response_model) → Validated Pydantic model
    Every LLM call returns a validated instance. No raw JSON trust.

Key design decisions:
- instructor.patch() wraps the OpenAI-compatible client so every .chat.completions.create()
  call returns a validated Pydantic model directly
- Fundamental bias contribution is enforceably capped at 0.05 (see validate_bias_contribution)
- All structured outputs are logged via structlog for audit/tracing
- Retry with exponential backoff on Pydantic ValidationError
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Generic, TypeVar

import structlog
import yaml
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


# ═══════════════════════════════════════════════════════════════════════
# Pydantic Output Models for all LLM agents
# ═══════════════════════════════════════════════════════════════════════

class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class TradeSignal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class Verdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    NEEDS_REVISION = "needs_revision"


class PatternType(str, Enum):
    TREND_CONTINUATION = "trend_continuation"
    TREND_REVERSAL = "trend_reversal"
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    RANGE_TRADE = "range_trade"
    NEWS_REACTION = "news_reaction"
    FALSE_BREAKOUT = "false_breakout"
    LIQUIDITY_GRAB = "liquidity_grab"
    SMC_ENTRY = "smc_entry"
    UNKNOWN = "unknown"


class KeyLevel(BaseModel):
    """A significant price level with type and strength annotation."""
    price: float
    type: str = Field(description="support | resistance | pivot | order_block | fvg | liquidity")
    strength: float = Field(ge=0.0, le=1.0, description="How significant this level is")
    timeframe: str = Field(default="H4", description="Timeframe where level is most visible")
    reasoning: str = Field(default="", max_length=200)


class Risk(BaseModel):
    """A named risk to the trade with severity and mitigation."""
    name: str = Field(min_length=3, max_length=120)
    severity: float = Field(ge=0.0, le=1.0, description="1.0 = trade killer")
    probability: float = Field(ge=0.0, le=1.0, description="Estimated probability")
    mitigation: str = Field(max_length=300, description="How to manage or avoid this risk")


# ── FundamentalBiasOutput ────────────────────────────────────────────

class FundamentalBiasOutput(BaseModel):
    """Structured output from FundamentalBiasAgent.

    The bias_score is capped at ±0.05 in the LLM contribution layer.
    The deterministic compute (Taylor rule, yield diffs) drives the main score,
    LLM narration only adjusts within the 0.05 band.
    """
    bias_score: float = Field(
        ge=-0.05, le=0.05,
        description="LLM contribution to bias score. Cap enforced: ±0.05."
    )
    direction: Direction = Field(
        description="Overall fundamental direction for the currency"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in the fundamental assessment"
    )
    reasoning: str = Field(
        min_length=20, max_length=800,
        description="Narrative explanation of the fundamental view"
    )
    key_drivers: list[str] = Field(
        default_factory=list,
        min_length=1, max_length=5,
        description="Top factors driving the fundamental outlook (e.g., 'CPI surprise', 'rate differential')"
    )
    data_quality: float = Field(
        ge=0.0, le=1.0,
        default=0.5,
        description="Quality/reliability of the fundamental data available (1.0 = complete)"
    )
    stale: bool = Field(
        default=False,
        description="Whether the fundamental data is stale (>24h old)"
    )

    @field_validator("bias_score")
    @classmethod
    def clamp_bias_contribution(cls, v: float) -> float:
        """Hard-enforce the 0.05 cap on LLM bias contribution."""
        return max(-0.05, min(0.05, v))


# ── TradeThesisOutput ────────────────────────────────────────────────

class TradeThesisOutput(BaseModel):
    """Structured output from TradeThesisAgent — the case FOR a trade.

    Contains specific stop-loss and take-profit reasoning in addition to
    signal assessment. Every element must be justified by evidence.
    """
    signal: TradeSignal = Field(description="BUY, SELL, or NO_TRADE")
    confidence: float = Field(ge=0.0, le=1.0, description="Conviction in the thesis")
    rationale: str = Field(
        min_length=30, max_length=1000,
        description="The complete trade narrative — why this setup works"
    )
    risks: list[Risk] = Field(
        default_factory=list,
        min_length=1,
        description="Risks to this trade (minimum 1 required)"
    )
    key_levels: list[KeyLevel] = Field(
        default_factory=list,
        description="Significant price levels (S/R, order blocks, liquidity zones)"
    )
    stop_loss_reasoning: str = Field(
        min_length=10, max_length=300,
        description="Why this specific stop-loss level was chosen"
    )
    stop_loss_price: float | None = Field(
        default=None,
        description="Specific stop-loss price level"
    )
    take_profit_reasoning: str = Field(
        min_length=10, max_length=300,
        description="Why this specific take-profit target was chosen"
    )
    take_profit_price: float | None = Field(
        default=None,
        description="Specific take-profit price level"
    )
    evidence_for: list[str] = Field(
        default_factory=list,
        description="Evidence supporting the trade"
    )
    evidence_against: list[str] = Field(
        default_factory=list,
        description="Evidence challenging the trade"
    )
    agent_agreement: float = Field(
        ge=0.0, le=1.0,
        description="Fraction of contributing agents that agree with this direction"
    )


# ── DevilsAdvocateOutput ─────────────────────────────────────────────

class DevilsAdvocateOutput(BaseModel):
    """Structured output from DevilsAdvocateAgent — the case AGAINST a trade.

    Must output at least 2 specific issues OR approve with justification.
    No vague objections — every issue must be concrete and falsifiable.
    """
    verdict: Verdict = Field(
        description="approve (thesis is sound), reject (fatal flaw), or needs_revision (fixable issues)"
    )
    issues: list[str] = Field(
        default_factory=list,
        min_length=0,
        description="Specific, concrete objections — minimum 2 if verdict is reject/needs_revision"
    )
    alternative_view: str = Field(
        min_length=10, max_length=800,
        description="What the opposing trade setup would look like"
    )
    worst_case_scenario: str = Field(
        min_length=10, max_length=300,
        description="The worst specific outcome if this trade goes wrong"
    )
    confidence_reduction: float = Field(
        ge=0.0, le=0.5,
        description="How much should the CIO reduce confidence? 0.0 = no reduction"
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="What information is missing that would strengthen the thesis?"
    )
    justification: str = Field(
        max_length=500, default="",
        description="Justification if approving the trade"
    )

    @field_validator("issues")
    @classmethod
    def require_two_issues_unless_approved(cls, v: list[str], info) -> list[str]:
        """If verdict is reject or needs_revision, require at least 2 issues."""
        verdict_val = info.data.get("verdict")
        if verdict_val in (Verdict.REJECT, Verdict.NEEDS_REVISION):
            if len(v) < 2:
                raise ValueError(
                    f"Devil's Advocate must provide at least 2 specific issues "
                    f"when verdict is '{verdict_val}'"
                )
        return v

    @field_validator("justification")
    @classmethod
    def require_justification_if_approved(cls, v: str, info) -> str:
        """If verdict is approve, must provide justification."""
        verdict_val = info.data.get("verdict")
        if verdict_val == Verdict.APPROVE and not v:
            raise ValueError(
                "Devil's Advocate must provide justification when approving the trade"
            )
        return v


# ── CIOOutput ────────────────────────────────────────────────────────

class CIOOutput(BaseModel):
    """Structured output from CIOAgent — the final trading decision.

    Decision is binary (BUY/SELL/NO_TRADE) with explicit conditions.
    MUST reference evidence from all 3 prior agents:
    - Thesis (case FOR)
    - Devil's Advocate (case AGAINST)
    - Fundamental Bias (macro/fundamental context)
    """
    final_decision: TradeSignal = Field(
        description="BUY, SELL, or NO_TRADE — the binding decision"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the decision")
    position_size_override: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Override position size as fraction of max (None = use default sizing)"
    )
    conditions: list[str] = Field(
        default_factory=list,
        description="Conditions that must hold for the decision to remain valid"
    )
    rationale: str = Field(
        min_length=30, max_length=1000,
        description="Complete reasoning, referencing evidence from Thesis, Devil's Advocate, and Fundamental Bias"
    )
    thesis_evidence: str = Field(
        min_length=5, max_length=300,
        description="Key evidence FROM the Trade Thesis that was most influential"
    )
    devil_evidence: str = Field(
        min_length=5, max_length=300,
        description="Key evidence FROM the Devil's Advocate that was most influential"
    )
    fundamental_evidence: str = Field(
        min_length=5, max_length=300,
        description="Key evidence FROM the Fundamental Bias that was most influential"
    )
    dissenting_agents: list[str] = Field(
        default_factory=list,
        description="Analysis agents that disagreed with the final decision"
    )
    risk_checks_passed: bool = Field(
        default=False,
        description="Whether risk management checks were satisfied"
    )


# ── LearningOutput ───────────────────────────────────────────────────

class ParameterAdjustment(BaseModel):
    """A specific adjustment to a system parameter based on learning."""
    parameter_path: str = Field(
        min_length=1, max_length=200,
        description="Dot-path to the parameter, e.g. 'risk.max_position_size'"
    )
    current_value: float | str | None = Field(default=None)
    suggested_value: float | str
    reason: str = Field(min_length=10, max_length=300)
    priority: float = Field(ge=0.0, le=1.0, default=0.5, description="How urgent this adjustment is")


class LearningOutput(BaseModel):
    """Structured output from LearningAgent — post-trade reflection.

    Tracks patterns across trades to build an institutional memory of what works.
    """
    pattern_type: PatternType = Field(
        description="The type of pattern/setup that this trade represents"
    )
    lessons: list[str] = Field(
        default_factory=list,
        min_length=1, max_length=5,
        description="Specific, actionable lessons learned (minimum 1)"
    )
    parameter_adjustments: list[ParameterAdjustment] = Field(
        default_factory=list,
        description="System parameters to adjust based on this trade"
    )
    what_worked: list[str] = Field(
        default_factory=list,
        description="Aspects of analysis that were correct"
    )
    what_failed: list[str] = Field(
        default_factory=list,
        description="Aspects of analysis that were wrong or misleading"
    )
    should_repeat: bool = Field(
        description="Should we look for this type of setup again?"
    )
    repeat_confidence: float = Field(
        ge=0.0, le=1.0, default=0.5,
        description="Confidence in repeating this pattern type in the future"
    )
    similar_trades_count: int = Field(
        ge=0, default=0,
        description="Number of similar trade patterns in memory"
    )


# ═══════════════════════════════════════════════════════════════════════
# Model Tier Configuration Loader
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ModelTierConfig:
    """A single model tier configuration loaded from YAML."""
    name: str
    primary: str | None
    fallback: str
    temperature: float
    max_tokens: int
    latency_budget_s: float
    rpm_limit: int
    description: str = ""


@dataclass
class ProviderConfig:
    """LLM provider configuration."""
    name: str
    base_url: str
    api_key_env: str
    provider_type: str  # "openai", "openai_compatible", "anthropic"


@dataclass
class InstructorConfig:
    """Instructor configuration."""
    mode: str = "md_json"          # md_json | json | function_calling | tool_calls
    max_retries: int = 3
    validation_context: bool = True


@dataclass
class CostRate:
    """Cost per 1M tokens for a model."""
    input: float
    output: float


def load_model_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load model tier configuration from YAML.

    Args:
        config_path: Path to llm_models.yaml. Uses default location if None.

    Returns:
        Parsed config dict with tiers, providers, instructor, and cost data.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "llm_models.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        logger.warning("model_config_missing", path=str(config_path))
        return _default_config()

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    return raw


def _default_config() -> dict[str, Any]:
    """Fallback config when llm_models.yaml is missing."""
    return {
        "tiers": {
            "decision": {"primary": "claude-4-opus", "fallback": "claude-4-sonnet", "temperature": 0.1, "max_tokens": 2048, "latency_budget_s": 12.0, "rpm_limit": 20},
            "analysis": {"primary": "claude-4-sonnet", "fallback": "gpt-5-mini", "temperature": 0.2, "max_tokens": 1536, "latency_budget_s": 8.0, "rpm_limit": 40},
            "fast": {"primary": "claude-4-haiku", "fallback": "gpt-5-mini", "temperature": 0.0, "max_tokens": 1024, "latency_budget_s": 3.0, "rpm_limit": 100},
            "local": {"primary": None, "fallback": "claude-4-haiku", "temperature": 0.1, "max_tokens": 1024, "latency_budget_s": 5.0, "rpm_limit": 60},
        },
        "providers": {
            "nvidia_nim": {"base_url": "https://integrate.api.nvidia.com/v1", "api_key_env": "NVIDIA_NIM_API_KEY", "type": "openai_compatible"},
        },
        "instructor": {"mode": "md_json", "max_retries": 3, "validation_context": True},
        "cost_per_1m_tokens": {},
    }


def parse_tiers(raw: dict[str, Any]) -> dict[str, ModelTierConfig]:
    """Parse raw tier config into typed ModelTierConfig objects."""
    tiers = {}
    for name, data in raw.get("tiers", {}).items():
        tiers[name] = ModelTierConfig(
            name=name,
            primary=data.get("primary"),
            fallback=data.get("fallback", ""),
            temperature=data.get("temperature", 0.1),
            max_tokens=data.get("max_tokens", 1024),
            latency_budget_s=data.get("latency_budget_s", 5.0),
            rpm_limit=data.get("rpm_limit", 40),
            description=data.get("description", ""),
        )
    return tiers


def parse_providers(raw: dict[str, Any]) -> dict[str, ProviderConfig]:
    """Parse raw provider config into typed ProviderConfig objects."""
    providers = {}
    for name, data in raw.get("providers", {}).items():
        providers[name] = ProviderConfig(
            name=name,
            base_url=data.get("base_url", ""),
            api_key_env=data.get("api_key_env", ""),
            provider_type=data.get("type", "openai_compatible"),
        )
    return providers


def get_cost_rates(raw: dict[str, Any]) -> dict[str, CostRate]:
    """Parse cost-per-1M-tokens data."""
    costs = {}
    for model, data in raw.get("cost_per_1m_tokens", {}).items():
        costs[model] = CostRate(
            input=data.get("input", 0.0),
            output=data.get("output", 0.0),
        )
    return costs


# ═══════════════════════════════════════════════════════════════════════
# Cost Tracker
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CostEvent:
    """A single cost-tracking event."""
    model: str
    tier: str
    agent: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    timestamp: float = field(default_factory=time.time)


class CostTracker:
    """Tracks LLM API costs per model, tier, and agent.

    Aggregates costs for monitoring and optimization decisions.
    """

    def __init__(self):
        self._events: list[CostEvent] = []
        self._cost_rates: dict[str, CostRate] = {}
        # Aggregates
        self._total_cost: float = 0.0
        self._by_tier: dict[str, float] = {}
        self._by_agent: dict[str, float] = {}
        self._by_model: dict[str, float] = {}

    def set_cost_rates(self, rates: dict[str, CostRate]) -> None:
        self._cost_rates = rates

    def record(
        self,
        model: str,
        tier: str,
        agent: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> None:
        """Record a cost event."""
        rates = self._cost_rates.get(model)
        if rates:
            cost = (input_tokens / 1_000_000) * rates.input + (output_tokens / 1_000_000) * rates.output
        else:
            cost = 0.0  # Unknown model = untracked cost

        event = CostEvent(
            model=model,
            tier=tier,
            agent=agent,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
        )
        self._events.append(event)

        self._total_cost += cost
        self._by_tier[tier] = self._by_tier.get(tier, 0.0) + cost
        self._by_agent[agent] = self._by_agent.get(agent, 0.0) + cost
        self._by_model[model] = self._by_model.get(model, 0.0) + cost

        logger.debug(
            "cost_tracked",
            model=model,
            tier=tier,
            agent=agent,
            cost_usd=round(cost, 6),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost_usd=round(self._total_cost, 4),
        )

    @property
    def summary(self) -> dict[str, Any]:
        """Return cost summary for monitoring."""
        return {
            "total_cost_usd": round(self._total_cost, 6),
            "total_events": len(self._events),
            "by_tier": {k: round(v, 6) for k, v in self._by_tier.items()},
            "by_agent": {k: round(v, 6) for k, v in self._by_agent.items()},
            "by_model": {k: round(v, 6) for k, v in self._by_model.items()},
        }

    def reset(self) -> None:
        """Reset all tracking — use when starting a new session."""
        self._events.clear()
        self._total_cost = 0.0
        self._by_tier.clear()
        self._by_agent.clear()
        self._by_model.clear()


# ═══════════════════════════════════════════════════════════════════════
# LLMStructuredClient — instructor-patched client for typed outputs
# ═══════════════════════════════════════════════════════════════════════

class LLMStructuredClient:
    """Production-grade client for type-safe structured LLM outputs.

    Wraps the NIM client (or any OpenAI-compatible API) with instructor patching
    to guarantee Pydantic-valid responses on every call.

    Features:
    - instructor.patch() for automatic JSON → Pydantic validation
    - Retry with exponential backoff on ValidationError
    - Cost tracking per model/tier/agent
    - structlog integration for all calls
    - Fundamental bias contribution enforcement (0.05 cap)

    Usage:
        client = LLMStructuredClient(api_key="nvapi-...", base_url="https://...")
        result = await client.complete(
            model="claude-4-sonnet",
            prompt="Analyze this setup...",
            response_model=TradeThesisOutput,
            tier="analysis",
            agent_name="trade-thesis",
        )
        # result is a validated TradeThesisOutput instance. Guaranteed.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        provider: str = "nvidia_nim",
        config_path: str | Path | None = None,
        default_tier: str = "analysis",
    ):
        # Load config
        raw_config = load_model_config(config_path)
        self._tiers = parse_tiers(raw_config)
        self._providers = parse_providers(raw_config)
        self._instructor_config = InstructorConfig(
            mode=raw_config.get("instructor", {}).get("mode", "md_json"),
            max_retries=raw_config.get("instructor", {}).get("max_retries", 3),
            validation_context=raw_config.get("instructor", {}).get("validation_context", True),
        )
        self._cost_rates = get_cost_rates(raw_config)

        # Select provider
        provider_cfg = self._providers.get(provider)
        if not provider_cfg:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(self._providers)}")

        self._base_url = base_url or provider_cfg.base_url
        self._api_key = api_key or os.getenv(provider_cfg.api_key_env, "")
        self._provider_type = provider_cfg.provider_type
        self._default_tier = default_tier

        # Cost tracking
        self.cost_tracker = CostTracker()
        self.cost_tracker.set_cost_rates(self._cost_rates)

        # Lazy-initialized instructor client
        self._instructor_client = None
        self._openai_client = None

        # Metrics
        self._total_calls = 0
        self._total_validation_failures = 0
        self._total_fallback_used = 0

    def _ensure_client(self):
        """Lazy-init the instructor-patched client."""
        if self._instructor_client is not None:
            return

        try:
            import instructor
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "LLMStructuredClient requires 'instructor' and 'openai' packages. "
                "Install with: pip install instructor openai"
            ) from e

        self._openai_client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=60.0,
            max_retries=0,  # We handle retries ourselves
        )

        # Patch with instructor — this is the magic
        self._instructor_client = instructor.from_openai(
            self._openai_client,
            mode=getattr(instructor.Mode, self._instructor_config.mode.upper(), instructor.Mode.MD_JSON),
        )

        logger.info(
            "instructor_client_initialized",
            provider=self._provider_type,
            base_url=self._base_url[:50],
            mode=self._instructor_config.mode,
        )

    async def complete(
        self,
        model: str,
        prompt: str,
        response_model: type[T],
        system_prompt: str = "",
        tier: str | None = None,
        agent_name: str = "unknown",
        temperature: float | None = None,
        max_tokens: int | None = None,
        messages: list[dict[str, str]] | None = None,
        validation_context: dict[str, Any] | None = None,
    ) -> T:
        """Get a validated structured output from the LLM.

        Args:
            model: Model name (e.g., 'claude-4-sonnet')
            prompt: The user prompt
            response_model: Pydantic model to validate against
            system_prompt: System prompt / instructions
            tier: Model tier name (for config lookup). Overrides model if set.
            agent_name: Name of calling agent (for logging/cost tracking)
            temperature: Override temperature
            max_tokens: Override max_tokens
            messages: Full message list (overrides prompt/system_prompt if set)
            validation_context: Extra context passed to Pydantic validators

        Returns:
            Validated instance of response_model

        Raises:
            ValueError: If all retries fail validation
            RuntimeError: On API failures after max retries
        """
        self._ensure_client()
        assert self._instructor_client is not None

        # Resolve tier config
        tier_name = tier or self._default_tier
        tier_cfg = self._tiers.get(tier_name)

        # Build messages
        if messages is None:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

        # Resolve parameters with tier defaults
        temp = temperature if temperature is not None else (tier_cfg.temperature if tier_cfg else 0.1)
        tokens = max_tokens or (tier_cfg.max_tokens if tier_cfg else 1024)

        # Track cost-relevant info
        effective_model = model

        # Retry loop with exponential backoff
        max_retries = self._instructor_config.max_retries
        last_error = None

        for attempt in range(max_retries + 1):
            start = time.monotonic()
            try:
                # instructor-patched call — returns validated response_model
                response, completion = await self._instructor_client.chat.completions.create_with_completion(
                    model=effective_model,
                    response_model=response_model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=tokens,
                    validation_context=validation_context,
                )

                elapsed_ms = (time.monotonic() - start) * 1000

                # Extract token usage for cost tracking
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

                logger.warning(
                    "structured_completion_retry",
                    agent=agent_name,
                    model=effective_model,
                    attempt=attempt + 1,
                    error=error_name,
                    error_msg=str(e)[:200],
                    latency_ms=round(elapsed_ms, 1),
                )

                # If it's a validation error (instructor raises these),
                # retry with the error message as context
                if "validation" in error_name.lower() or "pydantic" in error_name.lower():
                    self._total_validation_failures += 1

                # Try fallback model if primary fails and we have one
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

                # Exponential backoff
                if attempt < max_retries:
                    wait = min(2 ** attempt, 8) + 0.5 * attempt
                    await asyncio.sleep(wait)

        # All retries exhausted
        self._total_calls += 1
        logger.error(
            "structured_completion_failed",
            agent=agent_name,
            model=effective_model,
            tier=tier_name,
            retries=max_retries,
            last_error=str(last_error)[:300],
        )
        raise RuntimeError(
            f"LLMStructuredClient: Failed to get valid {response_model.__name__} "
            f"from {effective_model} after {max_retries + 1} attempts. "
            f"Last error: {last_error}"
        )

    def validate_bias_contribution(self, bias_output: FundamentalBiasOutput) -> FundamentalBiasOutput:
        """Enforce the 0.05 cap on LLM fundamental bias contribution.

        This is the hard guarantee: LLM narrative cannot push the fundamental
        bias beyond ±0.05, regardless of what the LLM returns.

        Args:
            bias_output: The FundamentalBiasOutput from the LLM

        Returns:
            Same object with bias_score clamped to [-0.05, 0.05]

        Note:
            The Pydantic field_validator on FundamentalBiasOutput.bias_score
            already enforces this at the model level. This method is a
            secondary enforcement for audit/review purposes.
        """
        original = bias_output.bias_score
        clamped = max(-0.05, min(0.05, original))

        if abs(clamped - original) > 1e-9:
            logger.warning(
                "bias_contribution_clamped",
                original=round(original, 4),
                clamped=round(clamped, 4),
                reasoning=bias_output.reasoning[:100],
            )
            bias_output.bias_score = clamped

        return bias_output

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._openai_client:
            await self._openai_client.close()
            self._instructor_client = None
            self._openai_client = None
            logger.info("instructor_client_closed")

    @property
    def metrics(self) -> dict[str, Any]:
        """Return client metrics for monitoring."""
        return {
            "total_calls": self._total_calls,
            "validation_failures": self._total_validation_failures,
            "validation_failure_rate": round(
                self._total_validation_failures / self._total_calls * 100, 1
            ) if self._total_calls else 0,
            "fallback_used": self._total_fallback_used,
            "cost": self.cost_tracker.summary,
        }


# ═══════════════════════════════════════════════════════════════════════
# PydanticAI-style Agent Definition Helper
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class StructuredAgentConfig:
    """Configuration for a PydanticAI-style structured agent.

    Provides a declarative way to define agents with typed input/output models.
    Mirrors PydanticAI's Agent class pattern without requiring the full framework.
    """
    name: str
    role: str
    system_prompt: str
    response_model: type[BaseModel]
    tier: str = "analysis"
    temperature: float | None = None
    max_tokens: int | None = None

    def build_messages(self, context: dict[str, Any]) -> list[dict[str, str]]:
        """Build chat messages from context. Override for custom formatting."""
        messages = [{"role": "system", "content": self.system_prompt}]
        parts = []
        for key, value in context.items():
            if isinstance(value, (str, int, float, bool)):
                parts.append(f"{key}: {value}")
            elif isinstance(value, dict):
                parts.append(f"{key}: {value}")
            elif isinstance(value, list) and len(value) < 20:
                parts.append(f"{key}: {value}")
        messages.append({"role": "user", "content": "\n".join(parts)})
        return messages

    def get_model(self, tiers: dict[str, ModelTierConfig]) -> str:
        """Resolve the primary model for this tier."""
        tier_cfg = tiers.get(self.tier)
        if tier_cfg and tier_cfg.primary:
            return tier_cfg.primary
        return "claude-4-sonnet"  # Ultimate fallback
