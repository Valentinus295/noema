# Changelog

All notable changes to Noema are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-06-24 — Phases 2-6: Full Platform

### Phase 2: Noema Nexus — Actor-Critic Architecture
- **3 agent teams**: Analysis (Actor), Critic (Judge), Execution (Doer)
- **Debate Engine 2.0**: Semantic debate, 3 rounds, deterministic ConservativeTiebreaker vote
- **Conductor**: Meta-cognition, per-agent performance tracking, anomaly detection
- **TypedMessageBus**: Priority + TTL + dead letter queue
- **Config-driven architecture**: `--architecture flat|teams|actor_critic|nexus`
- Full backward compatibility: flat = existing 5-layer wave
- Zero LLM decision authority — LLM generates arguments, math decides the trade

### Phase 3: Multi-Symbol / Multi-Timeframe
- Per-symbol orchestrators with fleet-wide coordination
- 4-timeframe alignment (HTF direction + LTF entry)
- Real-time correlation matrix across all pairs
- Fleet-wide drawdown kill-switch (15% threshold)
- Capital allocation with trend/correlation/P&L bonuses
- Pure math — zero LLM in allocation decisions

### Phase 4: Self-Learning & Memory
- 4-layer memory system: episodic, semantic, working, procedural
- 3 self-improvement loops: real-time agent weighting, daily consolidation, weekly genetic evolution
- 15 learnable skills: pattern recognition through trade execution
- Anti-catastrophic forgetting via Elastic Weight Consolidation (EWC)
- LearningSafeguards with Guardian kill-switch #16

### Phase 5: Institutional Features
- Multi-broker gateway (FxPesa + FBS + Custom)
- FIX protocol stub for institutional connectivity
- Position reconciliation across brokers
- 7-year audit-compliant trade journal (PostgreSQL + DuckDB)
- Lot-protection hardware barrier (max lot from broker config)

### Phase 6: Production Hardening
- Graceful 5-phase shutdown sequence
- Kubernetes health endpoints (liveness/readiness/startup)
- Secret redaction across all log levels
- Config validation on startup
- systemd auto-boot service
- Full backup/restore with verification
- Docker Compose with resource limits and healthchecks
- OpenTelemetry + Langfuse tracing + Prometheus metrics

### Setup Fixes (v0.2.0)
- Python 3.11+ version enforcement with OS-specific upgrade paths
- System dependency auto-install (build-essential, cmake, libta-lib-dev, python3-venv)
- Pop!_OS Docker repo compatibility (codename mapping)
- Docker Compose detection: both v2 plugin and standalone
- Pipe exit code capture across npm, Docker, and build steps
- Grafana port changed to 3001 (avoids dashboard collision)
- MT5 path auto-detection across common Wine install locations
- Dashboard API server dependencies auto-installed
- Rust build failure messaging with specific fix instructions
- Docker password generation fixed (pre-computed, not literal heredoc)

## [0.1.0] — 2026-06-23 — Phase 1: Statistical & Econometric Core
