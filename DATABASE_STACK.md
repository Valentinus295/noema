# Noema Database Stack

> Last updated: 2026-06-28

## Summary

Noema uses **2 primary engines** + **1 optional**. The "4 DB engines" finding from the
architecture review was based on the CohusDex design docs, not NOEMA's actual implementation.

| Engine | Role | Required? | Status |
|--------|------|-----------|--------|
| **Redis 7** | Message bus, caching, pub/sub | ✅ Yes | Core service |
| **DuckDB** | Trade journal, analytics, in-process OLAP | ✅ Yes | Embedded (no server) |
| **PostgreSQL 16** | Multi-process trade journal, B2B scale | ❌ No | Opt-in via override |

**NOT used in NOEMA** (despite appearing in CohusDex docs):
- TimescaleDB — no hypertable or time-series SQL found
- Apache AGE — no Cypher queries or graph extension found

## Details

### Redis (required)
- **Purpose**: Agent message bus, real-time caching, pub/sub for dashboard WebSocket
- **Docker**: `redis:7-alpine` in `docker-compose.yml`
- **Config**: `REDIS_URL` env var (default: `redis://localhost:6379/0`)
- **Memory limit**: 512MB with allkeys-lru eviction
- **Persistence**: AOF + RDB snapshots

### DuckDB (required, embedded)
- **Purpose**: Trade journal, backtesting data, analytics queries
- **Runs in-process**: No Docker container needed
- **Data path**: `data/noema.duckdb` (configurable)
- **Why DuckDB over PostgreSQL**: Single-file, zero-config, columnar OLAP performance for analytics

### PostgreSQL (optional, opt-in)
- **Purpose**: Multi-process trade journal writes, production deployments, B2B scale
- **Docker**: `postgres:16-alpine` in `docker-compose.override.yml` (auto-loaded)
- **Config**: `DATABASE_URL` env var
- **When to use**: Multiple Noema instances writing to same journal, or production deployments needing ACID guarantees across processes

## Recommendations

1. **Current stack is appropriate** — Redis + DuckDB covers all single-trader use cases
2. **Add PostgreSQL when** scaling to multi-process or B2B deployments
3. **Do NOT add** TimescaleDB or Apache AGE — they solve problems NOEMA doesn't have
4. **Consider removing** PostgreSQL from the default `.env` prompts to reduce setup confusion
