# Pre-Implementation Reviews

Two independent agents reviewed the design before engineering started.
Both returned **CHANGE_REQUESTED**. All blocking items have been resolved
in this commit; the resolution mapping is below.

## Security review — resolutions

| Finding | Severity | Resolution |
|---|---|---|
| No `.gitignore` | Critical | Added `.gitignore` with `.env`, journal db, logs excluded |
| Guardian fail-safe unspec'd | Critical | `docs/ARCHITECTURE.md §10` + `settings.yaml guardian.heartbeat_*` |
| MT5 disconnect policy unspec'd | Major | `docs/ARCHITECTURE.md §11` |
| Pre-order-send veto missing | Major | `docs/ARCHITECTURE.md §1` (Guardian role) |
| LLM prompt-injection surface | Major | `docs/ARCHITECTURE.md §2` — LLM is narrator only, Pydantic-schema'd, magnitude-clamped to ≤ 0.5, news truncated 2KB, ≥2 source corroboration |
| Finnhub quota → naked technicals | Major | `news.fail_closed_on_quota: true` + `fundamental_stale` hard veto |
| Risk caps too aggressive | Major | `risk_pct_per_trade` 0.5 → 0.25; daily limit 2.0 → 1.0 |
| Live-mode default | Major | Mode + `--live` + interactive confirm (`docs/ARCHITECTURE.md §13`) |
| mt5linux supply-chain | Major | Will vendor wheel + pin sha256 in `uv.lock` |
| RPyC RCE history | Major | `rpyc>=6.0` pinned; `docs/ARCHITECTURE.md §12` |
| Telegram weak auth | Minor | `VMPM_TELEGRAM_SHARED_SECRET` required on commands |
| Log rotation | Minor | `RotatingFileHandler` mandated in `docs/SECURITY.md` |
| Journal at rest | Minor | LUKS + no cloud sync (`docs/SECURITY.md`) |
| LiteLLM multi-user | Minor | Documented |
| HTTPS verify | Minor | `verify=True` mandated, CI-grepped |
| LGPL audit | Minor | `docs/SECURITY.md §Supply chain` |
| FxPesa CMA confirmation | Minor | Launch gate in `docs/ROADMAP.md` v0.4 |

## Quality review — resolutions

| Finding | Severity | Resolution |
|---|---|---|
| GARCH/ATR drift | Critical | ATR primary for SL; GARCH demoted to v1.0 regime flag |
| FundamentalBiasAgent contract | Critical | Python computes, LLM narrates only (`docs/ARCHITECTURE.md §2`) |
| PortfolioAgent missing | Critical | Added as 7th agent; `agents/portfolio.py` slot |
| Order-block definition | Critical | ICT-style pinned in `docs/ARCHITECTURE.md §5` + `settings.yaml indicators.order_block` |
| Conditional-EV curse of dimensionality | Major | Demoted to weighted-vote in v1; joint model deferred |
| Joint multi-TF distribution | Major | Acknowledged as conditional-independence approximation in v1 |
| BH-FDR vs sequential testing | Major | BH-FDR scoped to within-bar; SPRT promoted P1 → P0 |
| Permutation test naïve shuffle | Major | Stationary bootstrap (Politis-Romano) configured |
| MLE RSI vs no walk-forward | Major | RSI thresholds frozen as priors; MLE deferred to v2.0 |
| Beta prior unspec'd | Major | Beta(α=4.5, β=5.5), ESS=10 written into `settings.yaml` |
| Mahalanobis covariance | Major | Ledoit-Wolf in `docs/CURRICULUM_MAPPING.md` |
| 10 agents overkill | Major | Collapsed to 7 |
| LangGraph overkill | Major | Hand-rolled asyncio chain in v0.x; LangGraph only if v2.0 needs tool loops |
| NautilusTrader heavy | Major | Custom event-driven loop in v0.x; Nautilus optional in v2.0 |
| Slippage + spread models | Major | `backtest.slippage_*` and `backtest.spread_*` configured |
| Versioning | Major | `git_sha + settings_hash + strategy_version` on every journal row |
| 30 P0 items unrealistic | Major | `docs/ROADMAP.md` scopes v0.1–v2.0 honestly |
| Pair universe 5 vs 28 | Minor | 5 in v1; BH-FDR is N-agnostic |
| Broker abstraction | Minor | `broker/base.py BrokerProtocol` written in v0.1 |
| Cadence collision (news mid-M15) | Minor | Architecture §1 + GuardianAgent pre-order veto |
| Logging taxonomy | Minor | Pinned in `docs/ARCHITECTURE.md §8` |

## What still needs sign-off

- Re-review of the patched settings + new docs (running next)
- Code reviews after each implementation batch (per user's instruction)
