# VMPM Reference Repos — Extracted Knowledge
## Team Skills & Patterns Guide

---

## 1. SMC Analysis Engine (from JARVIS + SURGE-WSI)

### JARVIS `core/smc.py` — Best-in-class SMC implementation
**When to use:** Any SMC analysis (order blocks, FVGs, liquidity sweeps, market structure)

**Key patterns:**
- **Swing detection:** Fractal-style with configurable `lookback` (default 3). A swing high = price higher than `lookback` candles on each side, and unique max.
- **Market structure:** Walk-forward that tracks last swing high/low. Close above last SH + prior trend bearish = CHoCH (bullish reversal). Close above last SH + already bullish = BOS (continuation).
- **Order Blocks:** Last opposing candle before `>=2` consecutive impulsive candles. OB is valid until price closes through it (not wicks).
- **FVG:** 3-candle imbalance. Bullish: `low[i+1] > high[i-1]`. Tracks mitigation (price revisits gap).
- **Liquidity Sweeps:** Price penetrates prior swing level but closes back on original side same candle. Search lookback: 30 bars.
- **Entry model:** Requires confluence of HTF trend + structure event + sweep + unmitigated OB + optional FVG overlap. Validates distance from OB ≤ max_distance_pips.

**Dataclass structure (portable):**
```python
Swing, StructureEvent, OrderBlock, FVG, LiquiditySweep, Setup, SMCReport
```

### SURGE-WSI `src/analysis/poi_detector.py` — SMC via smartmoneyconcepts library
**When to use:** When you want to leverage the `smartmoneyconcepts` Python library for order blocks, FVGs, BOS/CHOCH

**Key pattern:** Uses `smartmoneyconcepts.smc` class. Handles encoding issues (suppresses star emoji on Windows).
- POI types: OB_BULL, OB_BEAR, FVG_BULL, FVG_BEAR
- POI quality scoring system (0-100)
- Zone proximity monitoring

---

## 2. Statistical / Econometric Layer (from SURGE-WSI)

### Kalman Filter `src/analysis/kalman_filter.py`
**When to use:** Noise reduction before HMM regime detection. NOT for signal generation.

**Key patterns:**
- **Single Kalman:** 3-state model [price, velocity, acceleration] with constant acceleration transition matrix.
- **MultiScaleKalman:** 3 filters (fast/medium/slow) with different process/measurement noise:
  - Fast: q=0.05, r=0.05 (scalping-sensitive)
  - Medium: q=0.01, r=0.1 (intraday balanced) — PRIMARY
  - Slow: q=0.001, r=0.2 (swing trend)
- **Outputs:** smoothed_price, velocity, acceleration, residual, uncertainty
- **HMM features:** Returns + volatility from medium filter
- **Dependency:** `filterpy` library

### HMM Regime Detector `src/analysis/regime_detector.py`
**When to use:** Primary market filter — determines WHEN to trade

**Key patterns:**
- 3 states: BULLISH, BEARISH, SIDEWAYS
- Probability threshold: 60% for tradeable regime
- Output: `RegimeInfo` with probability, bias (BUY/SELL/NONE), `is_tradeable` boolean
- Rules: BULLISH + prob≥60% → only look for buys. BEARISH + prob≥60% → only look for sells. SIDEWAYS → no trade.
- **Dependency:** `hmmlearn` library

### Benefits for VMPM:
- The econometrics engine (`analysis/econometrics.py`) already has ARIMA, GARCH, cointegration, PCA
- Adding Kalman + HMM would complete the statistical layer
- Kalman → HMM → SMC creates a 3-layer cascade: noise reduction → regime → entry

---

## 3. MT5 Integration Patterns (from JARVIS + pyeventbt)

### JARVIS `core/mt5_connector.py` — Production MT5 wrapper
**When to use:** Direct MT5 connection, data fetching, order placement

**Key patterns:**
- **Connection:** Retry logic (3 attempts, 2s delay). `ensure_connected()` checks terminal_info.
- **Timeframe map:** M1/M5/M15/M30/H1/H4/D1
- **Data:** `get_candles(symbol, timeframe, count)` → DataFrame with [time, open, high, low, close, volume, spread]
- **Orders:** `place_pending_order()` supports buy_limit/sell_limit/buy_stop/sell_stop with expiration. Works with killzone-based entry.
- **Position management:** `modify_position_sl()` for trailing stops, `cancel_order()` for timeout
- **Credentials:** `.env` file loaded via python-dotenv

### pyeventbt — Event-driven MT5 architecture
**When to use:** When building event-driven backtesting + live trading on MT5

**Key patterns:**
- Event-driven architecture with connector/simulator split
- Clean entity separation: Tick, TradeRequest, OrderSendResult, AccountInfo, SymbolInfo
- MT5 simulator connector for backtesting using real MT5 data
- Broker interface abstraction

---

## 4. Risk Management Patterns (from JARVIS + SURGE-WSI)

### JARVIS `core/risk_manager.py` — Clean pre-trade risk checks
**When to use:** Pre-trade validation before order placement

**Key patterns:**
- **Lot size calculation:** `risk_amount / ((stop_distance / tick_size) * tick_value)` rounded DOWN to nearest volume_step
- **Session awareness:** `within_active_window(now, start, end, active_days)` with named sessions
- **Trade evaluation:** `evaluate_trade()` checks max_positions, existing_symbol_positions, min_rr, volume > 0
- **Returns:** `RiskDecision(allowed, volume, reason)` — clean boolean gate

### SURGE-WSI `src/trading/risk_manager.py` — Dynamic risk sizing
**When to use:** When you want quality-based dynamic position sizing

**Key patterns:**
- Quality-gated risk: High>80 → 1.5% | Medium 60-80 → 1.0% | Low<60 → 0.5%
- Zero Losing Months config: max lot 0.5, max loss/trade 0.1%, monthly stop 2%
- Daily profit target + daily loss limit
- RiskParams dataclass: lot_size, risk_amount, risk_percent, sl_pips, position_value

---

## 5. Architecture Patterns (from QuantDinger)

### QuantDinger — 8.5k⭐ production quant platform
**When to use:** Reference for production architecture patterns

**Key patterns to extract:**
- **Strategy position sync:** auto-reconciliation between strategy state and exchange positions
- **Grid engine:** automated grid trading with risk exits
- **AI bot symbol detection:** ML model for symbol selection
- **Cross-sectional strategies:** multi-asset analysis
- **Data provider abstraction:** unified interface across exchanges
- **Experiment services:** A/B testing framework for strategies
- **Risk guard:** circuit breakers, exposure limits, drawdown controls
- **Trade close reason tracking:** every exit has a coded reason — feeds learning

**Relevant for VMPM:**
- Strategy position sync → for broker reconciliation
- Risk guard → for GuardianAgent kill-switches
- Trade close reason tracking → for LearningAgent
- Experiment services → for strategy optimization

---

## 6. Backtesting Patterns (from SURGE-WSI)

### Massive backtest library — ~100+ backtest scripts
**Key patterns observed:**
- **Iterative optimization:** v1 → v2 → v3... → v6.4 shows progressive refinement
- **Monthly analysis:** dedicated scripts to diagnose losing months
- **Parameter sweeps:** systematic testing of thresholds, filters, timeframes
- **Strategy comparison:** side-by-side comparison of different approaches
- **Multi-year validation:** 2023, 2024, 2025 separate backtests
- **Quality sweep:** finds optimal parameter combinations

**For VMPM's backtesting engine:**
- Adopt the "diagnose losing months" pattern
- Add systematic parameter sweep capability
- Track trade close reasons (from QuantDinger pattern)

---

## 7. Quick Reference: Which Repo for What

| Need | Go to | File(s) |
|------|-------|---------|
| Order block detection | JARVIS | `core/smc.py` → `detect_order_blocks()` |
| FVG detection | JARVIS | `core/smc.py` → `detect_fvgs()` |
| Liquidity sweep detection | JARVIS | `core/smc.py` → `detect_liquidity_sweeps()` |
| Market structure (BOS/CHoCH) | JARVIS | `core/smc.py` → `detect_structure()` |
| SMC entry model | JARVIS | `core/smc.py` → `find_setup()` |
| Kalman noise reduction | SURGE-WSI | `src/analysis/kalman_filter.py` |
| HMM regime detection | SURGE-WSI | `src/analysis/regime_detector.py` |
| MT5 connection + orders | JARVIS | `core/mt5_connector.py` |
| Pre-trade risk checks | JARVIS | `core/risk_manager.py` |
| Dynamic position sizing | SURGE-WSI | `src/trading/risk_manager.py` |
| Event-driven MT5 backtesting | pyeventbt | `pyeventbt/broker/mt5_broker/` |
| Production quant architecture | QuantDinger | `backend_api_python/app/` |
| Strategy optimization workflow | SURGE-WSI | `backtest/` directory |
| Claude-based trading workflow | cbt-framework | `templates/` directory |

---

## 8. Dependencies to Add to VMPM

From these repos, useful libraries:
- `filterpy` — Kalman filtering (SURGE-WSI pattern)
- `hmmlearn` — Hidden Markov Models (SURGE-WSI pattern)
- `smartmoneyconcepts` — SMC library (SURGE-WSI pattern)
- `MetaTrader5` — MT5 Python API (JARVIS pattern)
- `python-dotenv` — Environment config (already likely present)

---

*Generated by Atlas for VMPM team — June 23, 2026*
*Sources: JARVIS, SURGE-WSI, QuantDinger, pyeventbt, cbt-framework*
