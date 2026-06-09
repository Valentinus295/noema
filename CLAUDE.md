# VMPM — Valentine Money Printing Machine

## Project Identity
- **Full Name:** Valentine Money Printing Machine (VMPM)
- **Version:** 1.0.0 (initial release)
- **Repository:** https://github.com/ovalentine964/valentine-money-printing-machine (private)
- **Owner:** Valentine (ovalentine964)
- **Language:** Python 3.11+
- **Build System:** Hatchling (pyproject.toml)

## What This Is
A **multi-agent forex trading system** that replicates the reasoning process of a disciplined institutional trader. It uses 17 specialized AI agents working in a 12-phase pipeline to analyze markets and execute trades on MT5 (FX Pesa, FBS brokers).

## Owner Background
- **BSc Economics & Statistics** (4th year, semester 2)
- Strong in: Econometrics, Time Series Analysis, Hypothesis Testing, Multivariate Analysis, Probability Theory
- Weave this background into the system's analytical brain (ARIMA, GARCH, cointegration, PCA, hypothesis testing)

## Architecture Overview
```
[MT5 bars]──▶ indicators ──▶ TrendAgent ─┐
                                          ├─▶ ConfluenceAgent ─▶ RiskAgent ─▶ ExecutionAgent
[news feed]──▶ FundamentalBiasAgent (LLM)─┘             │             │
                                                        ▼             ▼
                                                  GuardianAgent (kill-switches)
```

## 12-Phase Trading Pipeline
1. Fundamental Analysis (Macro Economic Agent)
2. Trend Identification (Market Structure Agent)
3. Support & Resistance Mapping (S/R Agent + Order Block Agent)
4. Order Block Analysis (Institutional Footprint Agent)
5. Waiting Phase (Session Intelligence Agent)
6. Price Arrives at Zone (Opportunity Surveillance Agent)
7. RSI Confirmation (Momentum Agent)
8. Candlestick Confirmation (Price Action Agent)
9. Trade Validation (Trade Thesis + Devil's Advocate + CIO)
10. Risk Management (Risk Manager Agent)
11. Execution (Execution Agent)
12. Post-Trade Learning (Performance Analyst + Learning Agent)

## 17 Agents (by department)

### Analysis Agents
| # | Agent | File | Purpose |
|---|-------|------|---------|
| 1 | MacroEconomicAgent | agents/macro.py | Fundamental analysis, economic calendar |
| 2 | CurrencyStrengthAgent | agents/currency.py | Ranks currencies by relative strength |
| 3 | MarketStructureAgent | agents/structure.py | HH/HL/LH/LL, BOS, CHoCH detection |
| 4 | InstitutionalFootprintAgent | agents/institutional.py | Order blocks, FVG, liquidity sweeps |
| 5 | SupportResistanceAgent | agents/sr.py | Session/D/W/M/Y highs+low mapping |
| 6 | SessionIntelligenceAgent | agents/session.py | Trading session awareness |

### Signal Agents
| # | Agent | File | Purpose |
|---|-------|------|---------|
| 7 | OpportunitySurveillanceAgent | agents/opportunity.py | Zone proximity monitoring |
| 8 | MomentumAgent | agents/momentum.py | RSI confirmation M15/H1/D1 |
| 9 | PriceActionAgent | agents/price_action.py | Candlestick pattern detection |

### Decision Agents
| # | Agent | File | Purpose |
|---|-------|------|---------|
| 10 | TradeThesisAgent | agents/thesis.py | Builds case for/against trade |
| 11 | DevilsAdvocateAgent | agents/devil.py | Destroys bad trades |
| 12 | CIOAgent | agents/cio.py | Final decision maker |

### Execution Agents
| # | Agent | File | Purpose |
|---|-------|------|---------|
| 13 | RiskManagerAgent | agents/risk.py | Position sizing, loss limits |
| 14 | ExecutionAgent | agents/execution.py | Order placement via MT5 |
| 15 | TradeManagementAgent | agents/management.py | SL/TP management |

### Learning Agents
| # | Agent | File | Purpose |
|---|-------|------|---------|
| 16 | PerformanceAnalystAgent | agents/performance.py | Trade outcome tracking |
| 17 | LearningAgent | agents/learning.py | Post-trade pattern learning |

## Analysis Modules
| Module | File | Purpose |
|--------|------|---------|
| EconometricsEngine | analysis/econometrics.py | ARIMA, GARCH, Cointegration, ADF, PCA, Hurst |
| FundamentalAnalyzer | analysis/fundamental.py | Economic event scoring, currency strength |
| TechnicalAnalyzer | analysis/technical.py | EMA 50/200, RSI, MACD, ADX, ATR (TA-Lib or pandas) |
| SMCForecaster | analysis/smc.py | Order Blocks, FVG, Liquidity Sweeps, BOS/CHoCH |
| CandlestickDetector | analysis/candlestick.py | Engulfing, Morning/Evening Star, Hammer, Tweezers |

## Infrastructure
| Component | File | Purpose |
|-----------|------|---------|
| Agent (base) | core/agent.py | Base class for all agents, AgentReport dataclass |
| MessageBus | core/message_bus.py | Async pub/sub inter-agent communication |
| TradingPipeline | core/state_machine.py | 12-phase state machine with strict transitions |
| VMPMConfig | core/config.py | YAML config with env var overrides |
| BrokerBase | broker/base.py | Abstract broker interface |
| MT5Broker | broker/mt5.py | MetaTrader 5 integration (FX Pesa, FBS) |
| PaperBroker | broker/paper.py | Simulated trading for testing |
| MarketDataFeed | data/feed.py | OHLCV data from MT5 or synthetic |
| EconomicCalendar | data/calendar.py | Economic event data |
| VMPMOrchestrator | main.py | Main entry point, coordinates all agents |

## Key Config (config/settings.yaml)
- Broker type: paper (default) or mt5
- Risk per trade: 1%
- Max daily loss: 3%
- Max weekly loss: 8%
- Min risk/reward: 1:2
- Pairs: EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, NZDUSD, USDCAD
- Timeframes: D1 (primary), H4 (secondary), H1 (entry), M15 (confirmation)

## How to Run
```bash
cd /home/valentinetech/vmpm
python -m vmpm.main --mode paper --pair EURUSD    # Paper trading
python -m vmpm.main --mode analyze --pair EURUSD  # Single analysis
python -m vmpm.main --mode run                     # Continuous (needs MT5)
```

## Current Status (as of June 2026)
- ✅ All 17 agents implemented
- ✅ All analysis modules implemented
- ✅ MT5 and Paper broker integration
- ✅ Message bus and state machine
- ✅ Main orchestrator with full 12-phase pipeline
- ✅ Config system with YAML + env vars
- ✅ Pushed to GitHub (private repo)
- ⬜ Unit tests needed
- ⬜ Integration tests needed
- ⬜ Windows VPS setup for MT5 (FX Pesa/FBS)
- ⬜ Telegram notifications
- ⬜ Dashboard/monitoring
- ⬜ Backtesting engine
- ⬜ Live trading validation

## Todo Tracker
- [ ] Add unit tests for all agents and analysis modules
- [ ] Add integration tests for the full pipeline
- [ ] Set up Windows VPS with Wine + MT5 for live trading
- [ ] Configure FX Pesa and FBS broker accounts
- [ ] Add Telegram bot notifications for trade alerts
- [ ] Build a monitoring dashboard
- [ ] Implement backtesting engine
- [ ] Add LLM integration for fundamental bias scoring (via LiteLLM proxy)
- [ ] Performance optimization (parallel agent execution)
- [ ] Add more candlestick patterns and SMC concepts
