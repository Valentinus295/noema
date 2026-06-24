"""Agent Team Manager — Manages agent teams (Analysis, Critic, Execution).

Part of Phase 2: Noema Nexus — Actor-Critic Architecture.

TeamManager is the orchestration layer that:
1. Groups agents into three teams: Analysis (Actor), Critic, Execution
2. Executes agents within each team in parallel via asyncio.gather
3. Monitors team-level health
4. Supports config-driven architecture modes: flat → teams → actor_critic → nexus
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import structlog

from noema.core.modern_agent import BaseAgent, AgentReport, AgentType, HealthStatus
from noema.core.typed_messages import (
    TypedMessage, MessageType, MessagePriority,
    AnalysisResultPayload, ProposalFeedback,
)
from noema.core.conservative_tiebreaker import ConservativeTiebreaker, TiebreakerDecision, TiebreakerResult

logger = structlog.get_logger(__name__)


class ArchitectureMode(str, Enum):
    """Deployment architecture modes — phased migration path.

    flat:       Original 5-layer pipeline (backward compatible)
    teams:      Agent teams with parallel execution (Phase 2 default)
    actor_critic: Actor-Critic with debate engine (Phase 2.5)
    nexus:      Full Nexus with Conductor meta-cognition (Phase 3)
    """
    FLAT = "flat"
    TEAMS = "teams"
    ACTOR_CRITIC = "actor_critic"
    NEXUS = "nexus"


class TeamType(str, Enum):
    """Team classification for the actor-critic pattern."""
    ANALYSIS = "analysis"   # Actor team — generates proposals
    CRITIC = "critic"       # Critic team — evaluates proposals
    EXECUTION = "execution" # Execution team — places/manages orders


@dataclass
class TeamHealth:
    """Health status for a team of agents."""
    team_type: TeamType
    agent_count: int = 0
    healthy_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0
    avg_latency_ms: float = 0.0
    last_success_at: float = 0.0
    consecutive_failures: int = 0
    is_operational: bool = False
    status: str = "UNKNOWN"  # HEALTHY, DEGRADED, FAILED, ISOLATED

    @property
    def health_score(self) -> float:
        """Team health score 0-100."""
        if self.agent_count == 0:
            return 0.0
        return (self.healthy_count / self.agent_count) * 100.0


@dataclass
class TeamResult:
    """Result from a team's execution cycle."""
    team_type: TeamType
    reports: dict[str, AgentReport] = field(default_factory=dict)
    health: TeamHealth = field(default_factory=lambda: TeamHealth(team_type=TeamType.ANALYSIS))
    latency_ms: float = 0.0
    error: str | None = None


class TeamManager:
    """Manages agent teams with parallel execution and health monitoring.

    The TeamManager is the bridge between the ModernOrchestrator's
    wave-based pipeline and the Phase 2 team-based architecture.

    Usage:
        manager = TeamManager(mode=ArchitectureMode.TEAMS)
        manager.register_team(TeamType.ANALYSIS, analysis_agents)
        result = await manager.run_analysis_team(context)
    """

    def __init__(
        self,
        mode: ArchitectureMode = ArchitectureMode.TEAMS,
        config: Any = None,
    ):
        self.mode = mode
        self.config = config
        self._teams: dict[TeamType, list[BaseAgent]] = {
            TeamType.ANALYSIS: [],
            TeamType.CRITIC: [],
            TeamType.EXECUTION: [],
        }
        self._team_health: dict[TeamType, TeamHealth] = {
            TeamType.ANALYSIS: TeamHealth(team_type=TeamType.ANALYSIS),
            TeamType.CRITIC: TeamHealth(team_type=TeamType.CRITIC),
            TeamType.EXECUTION: TeamHealth(team_type=TeamType.EXECUTION),
        }
        self._consecutive_failures: dict[TeamType, int] = {
            TeamType.ANALYSIS: 0,
            TeamType.CRITIC: 0,
            TeamType.EXECUTION: 0,
        }
        self._logger = logger.bind(component="team_manager")

    # ── Team Registration ────────────────────────────────────────────

    def register_team(self, team_type: TeamType, agents: list[BaseAgent]) -> None:
        """Register agents to a team. Replaces any existing agents."""
        self._teams[team_type] = agents
        self._logger.info(
            "team_registered",
            team=team_type.value,
            agent_count=len(agents),
            agent_names=[a.name for a in agents],
        )

    def get_team(self, team_type: TeamType) -> list[BaseAgent]:
        """Get the agents registered for a team."""
        return self._teams.get(team_type, [])

    def get_agent(self, name: str) -> BaseAgent | None:
        """Find an agent by name across all teams."""
        for team in self._teams.values():
            for agent in team:
                if agent.name == name:
                    return agent
        return None

    # ── Team Execution ───────────────────────────────────────────────

    async def run_team(
        self,
        team_type: TeamType,
        context: dict[str, Any],
        symbol: str = "",
    ) -> TeamResult:
        """Execute all agents in a team in parallel.

        Args:
            team_type: Which team to execute.
            context: Shared context dictionary for all agents.
            symbol: Trading symbol for logging/tracing.

        Returns:
            TeamResult with all agent reports and health status.
        """
        agents = self._teams.get(team_type, [])
        if not agents:
            self._logger.warning("team_empty", team=team_type.value)
            return TeamResult(
                team_type=team_type,
                health=TeamHealth(team_type=team_type, status="EMPTY"),
            )

        team_start = time.monotonic()
        self._logger.debug("team_execution_start", team=team_type.value, agents=len(agents))

        # ── Execute all agents in parallel ──
        async def _process_agent(agent: BaseAgent) -> tuple[str, AgentReport | Exception]:
            try:
                report = await agent.process(context)
                return (agent.name, report)
            except Exception as e:
                self._logger.error(
                    "team_agent_failed",
                    team=team_type.value,
                    agent=agent.name,
                    error=str(e),
                )
                return (agent.name, e)

        results = await asyncio.gather(
            *[_process_agent(agent) for agent in agents],
            return_exceptions=False,
        )

        # ── Collect results ──
        reports: dict[str, AgentReport] = {}
        healthy = 0
        failed = 0
        total_latency = 0.0

        for name, result in results:
            if isinstance(result, Exception):
                failed += 1
                reports[name] = AgentReport(
                    agent_name=name,
                    signal="ERROR",
                    reasoning=str(result),
                )
            else:
                healthy += 1
                reports[name] = result
                if hasattr(result, 'llm_latency_ms'):
                    total_latency += result.llm_latency_ms

        team_latency_ms = (time.monotonic() - team_start) * 1000

        # ── Update health ──
        health = TeamHealth(
            team_type=team_type,
            agent_count=len(agents),
            healthy_count=healthy,
            degraded_count=0,
            failed_count=failed,
            avg_latency_ms=total_latency / max(healthy, 1),
            last_success_at=time.monotonic() if healthy > 0 else 0,
            consecutive_failures=self._consecutive_failures.get(team_type, 0),
            is_operational=healthy > 0,
            status="HEALTHY" if failed == 0 else ("DEGRADED" if healthy > 0 else "FAILED"),
        )
        self._team_health[team_type] = health

        if failed > 0:
            self._consecutive_failures[team_type] = self._consecutive_failures.get(team_type, 0) + 1
        else:
            self._consecutive_failures[team_type] = 0

        self._logger.info(
            "team_execution_complete",
            team=team_type.value,
            agents=len(agents),
            healthy=healthy,
            failed=failed,
            latency_ms=round(team_latency_ms, 1),
            status=health.status,
        )

        return TeamResult(
            team_type=team_type,
            reports=reports,
            health=health,
            latency_ms=team_latency_ms,
        )

    async def run_pipeline(
        self,
        symbol: str,
        data_context: dict[str, Any],
        analysis_context: dict[str, Any],
        decision_context: dict[str, Any],
        execution_context: dict[str, Any] | None = None,
    ) -> dict[str, TeamResult]:
        """Execute the full team-based pipeline.

        In teams mode:
        1. Analysis team runs in parallel (all analysis agents)
        2. Critic team evaluates analysis team output
        3. Execution team places orders if approved

        This replaces the 5-layer wave pattern for teams/actor_critic/nexus modes.

        Args:
            symbol: Trading symbol.
            data_context: Context with market data.
            analysis_context: Context for analysis agents.
            decision_context: Context for critic/decision agents.
            execution_context: Context for execution agents (optional).

        Returns:
            Dictionary mapping team type to TeamResult.
        """
        pipeline_results: dict[str, TeamResult] = {}

        # ── Phase 1: Analysis Team (parallel) ──
        analysis_result = await self.run_team(
            TeamType.ANALYSIS, analysis_context, symbol
        )
        pipeline_results["analysis"] = analysis_result

        # ── Phase 2: Critic Team (parallel, after analysis) ──
        # Inject analysis results into critic context
        critic_context = dict(decision_context)
        critic_context["analysis"] = {
            name: report.data for name, report in analysis_result.reports.items()
        }
        critic_context["analysis_signals"] = {
            name: report.signal for name, report in analysis_result.reports.items()
        }
        critic_context["analysis_confidence"] = {
            name: report.confidence for name, report in analysis_result.reports.items()
        }

        critic_result = await self.run_team(
            TeamType.CRITIC, critic_context, symbol
        )
        pipeline_results["critic"] = critic_result

        # ── Phase 3: Execution Team (if trade approved) ──
        if execution_context:
            execution_result = await self.run_team(
                TeamType.EXECUTION, execution_context, symbol
            )
            pipeline_results["execution"] = execution_result

        return pipeline_results

    # ── Health Monitoring ───────────────────────────────────────────

    def get_team_health(self, team_type: TeamType) -> TeamHealth:
        """Get current health status for a team."""
        return self._team_health.get(team_type, TeamHealth(team_type=team_type))

    def get_all_health(self) -> dict[TeamType, TeamHealth]:
        """Get health status for all teams."""
        return dict(self._team_health)

    def is_team_operational(self, team_type: TeamType) -> bool:
        """Check if a team is operational (at least one healthy agent)."""
        return self._team_health.get(team_type, TeamHealth(team_type=team_type)).is_operational

    def get_operational_summary(self) -> dict[str, Any]:
        """Get a summary of operational status for all teams."""
        teams_status = {}
        for team_type, health in self._team_health.items():
            teams_status[team_type.value] = {
                "status": health.status,
                "healthy": health.healthy_count,
                "total": health.agent_count,
                "score": health.health_score,
                "consecutive_failures": health.consecutive_failures,
            }
        return {
            "mode": self.mode.value,
            "teams": teams_status,
            "all_operational": all(
                h.is_operational or h.agent_count == 0
                for h in self._team_health.values()
            ),
        }

    # ── Architecture Mode Helpers ───────────────────────────────────

    @property
    def is_flat_mode(self) -> bool:
        """True if running in flat (original pipeline) mode."""
        return self.mode == ArchitectureMode.FLAT

    @property
    def is_teams_mode(self) -> bool:
        """True if running in teams mode or higher."""
        return self.mode in (ArchitectureMode.TEAMS, ArchitectureMode.ACTOR_CRITIC, ArchitectureMode.NEXUS)

    @property
    def is_actor_critic_mode(self) -> bool:
        """True if running in actor_critic mode or higher."""
        return self.mode in (ArchitectureMode.ACTOR_CRITIC, ArchitectureMode.NEXUS)

    @property
    def is_nexus_mode(self) -> bool:
        """True if running in full nexus mode."""
        return self.mode == ArchitectureMode.NEXUS

    # ── Conductor Integration (Phase 2.5+) ──────────────────────────

    async def report_to_conductor(self, conductor: Any) -> None:
        """Send team performance data to the Conductor for meta-cognition.

        Args:
            conductor: Conductor instance (from noema.core.conductor).
        """
        for team_type, health in self._team_health.items():
            await conductor.record_team_health(
                team_type=team_type.value,
                health_score=health.health_score,
                agent_count=health.agent_count,
                healthy_count=health.healthy_count,
                avg_latency_ms=health.avg_latency_ms,
            )
