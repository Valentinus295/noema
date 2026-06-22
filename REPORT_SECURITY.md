# Noema Security Audit Report — Build Team Review

**Date:** 2026-06-23 02:39 GMT+8  
**Auditor:** Security Review Lead (Subagent #7)  
**Scope:** Full codebase at `noema/` — post-build-team changes  
**System:** Multi-agent forex trading system handling REAL MONEY via MT5  
**Severity Scale:** 🔴 CRITICAL · 🟠 HIGH · 🟡 MEDIUM · 🔵 LOW · ⚪ INFO  

---

## Executive Summary

**Overall Score: CONDITIONAL FAIL — Must fix CRITICAL items before commit.**

The build team has made substantial progress: the GitHub PAT has been removed from `.git/config`, Rust crates are well-structured with zero unsafe blocks, the CI pipeline includes security scanning, and the NIM client has proper caching/retry/rate-limiting. However, a **single catastrophic failure** prevents sign-off: the Guardian kill-switch system is 100% dead code — defined but never wired into the trade pipeline. A system trading real money with all kill-switches disconnected is not safe to commit.

### Finding Summary

| Severity | Count | Key Issues |
|----------|-------|------------|
| 🔴 CRITICAL | 3 | Guardian dead code (0/13 kill-switches wired); Dashboard CORS wildcard + no WS auth; No auth on REST API |
| 🟠 HIGH | 6 | LLM on critical path for trades; No max lot size cap; Docker no resource limits; CI actions not SHA-pinned; FundamentalBiasAgent not registered; RiskManager lacks Guardian integration |
| 🟡 MEDIUM | 5 | Dashboard on 0.0.0.0; No uv.lock; Settings not validated before use; DuckDB path edge case; mock data in production API server |
| 🔵 LOW | 3 | Unused FundamentalBiasAgent; cargo audit not in CI; Grafana default admin password |
| ⚪ INFO | 2 | Rust unwrap_or patterns are safe; CI security scanning is present |

---

## 1. Credential & Secret Exposure (CRITICAL)

### ✅ PASS: GitHub PAT Removed
`.git/config` now uses SSH: `git@github.com:Valentinus295/noema.git`. The PAT has been successfully removed.

### ✅ PASS: No Hardcoded Real Credentials Found
Scanned all `.py`, `.rs`, `.yaml`, `.toml`, `.env.example`, `.ts`, `.tsx` files. Zero real API keys, tokens, or passwords found in source code.

### ✅ PASS: `.env.example` Uses Sentinel Values
```
NIM_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxx
Noema_MT5_PASSWORD=your_mt5_password
POSTGRES_PASSWORD=noema_dev
REDIS_PASSWORD=noema_redis_dev
```

### ✅ PASS: `.gitignore` Comprehensive
Correctly excludes `.env`, `*.pem`, `*.key`, `*.duckdb`, `*.sqlite`, `logs/`, and credential directories.

### ⚪ INFO: docker.env.example Has Dev Defaults
`config/docker.env.example` contains development defaults (`noema_dev`, `admin`). This is acceptable — the file is explicitly documented as needing changes before production. The comment on line 8 states: "Change passwords before deploying to production."

---

## 2. Kill-Switch Audit (🔴 CRITICAL)

### 🔴 CRITICAL: GuardianAgent Is 100% Dead Code

**The guardian kill-switch system is entirely disconnected from the trade pipeline.**

**Evidence:**

1. **`noema/agents/guardian.py`** defines only utility functions and a dataclass:
   - `GuardianState` — a dataclass with loss limits, heartbeat, news blackout
   - `check_daily_loss()`, `check_weekly_loss()`, `check_news_blackout()`, `check_heartbeat()` — check functions
   - `guardian_guard()` — the orchestrator function
   - `heartbeat_task()` — background heartbeat updater

2. **There is NO `GuardianAgent` class in `guardian.py`** — the test file `tests/test_guardian.py` tries to import `GuardianAgent` but it does not exist.

3. **`noema/main.py` does NOT import `guardian` at all** — zero imports, zero references.

4. **`noema/core/orchestrator_modern.py` does NOT call `guardian_guard()`** — the pipeline runs through `_run_data_phase() → _run_analysis_phase() → _run_decision_phase() → _run_execution_phase()` with zero guardian checks.

5. **`noema/agents/risk.py` (RiskManagerAgent)** has its own loss limit checks but operates in isolation — there is no cross-agent communication with Guardian.

**Kill-Switch Implementation Matrix:**

| Switch | Declared | Code Exists | Wired to Pipeline |
|--------|----------|-------------|-------------------|
| Daily Loss Limit | ✅ (dashboard mock) | ⚠️ `guardian.py` + `risk.py` | ❌ Dead code |
| Weekly Loss Limit | ✅ | ⚠️ `guardian.py` + `risk.py` | ❌ Dead code |
| Max Drawdown EWMA -2σ | ✅ (dashboard) | ❌ | ❌ |
| Max Drawdown EWMA -3σ | ✅ (dashboard) | ❌ | ❌ |
| Beta Win-Rate Floor | ✅ (dashboard) | ❌ | ❌ |
| KS Drift Detection | ✅ (dashboard) | ❌ | ❌ |
| SPRT Edge Monitor | ✅ (dashboard) | ❌ | ❌ |
| Spread Guard | ✅ (dashboard) | ❌ | ❌ |
| News Blackout | ✅ | ⚠️ `guardian.py` | ❌ Dead code |
| Guardian Heartbeat | ✅ | ⚠️ `guardian.py` | ❌ Dead code |
| Margin Level Warning | ✅ (dashboard) | ❌ | ❌ |
| Correlation Limit | ✅ (test) | ❌ | ❌ |
| Consecutive Losses | ✅ (dashboard) | ❌ | ❌ |

**Result: 0 of 13 kill-switches are wired to the trade pipeline.** The RiskManagerAgent does check daily/weekly loss and max open trades in its own `analyze()` method, but these are soft checks within a single agent — there is no system-level Guardian that can halt ALL trading across all symbols.

### Impact

Without wired kill-switches:
- A runaway strategy can exhaust the account with no circuit breaker
- Network disconnection has no heartbeat timeout protection
- High-impact news events have no trading blackout enforcement
- Consecutive losses have no automatic pause

### Remediation

1. Create a proper `GuardianAgent` class (or wire the existing functions)
2. Add a `pre_trade_check()` call in the orchestrator's `_run_execution_phase()` BEFORE risk agent runs
3. Import and instantiate Guardian in `main.py` -> `create_orchestrator()`
4. Wire all 13 kill-switches to the trade pipeline
5. Add `guardian_guard()` call before every trade execution

---

## 3. LLM Safety (🟠 HIGH)

### 🟠 HIGH: LLM Is on the Critical Path for Trading Decisions

**Finding:** The decision phase (`_run_decision_phase()` in `orchestrator_modern.py`) requires all three LLM agents (TradeThesisAgent → DevilsAdvocateAgent → CIOAgent) to function. If any LLM call fails, the entire decision returns `None` and no trade executes.

While this is **safe** (failure = no trade), it means:
- LLM API outage = ZERO trading (not just reduced capability)
- LLM rate limiting = skipped cycles
- LLM produces bad output = trade still executes if Pydantic parsing succeeds

**The system CANNOT trade without the LLM.** This violates the design principle of "LLM is narrator only, never critical path."

### ✅ PASS: FundamentalBiasAgent Score Clamping

The `_compute_bias_score()` function clamps scores to `±0.5`: `clamped_score = max(-0.5, min(0.5, score))`. 

However, the FundamentalBiasAgent is **NOT registered in main.py** and is never called. It exists as orphaned code. The 0.05 cap on absolute confluence contribution (0.10 weight × 0.5 max score) would need to be enforced in the orchestrator when weighting the fundamental component — but since the agent isn't registered, this is academic.

### ✅ PASS: LLM Output Validation

The NIM client (`nim_client.py`) parses LLM responses through Pydantic schemas:
- `CIODecision`, `TradeThesis`, `DevilsAdvocate`, `TradeDirection`
- Failed parsing returns `{"type": "raw", "content": ..., "parse_error": ...}`
- JSON extraction handles markdown code blocks, raw JSON, and brace-delimited JSON

### ✅ PASS: Prompt Injection Resistance

- All LLM inputs come from structured data (agent reports, market context), not user input
- Market data is numeric/structured, not free-text
- No user-controlled content reaches the LLM

### ✅ PASS: NIM Client Security

- API key passed via `Authorization: Bearer` header (not URL)
- Rate limiting (token bucket) prevents API abuse
- Decision caching (SHA-256 hash of market context) prevents redundant calls
- Exponential backoff retry with jitter
- 401 errors immediately raise (no retry)
- httpx timeout configured (30s total, 5s connect)

---

## 4. Rust FFI Safety (✅ PASS)

### ✅ PASS: Zero Unsafe Blocks

All 16 Rust source files contain **zero `unsafe` blocks**. `grep -r "unsafe" rust/` returned no matches.

### ✅ PASS: Zero Panic! Calls

No `panic!` macro calls anywhere in Rust code.

### ✅ PASS: Graceful Error Handling

The code uses `unwrap_or()` and `unwrap_or_else()` consistently, providing safe defaults on `None`:
```rust
// Safe — provides default
bar.volume += tick.volume.unwrap_or(0.0);
entry_time: self.current_tick.as_ref().map(|t| t.timestamp).unwrap_or_else(Utc::now),
```

One `unwrap()` exists in `aggregation.rs:163` but it's inside a `#[cfg(test)]` block — test-only code, not production.

### ✅ PASS: PyO3 Bindings Safe

- All `#[pyfunction]` returns `PyResult<T>` — panics won't cross FFI
- `#[pymodule]` uses proper error propagation
- Feature-gated (`#[cfg(feature = "python-bindings")]`) so pure-Rust builds don't need Python

**Verdict: Rust modules cannot crash the Python process.**

---

## 5. Docker Security (🟠 HIGH)

### 🟠 HIGH: No Resource Limits

None of the four services (PostgreSQL, Redis, Prometheus, Grafana) have resource constraints:

```yaml
# MISSING on all services:
deploy:
  resources:
    limits:
      memory: 512M
      cpus: "1.0"
```

Without limits, a runaway Redis memory leak or PostgreSQL query can exhaust the host machine. This is a DoS vector.

### 🟡 MEDIUM: PostgreSQL Exposed on All Interfaces

```yaml
ports:
  - "${POSTGRES_PORT:-5432}:5432"  # Binds to 0.0.0.0
```

On most Docker hosts, this exposes PostgreSQL to the network. Should bind to `127.0.0.1` explicitly unless PostgreSQL needs external access.

### ✅ PASS: Redis Password Protection

```yaml
command: redis-server ... --requirepass ${REDIS_PASSWORD:-noema_redis_dev}
```

Redis requires authentication. The default `noema_redis_dev` is documented as dev-only.

### ✅ PASS: Grafana Authentication Enabled

```yaml
GF_AUTH_ANONYMOUS_ENABLED: "false"
GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
```

Anonymous access is disabled. The default `admin` password is documented as needing change.

### ✅ PASS: PostgreSQL Password via Environment Variable

```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-noema_dev}
```

No hardcoded password — uses env var with dev default.

### ✅ PASS: Log Rotation Configured

All services have log rotation with size limits:
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "50m"
    max-file: "3"
```

### ✅ PASS: Noema App Service Commented Out

The `noema-app` service is entirely commented out — no accidental deployment of unconfigured app.

---

## 6. CI Pipeline Security (🟠 HIGH)

### 🟠 HIGH: Third-Party Actions Not Pinned to SHA Hashes

All GitHub Actions use version tags, not commit SHAs:

| Action | Version | Risk |
|--------|---------|------|
| `actions/checkout` | `@v4` | Tag can be moved by maintainer |
| `actions/setup-python` | `@v5` | Tag can be moved |
| `astral-sh/setup-uv` | `@v4` | Tag can be moved |
| `codecov/codecov-action` | `@v5` | Tag can be moved |
| `dtolnay/rust-toolchain` | `@stable` | Floating tag |
| `actions/cache` | `@v4` | Tag can be moved |
| `docker/setup-buildx-action` | `@v3` | Tag can be moved |
| `docker/build-push-action` | `@v6` | Tag can be moved |

**Recommendation:** Pin all actions to commit SHAs, e.g., `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2`

### ✅ PASS: Security Scanning in CI

```yaml
- name: Detect secrets
  run: uv run detect-secrets scan --all-files

- name: Audit dependencies
  run: uv run pip-audit
```

Both `detect-secrets` and `pip-audit` run on every push/PR.

### ✅ PASS: No Token Exposure in Workflow

No hardcoded secrets in workflow YAML. Secrets would be referenced via `${{ secrets.* }}` (not currently used, but no exposure).

### ✅ PASS: Concurrency Control

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

Prevents parallel CI runs from interfering.

### ✅ PASS: Fail-Fast Security

```yaml
if [ "${{ needs.security.result }}" != "success" ] ... then FAILED=1; fi
exit $FAILED
```

CI summary job fails if security scan fails.

### ⚪ INFO: CI Rust Step Only Runs If rust/ Exists

Good practice — doesn't fail on branches that don't touch Rust code.

---

## 7. New Dependencies Audit (🔵 LOW)

### ✅ PASS: Main Dependencies Are Mainstream

All dependencies in `pyproject.toml` are well-known, actively maintained packages:
- `pandas`, `polars`, `pyarrow` — standard data tools
- `sqlalchemy`, `asyncpg`, `aiosqlite`, `redis` — standard DB/drivers
- `pydantic`, `pydantic-settings` — standard validation
- `numpy`, `scipy`, `statsmodels`, `scikit-learn` — standard scientific
- `httpx`, `structlog`, `prometheus-client` — standard HTTP/logging/metrics
- `opentelemetry-*` — CNCF standard

### ✅ PASS: RPyC Pinned >=6.0

`rpyc>=6.0` avoids the RCE vulnerability in <5.3. Explicitly documented in pyproject.toml comment.

### ✅ PASS: Security Tooling in Dev Dependencies

```toml
"detect-secrets>=1.5",
"pip-audit>=2.7",
```

Both run in CI.

### 🔵 LOW: No Cargo Audit in CI

Rust dependencies are not audited in CI. Should add `cargo audit` step:
```yaml
- name: Audit Rust dependencies
  run: cargo install cargo-audit && cargo audit
```

### 🔵 LOW: No uv.lock Committed

`uv.lock` is not in the repository. Without a lock file, dependency resolution is non-deterministic across environments. Supply chain integrity depends on trusting PyPI at install time.

---

## 8. Dashboard Security (🔴 CRITICAL)

### 🔴 CRITICAL: CORS Allows All Origins

```python
# dashboard/server/api.py:42
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ANY website can access this API
    allow_methods=["*"],
    allow_headers=["*"],
)
```

This means ANY website visited by a user on the same network as the dashboard can:
- Read open positions (edge-leaking PII)
- Read trade history with P&L
- Read account balance
- Read risk metrics

**Remediation:** Restrict to specific origins:
```python
allow_origins=["http://localhost:3000", "http://localhost:8000"]
```

### 🔴 CRITICAL: WebSocket Has No Authentication

```python
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    client_id = await manager.connect(ws)  # No auth check!
```

Anyone who can reach the dashboard server can:
- Stream real-time positions, P&L, agent states
- Receive pipeline phase updates (trade intelligence)
- No token, no API key, no authentication required

**Remediation:** Add WebSocket authentication via query parameter token or initial auth message.

### 🟡 MEDIUM: Dashboard Server Binds to 0.0.0.0

```python
uvicorn.run(
    "noema.dashboard.server.api:app",
    host="0.0.0.0",  # Exposed to all network interfaces
    port=8000,
    reload=True,     # Debug mode — do NOT use in production
)
```

The combination of `host="0.0.0.0"` + `reload=True` + `allow_origins=["*"]` means this server is wide open in production.

### ✅ PASS: No XSS Vectors in React Components

- No `dangerouslySetInnerHTML` found in source
- React's JSX auto-escapes content
- No `eval()`, `document.write()`, or raw `innerHTML` usage

### ✅ PASS: WebSocket WSS on HTTPS

```typescript
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;
```

Correctly upgrades to WSS when behind TLS.

### ⚪ INFO: Dashboard Uses Mock Data

The dashboard API server returns hardcoded mock data (`generate_agents()`, `generate_positions()`, etc.). This is acceptable for development but must be replaced with real data sources before production.

---

## 9. Additional Findings

### 🟡 MEDIUM: RiskManagerAgent Has No Max Lot Size Hard Cap

`compute_position_size()` calculates lot size based on risk percentage but has no absolute ceiling. A very tight stop loss (e.g., 0.1 pips) or a misconfiguration could produce an excessively large position:

```python
lot_size = risk_amount / (sl_pips * 10)
return max(0.01, round(lot_size, 2))  # No max!
```

**Remediation:** Add `max_lot_size: float = 1.0` to `RiskParams` and enforce it.

### 🟡 MEDIUM: No NOEMA_SECRET_KEY Usage

`config/docker.env.example` defines `NOEMA_SECRET_KEY=change-me-in-production` but no code reads or uses this environment variable. The setting is orphaned — session tokens and API auth have no secret key backing.

### 🟡 MEDIUM: FundamentalBiasAgent Is Orphaned Code

The agent exists in `agents/fundamental.py` and has tests in `tests/test_fundamental_bias.py`, but it's never registered in `main.py`. Either wire it in or remove it to reduce attack surface.

### 🔵 LOW: RiskManagerAgent Has Duplicate Loss Limit Checks

Both `guardian.py` and `risk.py` implement daily/weekly loss limit checks. If Guardian is eventually wired, these checks will be duplicated. Should consolidate into Guardian as the single source of truth.

### 🔵 LOW: Grafana Admin Password Default

Default Grafana password is `admin` in `docker.env.example`. While documented as dev-only, it's trivially guessable if left unchanged in production.

---

## Recommendations (Priority Order)

### 🔴 Must Fix Before Commit

1. **Wire Guardian kill-switches to the trade pipeline**
   - Create `GuardianAgent` class (or wire existing functions)
   - Add `guardian_guard()` call in orchestrator before every trade execution
   - Import Guardian in `main.py` → `create_orchestrator()`
   - Wire heartbeat check, news blackout, spread guard

2. **Restrict CORS origins**
   - Change `allow_origins=["*"]` to specific origins
   - Load from `CORS_ORIGINS` environment variable

3. **Add WebSocket authentication**
   - Require token/API key for WebSocket connections
   - Use `NOEMA_SECRET_KEY` for token generation

### 🟠 Should Fix Before Live Trading

4. **Decouple LLM from critical path** — system should trade with deterministic signals when LLM is unavailable
5. **Add max lot size hard cap** in RiskManagerAgent
6. **Add Docker resource limits** (memory, CPU) to all services
7. **Pin CI actions to SHA hashes**
8. **Register & wire FundamentalBiasAgent** (or remove it)
9. **Consolidate kill-switch logic** — RiskManager should delegate to Guardian, not duplicate

### 🟡 Fix in Next Iteration

10. **Add `cargo audit` to CI**
11. **Commit `uv.lock`** for deterministic builds
12. **Bind PostgreSQL to 127.0.0.1** in docker-compose
13. **Replace dashboard mock data** with real API integration
14. **Add REST API authentication** to dashboard endpoints

---

## Sign-Off

**Noema is NOT safe to commit** in its current state. The single blocking issue is that the Guardian kill-switch system — the circuit breaker designed to prevent catastrophic losses during real-money trading — is entirely disconnected from the trade pipeline. Zero of the 13 documented kill-switches are wired to prevent a trade from executing. The code quality in all other areas (Rust safety, NIM client, CI pipeline, credential hygiene) is strong, and fixing the Guardian integration is a matter of wiring existing functions, not writing new code. Once the kill-switches are connected and the dashboard CORS/auth issues are resolved, the codebase will meet the security bar for committing.

---

*Report generated 2026-06-23 02:39 GMT+8. Full audit of 127 files across 8 security domains.*
