# VMPM Security Hardening

Single source of truth for security controls. Reviewed before any release.

## Secrets

- All secrets live in `.env` (gitignored). `.env.example` carries only `__set_me__` sentinels.
- `gitleaks` pre-commit hook scans every commit.
- Never log `api_key`, `password`, `token`, `chat_id` — `core/logging.py` redacts these in the structlog processor pipeline.
- Prometheus labels must never include user-controlled values. Static label sets only.

## Broker (FxPesa MT5 via Wine + mt5linux)

- `mt5linux` is vendored to `vendor/mt5linux-1.0.3-py3-none-any.whl` and pinned to a sha256 in `uv.lock`. If upstream disappears, the build still works.
- RPyC ≥ 6.0, `ThreadedServer`, `allow_public_attrs=False`, `allow_pickle=False`, bind `127.0.0.1`.
- On RPyC disconnect: halt new entries → reconcile on reconnect → halt + Telegram alert on mismatch. No auto-retry of `order_send`.
- Single-connection serialization lock around all MT5 calls (asyncio `Lock`).
- Live trading requires `VMPM_MODE=live` + `--live` CLI flag + first-of-day interactive confirmation.

## LLM (LiteLLM proxy → NVIDIA NIM)

- Proxy at `http://localhost:4000`. Multi-user hosts must rebind to a unix socket or add auth proxy. Single-user laptop: as-is.
- FundamentalBiasAgent LLM is **narrator only**. Numeric bias is computed in Python; the LLM cannot influence trade direction even if prompt-injected (see `docs/ARCHITECTURE.md §2`).
- LLM output schema is Pydantic-validated; free-text outputs are rejected.
- News payloads are HTML-stripped and truncated to ≤ 2 KB before being sent to the LLM.
- Require ≥ 2 corroborating news sources for any non-zero bias to flow.
- LLM borderline sanity-check (`confluence.llm_review_enabled`) defaults OFF. Shadow-mode log only.

## News sources

- All HTTP via `httpx` with `verify=True`. `verify=False` is forbidden and CI-grepped.
- Finnhub free-tier quota → **fail closed**: bias becomes neutral AND a `fundamental_stale` flag hard-vetoes ConfluenceAgent.
- TradingEconomics fallback engaged automatically on Finnhub 429/5xx.
- ForexFactory weekly XML cached locally for offline degraded mode.

## Control surface (Telegram)

- Bot token in `.env`, never in code.
- Auth on all commands: `TELEGRAM_CHAT_ID` whitelist **AND** `VMPM_TELEGRAM_SHARED_SECRET` token in the command (`/flatten <secret>`). Both required.
- Commands available: `/status`, `/positions`, `/flatten <secret>`, `/halt <secret>`, `/resume <secret>`.
- All command invocations logged to journal with redacted token.

## Logs + journal

- structlog JSON → `logs/vmpm.log` with `RotatingFileHandler(maxBytes=50_000_000, backupCount=10)`.
- DuckDB journal at `data/journal.duckdb`. Trade history is sensitive (edge-leaking + PII-adjacent):
  - File on encrypted home (LUKS) only.
  - Excluded from any cloud-sync folder (`~/Dropbox`, `~/Google Drive`, etc.).
  - Backed up nightly to a local encrypted volume via `scripts/backup_journal.sh`.

## Kill-switches (defense in depth)

GuardianAgent enforces, ExecutionAgent re-checks at the moment of `order_send`:

| Switch | Threshold | Action |
|---|---|---|
| Daily loss | `daily_loss_limit_pct` = 1.0% | Flatten + 24h halt |
| Drawdown EWMA -2σ | `drawdown_ewma_sigma_throttle` = 2.0 | Halve `risk_pct` |
| Drawdown EWMA -3σ | `drawdown_ewma_sigma_halt` = 3.0 | Halt |
| Beta posterior P(WR<0.45) > 0.95 | `beta_winrate_*` block | Halt |
| KS test live-vs-backtest | `ks_drift_pvalue_halt` = 0.01 | Halt + alert |
| SPRT H0 accepted | `sprt_*` block | Halt + alert |
| Spread > symbol cap | per `symbols.yaml` | Skip trade |
| News blackout | ±15 min around high-impact | Skip trade |
| Guardian heartbeat stale | > 30s | ExecutionAgent refuses orders |
| Watchdog: main proc died | systemd notify-missing | Flatten + alert |

## Supply chain

- `uv.lock` committed. CI re-resolves and diffs the lock weekly.
- License audit: TA-Lib (BSD), nautilus_trader (LGPL v3 — fine for personal use; flag if ever redistributed as a closed product), mt5linux (MIT), arch (NCSA), statsmodels (BSD), polars (MIT), structlog (Apache-2.0).
- Weekly `pip-audit` / `safety` scan in CI.

## Regulatory (Kenya)

- FxPesa is CMA-regulated. Written confirmation that algorithmic / API trading is permitted on the chosen account type is a **launch gate** (not a code gate). Filed in `docs/regulatory/fxpesa_algo_confirmation.pdf` before going live.
- KRA: P&L exportable as CSV in Africa/Nairobi timezone via `scripts/export_journal.py`.
