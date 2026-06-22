# Changelog

All notable changes to the Noema will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-09

### 🎉 Initial Release

The Noema v1.0.0 is a **multi-agent forex trading system** that replicates the reasoning of a disciplined institutional trader.

### 🤖 Agents (17 total)

#### Analysis Department
- **MacroEconomicAgent** - Fundamental analysis, economic calendar, currency strength scoring
- **CurrencyStrengthAgent** - Ranks currencies by relative strength using technical + fundamental data
- **MarketStructureAgent** - Detects HH/HL/LH/LL, BOS, CHoCH for trend identification
- **InstitutionalFootprintAgent** - Identifies Order Blocks, Fair Value Gaps, Liquidity Sweeps
- **SupportResistanceAgent** - Maps Session/D/W/M/Y highs+low as buy/sell zones
- **SessionIntelligenceAgent** - Trading session awareness and probability scoring

#### Signal Department
- **OpportunitySurveillanceAgent** - Monitors zone proximity and trade candidates
- **MomentumAgent** - RSI confirmation across M15/H1/D1 timeframes
- **PriceActionAgent** - Candlestick pattern detection (8 reversal patterns)

#### Decision Department
- **TradeThesisAgent** - Builds comprehensive case for/against trades
- **DevilsAdvocateAgent** - Critical analysis to destroy bad trades
- **CIOAgent** - Final decision maker (BUY/SELL/WAIT/REJECT)

#### Execution Department
- **RiskManagerAgent** - Position sizing, daily/weekly loss limits, correlation checks
- **ExecutionAgent** - Order placement via MT5 (FX Pesa, FBS compatible)
- **TradeManagementAgent** - SL/TP management, breakeven moves, partial close

#### Learning Department
- **PerformanceAnalystAgent** - Tracks trade outcomes and performance metrics
- **LearningAgent** - Post-trade pattern learning and strategy improvement

### 📊 Analysis Modules

- **EconometricsEngine** - ARIMA, GARCH, Cointegration, ADF, PCA, Hurst Exponent
- **FundamentalAnalyzer** - Economic event scoring, currency strength calculation
- **TechnicalAnalyzer** - EMA 50/200, RSI, MACD, ADX, ATR (TA-Lib or pandas fallback)
- **SMCForecaster** - Order Blocks, Fair Value Gaps, Liquidity Sweeps, BOS/CHoCH
- **CandlestickDetector** - 8 reversal patterns with strength scoring

### 🔧 Infrastructure

- **Async MessageBus** - Pub/sub inter-agent communication
- **TradingPipeline** - 12-phase state machine with strict state transitions
- **BrokerBase** - Abstract broker interface
- **MT5Broker** - MetaTrader 5 integration (FX Pesa, FBS)
- **PaperBroker** - Simulated trading for safe testing
- **MarketDataFeed** - OHLCV data from MT5 or synthetic generation
- **EconomicCalendar** - Economic event data with API + fallback
- **NoemaConfig** - YAML configuration with environment variable overrides

### 🎯 12-Phase Trading Pipeline

1. Fundamental Analysis → Currency strength scores
2. Trend Identification → Bullish/Bearish/Range
3. Support & Resistance → Buy/Sell zones mapped
4. Order Block Analysis → Institutional footprints
5. Waiting Phase → WAIT for price to reach zone
6. RSI Confirmation → RSI ≤30 (buy) / ≥70 (sell)
7. Candlestick Confirmation → Valid reversal pattern
8. Trade Validation → All conditions met
9. Risk Management → Position sizing, SL/TP
10. Execution → Place order via MT5
11. Trade Management → Monitor, move to BE, partial close
12. Post-Trade Learning → Store outcome, update knowledge

### 📈 Trading Pairs

- EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, NZDUSD, USDCAD

### 🛡️ Risk Management

- Configurable risk per trade (default: 1%)
- Maximum daily loss limit (default: 3%)
- Maximum weekly loss limit (default: 8%)
- Minimum risk/reward ratio (default: 1:2)
- Maximum open trades limit
- Correlation risk checks

### 📝 Configuration

- YAML-based configuration (`config/settings.yaml`)
- Environment variable overrides (`.env`)
- Multiple broker support (paper, MT5)
- Configurable trading pairs and timeframes

---

## [Unreleased]

### Planned Features
- Unit tests for all agents and analysis modules
- Integration tests for full pipeline
- Backtesting engine
- Telegram notifications
- Performance dashboard
- LangGraph orchestration (v2.0)
- LLM integration for fundamental bias
- Multi-broker routing
- Advanced portfolio management
- Web-based monitoring UI

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| 1.0.0 | 2026-06-09 | Initial release with 17 agents, 12-phase pipeline |
| 0.1.0 | 2026-06-09 | Design + scaffold (internal) |

---

## Contributors

- **Valentine** - Creator and Lead Developer
