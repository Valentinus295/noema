# Noema Architecture (v0.1)

This document pins every decision the security + quality reviews flagged as ambiguous.
If it isn't written here, it isn't decided.

## 1. Agent roster (final, 7 agents)

Per quality review §Major (10 → 7): RSIAgent, CandlestickAgent, and RetestAgent are
**deterministic sub-scorers inside ConfluenceAgent**, not standalone agents. They are
pure functions of OHLCV with no state of their own — splitting them into agents added
orchestration overhead with zero edge gain.

| Agent | Responsibility |
|---|---|
| TrendAgent | D1/H4/H1 trend via MA(50)/MA(200) + HH/HL or LH/LL |
| StructureAgent | Session/D/W/M/Y highs+lows + ICT-style order blocks + retest detection |
| FundamentalBiasAgent | Hybrid: deterministic macro computations → optional LLM narrator |
| ConfluenceAgent | Combines verdicts + computes RSI/candle sub-scores + optional borderline LLM check |
| PortfolioAgent | PCA factor exposure, currency-strength rank, hierarchical correlation cluster gate |
| RiskAgent | SL/TP/position size |
| ExecutionAgent | MT5 order send, modify, partial close, trail |
| GuardianAgent | Pre-trade AND pre-order-send veto + global kill-switches |
| Orchestrator | Schedules cadences, fans events over the in-process bus |

## 2. FundamentalBiasAgent contract (pinned)

Per quality review §Critical (#2): **option B — Python computes, LLM narrates**.

Pipeline:
1. **Inputs (deterministic, Python only)**: news event JSON from Finnhub
   (event name, currency, actual, consensus, prior), 2Y yield series per G10,
   spot rate series, VIX level.
2. **Compute** (Python, reproducible, no LLM):
   - **Taylor-rule delta**: `i_implied = r* + π + 0.5(π − π*) + 0.5(y_gap)`.
     `r*`, `π*`, `y_gap` per-currency loaded from `config/macro_priors.yaml` (P1; v1 uses 1.0/2.0/0.0 placeholders, documented).
   - **2Y real-yield differential**: `r_real = i_2y − π_expected_2y`.
     v1 uses Finnhub yields and a 12-month-trailing-CPI proxy for π_expected.
   - **Mundell-Fleming sign**: fiscal-tag news → +; monetary-tag news → −. Tag via event-name regex (P1: classifier).
   - **NAIRU check**: `unemployment − nairu_ccy` (priors in `macro_priors.yaml`).
   - **Carry regime gate**: `(rate_diff > 300bps) AND (VIX < 15)` → on; flip on VIX>25.
3. **Aggregate** into `Bias(currency, score ∈ [-1, +1], magnitude_clamp ≤ 0.5)`.
   Clamp per security review §Major (LLM can never exceed 0.10 × 0.5 = 0.05 absolute
   contribution to confluence score, even if compromised).
4. **LLM (NIM via LiteLLM @ :4000)**: only narrates the score for the dashboard. Output
   schema is `Literal["bullish","bearish","neutral"] + str_explanation`. It cannot
   change the numeric bias. This is the prompt-injection containment.

The LLM is therefore **never on the critical path** of any trade decision. If the
LLM is unreachable, the system trades on the deterministic Python bias.

## 3. SL sizing (pinned)

Per quality review §Critical (#1) and security review:
- **Primary**: SL = structure boundary ± `atr_buffer_mult × ATR(14)`.
- **GARCH(1,1) on H1 returns** is computed and stored, but only feeds RiskAgent's
  size throttle (high-vol regime → smaller positions). It does NOT place stops in v1.
- This resolves the GARCH/ATR drift between Agent 1 P0 and `settings.yaml`.

## 4. Portfolio layer (pinned)

Per quality review §Critical (#3): **new PortfolioAgent** rather than overloading
RiskAgent. Runs after ConfluenceAgent produces a Setup, before RiskAgent sizes:

- **PCA factor exposure**: rolling 60-day daily returns of `symbols.whitelist`,
  3 PCs retained. Reject Setup if net |projection on any PC| > `pca_factor_exposure_cap`.
- **Currency-strength rank**: PCA on per-currency strength matrix; long leg must be
  top-2, short leg bottom-2, or block.
- **Hierarchical clustering**: Ward linkage on correlation distance; at most 1
  concurrent trade per cluster.

## 5. Order block (pinned)

Per quality review §Critical (#4): ICT-style, parameters in `config/settings.yaml`
under `indicators.order_block`:

> An **order block** is the last opposing candle before an impulsive move that
> displaces price by ≥ `min_displacement_atr × ATR(14)` and leaves a fair-value gap
> of ≥ `fvg_min_pips`. The block is valid until price closes through it (not just
> wicks). Search lookback: `lookback_bars`.

Single testable definition, mirrored in `indicators/structure.py` docstring when written.

## 6. Statistical testing framework (pinned)

Per quality review §Major:
- **Within-bar 28-pair scan**: BH-FDR (q=0.10) corrects multiple-comparison across pairs at one M15 close.
- **Across time**: SPRT on live trade outcomes (`H1: E[R]=0.15` vs `H0: E[R]=0`, α=0.05, β=0.20).
  SPRT halts strategy on H0 acceptance; promoted from P1 to P0.
- **Permutation test**: stationary bootstrap (Politis-Romano), NOT naive bar shuffle.
  Mean block length 20 bars; n=5000 resamples.

## 7. Versioning + reproducibility (pinned)

Per quality review §Major: every journal row and every backtest artifact carries
`{git_sha, settings_hash, strategy_version}`. Implemented in `core/versioning.py` (when
written) and required by `core/logging.py` structlog processor.

## 8. Logging event taxonomy (pinned)

Per quality review §Minor: canonical events only, no ad-hoc keys per agent.
Define once in `core/logging.py`:

```
setup_proposed, confluence_scored, portfolio_gated, risk_gated,
order_sent, fill, partial_close, sl_hit, tp_hit,
guardian_pre_trade_veto, guardian_pre_order_veto,
guardian_throttle, guardian_halt,
news_blackout_start, news_blackout_end,
bias_updated, regime_changed, kill_switch_armed,
config_loaded, backtest_bar
```

Every event MUST include `{ts_utc, git_sha, settings_hash, run_id}`.

## 9. Broker abstraction (pinned)

Per quality review §Minor: `broker/base.py` defines a `BrokerProtocol`
(Pydantic / typing.Protocol). `MT5Broker` (FxPesa) implements it in v1. Adding FBS
or any other broker in v2 is a new file, no refactor.

## 10. Guardian fail-safe (pinned)

Per security review §Critical:
- GuardianAgent emits a heartbeat every 5s into a shared `asyncio.Event`.
- ExecutionAgent refuses `order_send` if `last_heartbeat_ts` is older than
  `guardian.heartbeat_max_age_seconds = 30`.
- A separate watchdog process (`scripts/watchdog.py`, systemd unit) monitors the
  main process. On crash or hang, the watchdog flattens all positions via
  `MT5Broker.close_all_positions()` and Telegram-alerts.

## 11. MT5 disconnect policy (pinned)

Per security review §Major:
- On RPyC disconnect → halt new entries immediately.
- On reconnect → reconcile open positions and pending orders against last-known state
  (`broker/reconciliation.py`).
- Mismatch → halt + Telegram alert; no auto-retry of order sends (duplicate-fill risk).

## 12. RPyC hardening (pinned)

Per security review §Major:
- `rpyc>=6.0` (pinned in pyproject).
- `ThreadedServer` with `allow_public_attrs=False`, `allow_pickle=False`.
- Bind `127.0.0.1` only — never `0.0.0.0`.

## 13. Live-mode dual-confirm (pinned)

Per security review §Major: live trading requires ALL of:
- `Noema_MODE=live` in env
- `--live` CLI flag on `run_live.py`
- Interactive `y/N` confirmation prompt on the first start of any calendar day

## 14. P0 scope honesty (acknowledged)

Per quality review §Major (#11): the **TOP-5 from each of 6 unit-miners = 30 P0
items** is a 3-4 month build, not a 2-week sprint. v0.1 ships only the **architecture
TOP-5 minimum**:

- TrendAgent (MA-cross + HH/HL)
- StructureAgent (session highs/lows, weekly/monthly/yearly, order blocks)
- ConfluenceAgent with deterministic RSI + candlestick sub-scorers
- RiskAgent with ATR-based SL, TP at next liquidity, Kelly-fraction-capped size
- GuardianAgent: daily-loss + heartbeat + spread guard + news blackout

Everything else from the 30-item P0 list moves to v0.2/v0.3 with explicit issue
tickets. See `docs/ROADMAP.md`.

## 15. Pair universe (pinned)

Per quality review §Minor (#12): v1 = 5 pairs (`symbols.whitelist`). BH-FDR is
designed for arbitrary N (uses `len(active_setups)`), so the 28-pair design carries
over to v2 without code change.
