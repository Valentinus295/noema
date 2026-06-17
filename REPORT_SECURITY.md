# VMPM Security Audit Report

**Date:** 2026-06-17  
**Auditor:** Automated Security Audit Agent  
**Scope:** Full codebase at `valentine-money-printing-machine/`  
**System:** Multi-agent forex trading system handling real money via MT5/FxPesa  
**Severity Scale:** 🔴 CRITICAL · 🟠 HIGH · 🟡 MEDIUM · 🔵 LOW · ⚪ INFO

---

## Executive Summary

VMPM is a well-architected multi-agent trading system with strong **design intent** for security (documented in `docs/SECURITY.md` and `docs/ARCHITECTURE.md`). However, the codebase is in an **early scaffold stage** — many documented controls exist only as documentation, not as implemented code. The most critical finding is a **leaked GitHub Personal Access Token** in `.git/config`. Several architectural security decisions (LLM isolation, kill-switches, Guardian heartbeat) are sound in design but have significant implementation gaps.

### Finding Summary

| Severity | Count | Key Issues |
|----------|-------|------------|
| 🔴 CRITICAL | 2 | GitHub PAT in `.git/config`; No Telegram auth implemented |
| 🟠 HIGH | 5 | No structlog redaction processor; No live-mode dual-confirm; No RPyC disconnect handling; Missing Guardian heartbeat integration; No log rotation configured |
| 🟡 MEDIUM | 4 | LiteLLM proxy has no auth; No LLM output schema validation in code; Missing vendor directory; No pip-audit integration |
| 🔵 LOW | 3 | calendar.py uses aiohttp instead of httpx; Position size limits are soft; ConfluenceSetup missing settings_hash/git_sha |
| ⚪ INFO | 4 | No tests; No backup scripts; No watchdog process; No DuckDB journal |

---

## 1. Secrets & Credentials

### 🔴 CRITICAL: GitHub PAT Exposed in `.git/config`

**File:** `.git/config` (line 5)  
```
url = https://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@github.com/...
```

A GitHub Personal Access Token (`ghp_KPWD7...`) is embedded in the remote URL. This token is committed to the repository and anyone with clone access can extract it. If this repo is ever shared or the token has broad scopes, it grants full GitHub API access.

**Remediation:**
1. **Immediately revoke** this token at https://github.com/settings/tokens
2. Use `git remote set-url origin https://github.com/...` (no token)
3. Use `git credential store` or SSH keys instead
4. Run `git filter-branch` or `git filter-repo` to purge from history
5. Add a pre-commit hook to detect PAT patterns in `.git/config`

### ✅ `.env.example` Sentinels — PASS

All sensitive values use `__set_me__` sentinel pattern. No real credentials in `.env.example`.

### ✅ `.gitignore` — PASS

Correctly excludes:
- `.env`, `.env.*` (but allows `.env.example`)
- `*.pem`, `*.key`
- `**/credentials*`, `**/secret*`
- `*.duckdb`, `*.sqlite`, `*.db`
- `logs/`, `*.log`

### ⚪ No Hardcoded Credentials Found in Source Code — PASS

Searched all `.py` files for hardcoded passwords, API keys, tokens. Only found proper `os.getenv()` usage in `scripts/run_live.py` and config loading.

---

## 2. Network Security

### 🟠 HIGH: LiteLLM Proxy Has No Authentication

**File:** `.env.example`  
```
LITELLM_BASE_URL=http://localhost:4000
LITELLM_MASTER_KEY=__set_me__
```

The `LITELLM_MASTER_KEY` is defined in `.env.example` but **no code in the repository actually uses it**. Searched for `LITELLM_MASTER_KEY`, `litellm`, `openai`, `chat.completion` in all Python files — found zero HTTP calls to the LiteLLM proxy. The LLM integration is documented but **not yet implemented**.

**Risk:** When implemented, if the proxy runs on `localhost:4000` without auth, any local process can use it. On a single-user laptop this is acceptable per `SECURITY.md`, but the master key should be enforced.

**Remediation:** When implementing LLM calls, include the `Authorization: Bearer $LITELLM_MASTER_KEY` header.

### ✅ RPyC Binding — PASS (in FBSBroker)

`FBSBroker.__init__` defaults to `host="127.0.0.1"`. The `.env.example` sets `MT5_HOST=127.0.0.0`. No `0.0.0.0` binding found anywhere.

**However:** The `MT5Broker` class in `broker/mt5.py` does **not** use RPyC at all — it directly imports `MetaTrader5` (the Windows Python package). The RPyC bridge pattern described in SECURITY.md is implemented only in `FBSBroker`. The MT5Broker relies on running under Wine with direct Python MT5 imports.

### 🔵 LOW: calendar.py Uses aiohttp Instead of httpx

**File:** `data/calendar.py` (line 61)  
```python
import aiohttp
async with aiohttp.ClientSession() as session:
    async with session.get(url, timeout=...) as resp:
```

SECURITY.md states "All HTTP via `httpx` with `verify=True`" but `calendar.py` uses `aiohttp` with no explicit SSL verification setting. `aiohttp` defaults to SSL verification enabled, so this is not a vulnerability, but it violates the stated policy and makes CI grepping for `verify=False` unreliable.

**Remediation:** Replace `aiohttp` with `httpx.AsyncClient(verify=True)` to match the stated policy.

### ✅ No `verify=False` Found — PASS

Searched all Python files for `verify\s*=\s*False`. None found.

---

## 3. LLM Security (Prompt Injection)

### Architecture Assessment

Per `docs/ARCHITECTURE.md §2`, the LLM is **narrator only**: Python computes the numeric bias, LLM narrates it. This is the correct containment pattern.

### 🟡 MEDIUM: LLM Output Schema Validation Not Implemented in Code

**File:** `core/types.py` defines `Bias` with Pydantic validation:
```python
score: float = Field(ge=-0.5, le=0.5)
explanation: str = Field(max_length=2000)
```

This is good — the `score` field clamps to ±0.5 and `explanation` is capped at 2KB. However, **no code in the repository actually calls an LLM or validates its output against this schema**. The `FundamentalBiasAgent` in `agents/fundamental.py` computes bias entirely in Python without any LLM call.

**Status:** The Pydantic schema exists and is correctly constrained. When LLM integration is added, it must pipe output through `Bias.model_validate()`.

### 🟡 MEDIUM: News Payload Sanitization Not Implemented

SECURITY.md claims "News payloads are HTML-stripped and truncated to ≤ 2 KB before being sent to the LLM." No HTML stripping or truncation code exists because the LLM integration is not yet implemented.

**Status:** Architectural intent is correct. Must be implemented when LLM calls are added.

### ✅ Magnitude Clamping — PASS (in Schema)

`core/types.py`: `score: float = Field(ge=-0.5, le=0.5)`. The comment says "LLM can never exceed 0.10 × 0.5 = 0.05 absolute contribution." The Pydantic schema enforces ±0.5 on the `Bias.score` field. The 0.05 limit would need to be enforced in `ConfluenceAgent` when weighting the fundamental bias component (weight=0.10 × max_score=0.5 = 0.05 max contribution). Currently `ConfluenceAgent` uses weight 0.10 for fundamental but the bias score comes from Python, not LLM.

### ⚪ No LLM Code Exists Yet — INFO

No Python file imports `openai`, `litellm`, or makes HTTP calls to an LLM endpoint. The entire LLM integration is documented but not coded. This is actually **good from a security perspective** — there's no attack surface yet.

---

## 4. Trading Security (Financial Risk)

### 🟠 HIGH: Live-Mode Dual-Confirm Not Implemented

**SECURITY.md states:** "Live trading requires `VMPM_MODE=live` + `--live` CLI flag + first-of-day interactive confirmation."

**Actual code in `scripts/run_live.py`:**
```python
parser.add_argument("--dry-run", action="store_true")
# ... no --live flag, no VMPM_MODE check, no interactive prompt
```

The script has a `--dry-run` flag but **no `--live` flag**. There is no check for `VMPM_MODE=live` environment variable. There is no interactive `y/N` confirmation prompt. The system will trade live as long as it can connect to the broker.

**Remediation:**
1. Add `--live` CLI flag (required for live trading)
2. Check `os.getenv("VMPM_MODE") == "live"` 
3. Add interactive `input("Confirm live trading [y/N]: ")` on first start of day
4. All three must pass before `MT5Broker` is instantiated

### 🟠 HIGH: Guardian Heartbeat Not Integrated into Execution Flow

**File:** `agents/guardian.py`  
The `heartbeat_task()` updates `state.last_heartbeat` every 5 seconds. The `check_heartbeat()` function verifies freshness. **However**, in `agents/orchestrator.py`, the `_evaluate_and_trade()` method calls `guardian_guard()` which checks daily/weekly loss and news blackout, but does **NOT** check heartbeat staleness:

```python
approved, reason = await guardian_guard(
    self.state.guardian_state, setup, self.state.guardian_state.daily_pnl
)
```

The `guardian_guard()` function in `guardian.py` does not call `check_heartbeat()`. The heartbeat check exists as a standalone function but is never wired into the guard decision.

**Remediation:** Add heartbeat check to `guardian_guard()`:
```python
if not check_heartbeat(state):
    return False, "Guardian heartbeat stale — refusing orders"
```

### 🟠 HIGH: No RPyC Disconnect Handling

**SECURITY.md states:** "On RPyC disconnect → halt new entries → reconcile on reconnect → halt + Telegram alert on mismatch."

**Actual code:** `FBSBroker` has no try/except around RPyC calls, no disconnect detection, no reconnection logic, no reconciliation. If the RPyC connection drops mid-trade, the system will crash with an unhandled exception.

**Remediation:** Wrap RPyC calls in try/except for `EOFError`, `ConnectionError`. On disconnect: set a `_connected=False` flag, halt new entries, attempt reconnect with exponential backoff, reconcile positions on success.

### 🟠 HIGH: No Watchdog Process

**SECURITY.md states:** "A separate watchdog process (`scripts/watchdog.py`, systemd unit) monitors the main process. On crash or hang, the watchdog flattens all positions."

**Actual code:** No `scripts/watchdog.py` exists. No systemd unit file exists. The `scripts/` directory contains only `run_live.py`. If the main process crashes, open positions remain unprotected.

### Kill-Switch Assessment

| Switch | Documented | Implemented | Status |
|--------|-----------|-------------|--------|
| Daily loss (1%) | ✅ | ✅ `guardian.py` `check_daily_loss()` | Working but uses absolute P&L, not % of account |
| Weekly loss | ✅ | ✅ `guardian.py` `check_weekly_loss()` | Same issue — absolute, not percentage |
| Drawdown EWMA -2σ | ✅ | ❌ Not in code | Not implemented |
| Drawdown EWMA -3σ | ✅ | ❌ Not in code | Not implemented |
| Beta posterior | ✅ | ❌ Not in code | Not implemented |
| KS drift test | ✅ | ❌ Not in code | Not implemented |
| SPRT | ✅ | ❌ Not in code | Not implemented |
| Spread cap | ✅ | ❌ Not in guardian | Checked in RiskManagerAgent only |
| News blackout | ✅ | ✅ `guardian.py` `check_news_blackout()` | Working |
| Guardian heartbeat | ✅ | ⚠️ Function exists but not wired | **Gap** |
| Watchdog | ✅ | ❌ Not in code | Not implemented |

**Only 3 of 11 documented kill-switches are functionally implemented.** The drawdown EWMA, beta posterior, and SPRT are all sophisticated statistical guards that exist only in `settings.yaml` configuration.

### Position Size Limits

`RiskManagerAgent` computes lot size and checks `max_open_trades`, but there is **no hard cap on maximum lot size**. A misconfigured `risk_per_trade` or very tight stop-loss could produce an excessively large position.

**Remediation:** Add `max_lot_size: float = 1.0` to `RiskConfig` and enforce it in `RiskManagerAgent`.

---

## 5. Supply Chain Security

### 🟡 MEDIUM: Vendor Directory Missing

**SECURITY.md states:** "`mt5linux` is vendored to `vendor/mt5linux-1.0.3-py3-none-any.whl`"

**Actual state:** No `vendor/` directory exists. The `scripts/` directory contains only `run_live.py`. The vendoring strategy is documented but not implemented.

### ✅ RPyC Version Pinning — PASS

`pyproject.toml`: `"rpyc>=6.0"` — correctly pins to ≥6.0 to avoid the RCE vulnerability in <5.3.

### 🟡 MEDIUM: No pip-audit/safety Integration

**SECURITY.md states:** "Weekly `pip-audit` / `safety` scan in CI."

**Actual state:** `pip-audit>=2.7` is listed in `[project.optional-dependencies] dev` but no CI configuration exists (no `.github/workflows/`, no `Makefile`, no `tox.ini`). The tooling dependency exists but is not wired into any automated scan.

### ⚪ No `uv.lock` Committed — INFO

SECURITY.md states "`uv.lock` committed." No `uv.lock` file exists in the repository.

### License Audit

`pyproject.toml` dependencies match the license audit in SECURITY.md. No unexpected license pulls detected in the dependency list.

---

## 6. Data Security

### 🟠 HIGH: No Structlog Redaction Processor

**SECURITY.md states:** "Never log `api_key`, `password`, `token`, `chat_id` — `core/logging.py` redacts these in the structlog processor pipeline."

**Actual state:** No `core/logging.py` file exists. The structlog configuration in `main.py` uses basic processors with no redaction:

```python
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(),
    ],
    ...
)
```

No custom processor to strip `api_key`, `password`, `token`, or `chat_id` from log output. If any agent logs context containing these fields, they will appear in plaintext.

**Remediation:** Create `core/logging.py` with a redaction processor:
```python
REDACTED_FIELDS = {"api_key", "password", "token", "chat_id", "secret", "mt5_password"}

def redact_secrets(logger, method_name, event_dict):
    for key in list(event_dict.keys()):
        if any(s in key.lower() for s in REDACTED_FIELDS):
            event_dict[key] = "***REDACTED***"
    return event_dict
```

### ⚪ No Log Rotation Configured — INFO

SECURITY.md specifies `RotatingFileHandler(maxBytes=50_000_000, backupCount=10)` but no file handler is configured in the structlog setup. Currently logs go to stdout only.

### ⚪ No DuckDB Journal — INFO

No DuckDB integration exists in the code. `database/models.py` uses SQLAlchemy with a SQLite backend (`sqlite+aiosqlite:///vmpm.db`). The DuckDB journal on LUKS is documented but not implemented.

### 🔵 LOW: Prometheus Label Safety

No Prometheus metrics are currently exported. The `prometheus-client>=0.21` dependency exists but is unused. When implemented, ensure static label sets only (no user-controlled values).

### Trade Data Sensitivity

`database/models.py` stores trade records with `pair`, `direction`, `volume`, `pnl`, `open_price`, `close_price`. This is edge-leaking data. The `.gitignore` correctly excludes `*.sqlite` and `*.db` files.

---

## 7. Authentication & Authorization

### 🔴 CRITICAL: Telegram Auth Not Implemented

**SECURITY.md states:** "Auth on all commands: `TELEGRAM_CHAT_ID` whitelist AND `VMPM_TELEGRAM_SHARED_SECRET` token in the command. Both required."

**Actual state:** No Telegram integration code exists anywhere in the codebase. Searched for `telegram`, `chat_id`, `shared_secret`, `bot_token` in all Python files — zero results. The `python-telegram-bot>=21.0` dependency is in `pyproject.toml` but no code uses it.

**Risk:** When Telegram integration is added, if auth is not implemented first, the bot will be an unauthenticated control surface for a real-money trading system.

**Remediation:** Implement auth as the first feature of the Telegram integration:
1. Check `update.effective_chat.id` against `TELEGRAM_CHAT_ID` whitelist
2. Require `VMPM_TELEGRAM_SHARED_SECRET` as second argument to sensitive commands
3. Reject all commands that fail either check
4. Log rejected auth attempts

---

## 8. Vulnerability Assessment

### ✅ No eval/exec Usage — PASS

Searched all Python files for `eval(` and `exec(`. No usage found (false positives were function names like `_evaluate_and_trade`).

### ✅ No Pickle Usage — PASS

Searched for `pickle` and `allow_pickle`. No usage found. When RPyC is used (FBSBroker), it uses `rpyc.connect()` which defaults to `allow_pickle=False` in RPyC ≥6.0.

### ✅ SQL Injection — LOW RISK

`database/models.py` uses SQLAlchemy ORM with parameterized queries. No raw SQL or string interpolation in queries. Low risk.

### 🔵 LOW: Path Traversal — LOW RISK

`core/config.py` loads YAML from a path parameter:
```python
path = Path("config/default.yaml")
```
`core/settings.py` uses a hardcoded path:
```python
path = Path("/home/valentinetech/vmpm/config/settings.yaml")
```

Both use `Path()` which normalizes paths. No user-controlled path input that could traverse directories. Low risk.

### ✅ YAML Safe Loading — PASS

`yaml.safe_load()` is used in both `core/config.py` and `core/settings.py`. No `yaml.load()` with unsafe loaders.

---

## 9. Compliance

### Kenya CMA Regulatory Status

SECURITY.md states: "FxPesa is CMA-regulated. Written confirmation that algorithmic/API trading is permitted on the chosen account type is a **launch gate** (not a code gate)."

**Status:** No `docs/regulatory/` directory exists. No `fxpesa_algo_confirmation.pdf` found. This is a **pre-launch requirement**, not a code issue.

### KRA Tax Reporting

SECURITY.md states: "P&L exportable as CSV in Africa/Nairobi timezone via `scripts/export_journal.py`."

**Status:** No `scripts/export_journal.py` exists. No journal database exists yet. This must be implemented before live trading.

### Data Retention

No data retention policy is coded. The `.gitignore` excludes database files from version control, which is correct. No automated data cleanup or archival process exists.

---

## 10. Gap Analysis vs docs/SECURITY.md

### Controls Documented and Implemented ✅

| Control | Implementation |
|---------|---------------|
| `.env.example` sentinels | ✅ `__set_me__` pattern used |
| `.gitignore` secret exclusion | ✅ Comprehensive |
| RPyC bind 127.0.0.1 | ✅ Default in FBSBroker |
| RPyC ≥6.0 pinning | ✅ In pyproject.toml |
| Daily loss kill-switch | ✅ `guardian.py` |
| Weekly loss kill-switch | ✅ `guardian.py` |
| News blackout | ✅ `guardian.py` |
| Pydantic schema validation | ✅ `core/types.py` |
| Bias score clamping ±0.5 | ✅ `core/types.py` |
| SQLAlchemy (no raw SQL) | ✅ `database/models.py` |
| yaml.safe_load | ✅ Both config files |
| No eval/exec | ✅ Confirmed |
| No pickle | ✅ Confirmed |
| No verify=False | ✅ Confirmed |

### Controls Documented but NOT Implemented ❌

| Control | Status |
|---------|--------|
| gitleaks pre-commit hook | ❌ No `.pre-commit-config.yaml` |
| structlog redaction processor | ❌ No `core/logging.py` |
| Prometheus static labels | ❌ No metrics exported |
| DuckDB journal on LUKS | ❌ SQLite only, no encryption |
| Log rotation (50MB, 10 backups) | ❌ stdout only |
| Backup script (`scripts/backup_journal.sh`) | ❌ Does not exist |
| mt5linux vendoring | ❌ No `vendor/` directory |
| `uv.lock` committed | ❌ Does not exist |
| Weekly pip-audit in CI | ❌ No CI config |
| Live-mode triple-confirm | ❌ No `--live` flag, no prompt |
| RPyC disconnect handling | ❌ No reconnect logic |
| Watchdog process | ❌ No `scripts/watchdog.py` |
| Drawdown EWMA kill-switch | ❌ Config only |
| Beta posterior kill-switch | ❌ Config only |
| KS drift test | ❌ Config only |
| SPRT kill-switch | ❌ Config only |
| Guardian heartbeat wiring | ⚠️ Function exists, not connected |
| Telegram auth (chat_id + secret) | ❌ No Telegram code |
| P&L export for KRA | ❌ No export script |
| CMA algo confirmation | ❌ No regulatory docs |
| Position size hard cap | ❌ Soft limits only |
| LLM integration (narrator) | ❌ Not implemented |
| News HTML stripping | ❌ Not implemented |
| LLM 2KB truncation | ❌ Not implemented |
| ≥2 corroboration rule | ❌ Not implemented |
| Settings hash in journal | ❌ `settings_hash=""` in ConfluenceAgent |
| Git SHA in journal | ❌ `git_sha=""` in ConfluenceAgent |
| Version stamping | ❌ No `core/versioning.py` |
| Reconciliation on reconnect | ❌ No `broker/reconciliation.py` |

### Controls Documented and Bypassed ⚠️

| Control | Issue |
|---------|-------|
| HTTP policy (httpx only) | `data/calendar.py` uses `aiohttp` instead |
| Daily loss as percentage | `guardian.py` uses absolute P&L, not % of account |
| Heartbeat check in order flow | `check_heartbeat()` exists but `guardian_guard()` doesn't call it |

---

## Recommendations (Priority Order)

### 🔴 Immediate (Before Any Live Trading)

1. **Revoke the exposed GitHub PAT** and purge from git history
2. **Implement live-mode triple-confirm** in `scripts/run_live.py`
3. **Implement Telegram auth** before any bot deployment
4. **Wire Guardian heartbeat** into `guardian_guard()`
5. **Create `core/logging.py`** with secret redaction processor

### 🟠 Before Beta Testing

6. **Implement RPyC disconnect handling** in `FBSBroker`
7. **Create watchdog process** (`scripts/watchdog.py` + systemd unit)
8. **Add max lot size hard cap** in `RiskManagerAgent`
9. **Fix daily/weekly loss to use percentage** of account balance
10. **Implement drawdown EWMA** kill-switch (config exists, needs code)
11. **Replace aiohttp with httpx** in `calendar.py`
12. **Commit `uv.lock`** and vendor mt5linux wheel

### 🟡 Before Production

13. **Set up CI pipeline** with pip-audit, gitleaks, ruff, mypy
14. **Implement log rotation** and file handler
15. **Implement DuckDB journal** with encryption awareness
16. **Implement P&L export** for KRA tax reporting
17. **Add version stamping** (`core/versioning.py`) to journal rows
18. **Implement LLM narrator** with proper schema validation and sanitization
19. **Implement ≥2 corroboration rule** for fundamental bias
20. **Obtain CMA algo trading confirmation** from FxPesa

---

## Methodology

- Static analysis of all Python source files (grep patterns for secrets, eval, pickle, SQL injection)
- `.git/config` inspection for credential exposure
- `.gitignore` completeness review
- Cross-reference of `docs/SECURITY.md` claims against actual code
- Dependency audit of `pyproject.toml`
- Architecture review of agent communication patterns
- Kill-switch completeness matrix

---

*Report generated 2026-06-17. Re-audit recommended after implementation of 🔴 immediate items.*
