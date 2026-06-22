# Noema

Multi-agent forex trading system on MT5. Sniper-style, multi-confirmation, statistically grounded.
Built to encode the Valentine BSc Economics & Statistics curriculum as live trading logic.

## Strategy in one sentence

Fundamental bias → trend (D1/H4/H1) → S/R zones (session/D/W/M/Y highs+lows + order blocks) → retest →
RSI alignment (M15/H1/D1) → candlestick confirmation → execute → SL beyond structure → TP at next liquidity.

## Architecture

10 agents, single asyncio event loop, deterministic per-tick logic, LLM (NIM via LiteLLM @ :4000)
only for fundamental-bias scoring on news events and optional borderline-setup sanity checks.

```
[MT5 bars]──▶ indicators ──▶ TrendAgent ─┐
                                          ├─▶ ConfluenceAgent ─▶ RiskAgent ─▶ ExecutionAgent
[news feed]──▶ FundamentalBiasAgent (LLM)─┘             │             │
                                                        ▼             ▼
                                                  GuardianAgent (kill-switches)
```

See `docs/ARCHITECTURE.md` for the full design and `docs/CURRICULUM_MAPPING.md`
for which academic concept lives in which file.

## Quick start (Linux + Wine)

```bash
cd ~/noema
uv sync                                    # installs deps from pyproject.toml
cp .env.example .env && $EDITOR .env       # fill in MT5 + Telegram + LiteLLM keys
uv run scripts/fetch_history.py            # cache bar history
uv run scripts/run_backtest.py             # validate edge before going live
uv run scripts/run_live.py --broker fxpesa # paper or live (config-gated)
```

## Broker

v1: **FxPesa** (live), single MT5 terminal running under Wine.
v2 roadmap: add FBS as second broker, route by best spread.

## Status

v0.1 — design + scaffold, reviewed by security and quality before any code lands.
See `docs/SECURITY.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/CURRICULUM_MAPPING.md`.

## Reviews

Both security and quality reviews ran on the design before engineering began.
Reports are in `research/REVIEWS.md`. CHANGE_REQUESTED items resolved before v0.1 lands.

