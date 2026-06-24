# Noema Grafana Dashboard Setup
# ==============================
#
# This directory contains Grafana dashboard JSON definitions.
# Dashboards are automatically provisioned by Grafana when the container starts
# (configured via config/grafana-dashboards.yml provisioner).
#
# ## Creating Dashboards
#
# 1. Start Grafana: `docker compose up -d grafana`
# 2. Open http://localhost:3000 (admin/admin)
# 3. Create your dashboard in the UI
# 4. Export as JSON: Share → Export → "Export for sharing externally"
# 5. Save the JSON to this directory
# 6. Commit it — next `docker compose up` will load it automatically
#
# ## Recommended Dashboards
#
# ### 1. Noema System Overview (`noema-overview.json`)
# Full system health dashboard:
#   - Prometheus: `up{job="noema-app"}` — app health
#   - Redis: connected clients, memory usage, hit rate
#   - PostgreSQL: active connections, query latency
#   - System: CPU, memory, disk for host
#
# ### 2. Trading Performance (`noema-trading.json`)
# Real-time trading metrics:
#   - `noema_positions_open` — current open positions
#   - `noema_daily_pnl` — daily P&L gauge
#   - `noema_trades_total` — cumulative trade counter
#   - `noema_win_rate` — rolling win rate
#   - `noema_cycle_duration_seconds` — orchestrator loop timing
#
# ### 3. Agent Activity (`noema-agents.json`)
# Agent-level metrics:
#   - `noema_agent_decisions_total{agent="..."}` — decisions per agent
#   - `noema_agent_latency_seconds{agent="..."}` — latency per agent
#   - `noema_signals_generated_total` — signal pipeline throughput
#
# ## Prometheus Metrics Reference
#
# All Noema metrics are prefixed with `noema_` and exposed at `/metrics`.
# See `noema/observability/metrics.py` for the full registry.
#
# ## Adding Grafana Plugins
#
# Add plugin IDs to the GF_INSTALL_PLUGINS env var in docker-compose.yml:
#   GF_INSTALL_PLUGINS: "grafana-piechart-panel,grafana-worldmap-panel"
#
# Or install manually:
#   docker exec noema-grafana grafana-cli plugins install <plugin-id>
#   docker compose restart grafana
