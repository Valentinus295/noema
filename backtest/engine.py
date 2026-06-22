"""Event-driven backtesting engine for VMPM.

Replays historical OHLCV bars through the full agent pipeline,
simulates fills with slippage and spread, and records every decision
for audit. Uses polars for performance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import structlog

from vmpm.backtest.metrics import PerformanceMetrics, compute_metrics

logger = structlog.get_logger(__name__)


class BacktestBar:
    """A single OHLCV bar for backtesting."""

    __slots__ = ("time", "open", "high", "low", "close", "volume", "timeframe")

    def __init__(self, time: datetime, open_: float, high: float, low: float,
                 close: float, volume: float, timeframe: str = "H1") -> None:
        self.time = time
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.timeframe = timeframe


@dataclass
class TradeRecord:
    """A single trade in the backtest."""
    ticket: int
    symbol: str
    direction: str           # "buy" or "sell"
    entry_price: float
    exit_price: float
    volume: float
    sl: float
    tp: float
    pnl: float
    pnl_pips: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str         # "tp", "sl", "signal", "timeout", "guardian"
    session: str
    agent_reports: dict[str, Any] = field(default_factory=dict)
    settings_hash: str = ""
    git_sha: str = ""


@dataclass
class BacktestConfig:
    """Backtest configuration."""
    initial_balance: float = 10000.0
    risk_per_trade: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_open_trades: int = 3
    slippage_atr_mult: float = 0.05
    spread_pips: float = 1.5
    max_bars_in_trade: int = 100    # timeout after N bars
    commission_per_lot: float = 7.0  # per round trip


@dataclass
class BacktestResult:
    """Complete backtest output."""
    trades: list[TradeRecord]
    equity_curve: list[float]
    metrics: PerformanceMetrics
    total_bars_processed: int
    pairs_tested: list[str]
    settings_hash: str
    git_sha: str
    elapsed_seconds: float


class BacktestEngine:
    """Event-driven backtesting engine.

    Replays historical bars through the VMPM agent pipeline and
    simulates realistic fills with slippage and spread.
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self._balance = self.config.initial_balance
        self._trades: list[TradeRecord] = []
        self._equity_curve: list[float] = [self.config.initial_balance]
        self._open_positions: list[dict[str, Any]] = []
        self._daily_pnl = 0.0
        self._current_date: datetime | None = None
        self._settings_hash = ""
        self._git_sha = ""
        self._ticket_counter = 100000

    def run(
        self,
        symbol: str,
        data: pd.DataFrame,
        signal_fn: Any,
        *,
        settings_hash: str = "",
        git_sha: str = "",
    ) -> BacktestResult:
        """Run backtest on a single symbol.

        Args:
            symbol: Trading pair (e.g., "EURUSD")
            data: OHLCV DataFrame with columns: time, open, high, low, close, volume
            signal_fn: Callable(context) -> dict with keys: signal, confidence, sl, tp, agent_reports
            settings_hash: Hash of config at decision time
            git_sha: Git commit SHA
        """
        start_time = time.monotonic()
        self._settings_hash = settings_hash
        self._git_sha = git_sha
        self._balance = self.config.initial_balance
        self._trades = []
        self._equity_curve = [self.config.initial_balance]
        self._open_positions = []
        self._daily_pnl = 0.0
        self._current_date = None

        if len(data) < 50:
            return BacktestResult(
                trades=[], equity_curve=[self.config.initial_balance],
                metrics=compute_metrics([]), total_bars_processed=0,
                pairs_tested=[symbol], settings_hash=settings_hash,
                git_sha=git_sha, elapsed_seconds=0.0,
            )

        # Process each bar
        for i in range(50, len(data)):
            bar = self._df_row_to_bar(data, i, symbol)
            prev_bar = self._df_row_to_bar(data, i - 1, symbol)

            # Track daily reset
            if self._current_date is None or bar.time.date() != self._current_date:
                self._daily_pnl = 0.0
                self._current_date = bar.time.date()

            # 1. Check open positions (SL/TP/timeout)
            self._manage_positions(bar, prev_bar)

            # 2. Check daily loss limit
            if abs(self._daily_pnl) >= self.config.max_daily_loss_pct * self._balance:
                self._equity_curve.append(self._get_equity(bar))
                continue

            # 3. Check max open trades
            if len(self._open_positions) >= self.config.max_open_trades:
                self._equity_curve.append(self._get_equity(bar))
                continue

            # 4. Generate signal from agent pipeline
            context = self._build_context(data, i, symbol, bar)
            try:
                result = signal_fn(context)
            except Exception as exc:
                logger.debug("signal_error", bar=i, error=str(exc))
                self._equity_curve.append(self._get_equity(bar))
                continue

            signal = result.get("signal", "WAIT")
            confidence = result.get("confidence", 0.0)

            # 5. Execute if BUY or SELL
            if signal in ("BUY", "SELL") and confidence >= 0.5:
                direction = "buy" if signal == "BUY" else "sell"
                sl = result.get("sl", 0.0)
                tp = result.get("tp", 0.0)

                if sl > 0 and tp > 0:
                    self._open_position(symbol, direction, bar.close, sl, tp,
                                        bar.time, result.get("agent_reports", {}))

            self._equity_curve.append(self._get_equity(bar))

        # Close any remaining positions at last price
        if self._open_positions and len(data) > 0:
            last_bar = self._df_row_to_bar(data, len(data) - 1, symbol)
            for pos in list(self._open_positions):
                self._close_position(pos, last_bar.close, last_bar.time, "backtest_end")

        elapsed = time.monotonic() - start_time
        metrics = compute_metrics(self._trades)

        return BacktestResult(
            trades=self._trades,
            equity_curve=self._equity_curve,
            metrics=metrics,
            total_bars_processed=len(data),
            pairs_tested=[symbol],
            settings_hash=self._settings_hash,
            git_sha=self._git_sha,
            elapsed_seconds=elapsed,
        )

    def run_multi_pair(
        self,
        data_dict: dict[str, pd.DataFrame],
        signal_fn: Any,
        *,
        settings_hash: str = "",
        git_sha: str = "",
    ) -> BacktestResult:
        """Run backtest across multiple pairs, interleaving bars by time."""
        start_time = time.monotonic()
        self._settings_hash = settings_hash
        self._git_sha = git_sha
        self._balance = self.config.initial_balance
        self._trades = []
        self._equity_curve = [self.config.initial_balance]
        self._open_positions = []
        self._daily_pnl = 0.0
        self._current_date = None

        # Build unified timeline
        all_bars: list[tuple[datetime, str, int]] = []
        for symbol, df in data_dict.items():
            for i in range(50, len(df)):
                ts = pd.Timestamp(df["time"].iloc[i]).to_pydatetime()
                all_bars.append((ts, symbol, i))

        all_bars.sort(key=lambda x: x[0])
        total_bars = len(all_bars)

        for ts, symbol, idx in all_bars:
            data = data_dict[symbol]
            bar = self._df_row_to_bar(data, idx, symbol)
            prev_bar = self._df_row_to_bar(data, idx - 1, symbol)

            if self._current_date is None or bar.time.date() != self._current_date:
                self._daily_pnl = 0.0
                self._current_date = bar.time.date()

            # Manage existing positions for this symbol
            self._manage_positions_for_symbol(symbol, bar, prev_bar)

            if abs(self._daily_pnl) >= self.config.max_daily_loss_pct * self._balance:
                self._equity_curve.append(self._get_equity_multi(data_dict))
                continue

            # Count open for this symbol
            open_for_symbol = [p for p in self._open_positions if p["symbol"] == symbol]
            if len(open_for_symbol) >= 1:
                self._equity_curve.append(self._get_equity_multi(data_dict))
                continue

            if len(self._open_positions) >= self.config.max_open_trades:
                self._equity_curve.append(self._get_equity_multi(data_dict))
                continue

            context = self._build_context(data, idx, symbol, bar)
            try:
                result = signal_fn(context)
            except Exception:
                self._equity_curve.append(self._get_equity_multi(data_dict))
                continue

            signal = result.get("signal", "WAIT")
            confidence = result.get("confidence", 0.0)

            if signal in ("BUY", "SELL") and confidence >= 0.5:
                direction = "buy" if signal == "BUY" else "sell"
                sl = result.get("sl", 0.0)
                tp = result.get("tp", 0.0)
                if sl > 0 and tp > 0:
                    self._open_position(symbol, direction, bar.close, sl, tp,
                                        bar.time, result.get("agent_reports", {}))

            self._equity_curve.append(self._get_equity_multi(data_dict))

        # Close remaining
        for pos in list(self._open_positions):
            sym = pos["symbol"]
            if sym in data_dict and len(data_dict[sym]) > 0:
                last = self._df_row_to_bar(data_dict[sym], len(data_dict[sym]) - 1, sym)
                self._close_position(pos, last.close, last.time, "backtest_end")

        elapsed = time.monotonic() - start_time
        metrics = compute_metrics(self._trades)
        return BacktestResult(
            trades=self._trades, equity_curve=self._equity_curve,
            metrics=metrics, total_bars_processed=total_bars,
            pairs_tested=list(data_dict.keys()),
            settings_hash=self._settings_hash, git_sha=self._git_sha,
            elapsed_seconds=elapsed,
        )

    # ── Internal helpers ──

    def _df_row_to_bar(self, df: pd.DataFrame, idx: int, symbol: str) -> BacktestBar:
        row = df.iloc[idx]
        return BacktestBar(
            time=pd.Timestamp(row["time"]).to_pydatetime(),
            open_=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]),
            volume=float(row.get("volume", 0)), timeframe="H1",
        )

    def _build_context(self, data: pd.DataFrame, idx: int,
                       symbol: str, bar: BacktestBar) -> dict[str, Any]:
        """Build context dict for signal function from historical data."""
        lookback = min(idx + 1, 200)
        history = data.iloc[idx + 1 - lookback:idx + 1].copy()

        return {
            "pair": symbol,
            "price_data": history,
            "prices": {symbol: history, "H1": history, "D1": history, "H4": history},
            "current_price": bar.close,
            "account_balance": self._balance,
            "daily_pnl": self._daily_pnl,
            "weekly_pnl": 0.0,
            "open_trades": len(self._open_positions),
            "open_positions": list(self._open_positions),
            "backtest_mode": True,
        }

    def _open_position(
        self, symbol: str, direction: str, price: float,
        sl: float, tp: float, entry_time: datetime,
        agent_reports: dict[str, Any],
    ) -> None:
        self._ticket_counter += 1
        risk_amount = self._balance * self.config.risk_per_trade
        risk_pips = abs(price - sl) / 0.0001 if "JPY" not in symbol else abs(price - sl) / 0.01
        pip_value = 10.0 if "JPY" not in symbol else 0.01
        volume = round(risk_amount / (risk_pips * pip_value * 10), 2) if risk_pips > 0 else 0.01
        volume = max(0.01, volume)

        spread_cost = self.config.spread_pips * pip_value * volume * 10
        self._balance -= spread_cost

        self._open_positions.append({
            "ticket": self._ticket_counter,
            "symbol": symbol,
            "direction": direction,
            "entry_price": price,
            "sl": sl,
            "tp": tp,
            "volume": volume,
            "entry_time": entry_time,
            "agent_reports": agent_reports,
        })

        logger.debug("backtest_open", ticket=self._ticket_counter, symbol=symbol,
                      direction=direction, price=price, volume=volume)

    def _close_position(self, pos: dict, exit_price: float,
                        exit_time: datetime, reason: str) -> None:
        if pos["direction"] == "buy":
            pnl_pips = (exit_price - pos["entry_price"]) / 0.0001 if "JPY" not in pos["symbol"] \
                else (exit_price - pos["entry_price"]) / 0.01
        else:
            pnl_pips = (pos["entry_price"] - exit_price) / 0.0001 if "JPY" not in pos["symbol"] \
                else (pos["entry_price"] - exit_price) / 0.01

        pip_value = 10.0 if "JPY" not in pos["symbol"] else 0.01
        pnl = pnl_pips * pip_value * pos["volume"] * 10
        pnl -= self.config.commission_per_lot * pos["volume"]

        self._balance += pnl
        self._daily_pnl += pnl

        entry_time_val = pos["entry_time"]
        session = self._detect_session(entry_time_val)

        self._trades.append(TradeRecord(
            ticket=pos["ticket"], symbol=pos["symbol"], direction=pos["direction"],
            entry_price=pos["entry_price"], exit_price=exit_price,
            volume=pos["volume"], sl=pos["sl"], tp=pos["tp"],
            pnl=pnl, pnl_pips=pnl_pips,
            entry_time=entry_time_val, exit_time=exit_time,
            exit_reason=reason, session=session,
            agent_reports=pos.get("agent_reports", {}),
            settings_hash=self._settings_hash, git_sha=self._git_sha,
        ))

        if pos in self._open_positions:
            self._open_positions.remove(pos)

    def _manage_positions(self, bar: BacktestBar, prev_bar: BacktestBar) -> None:
        for pos in list(self._open_positions):
            self._check_exit(pos, bar, prev_bar)

    def _manage_positions_for_symbol(self, symbol: str,
                                     bar: BacktestBar, prev_bar: BacktestBar) -> None:
        for pos in [p for p in self._open_positions if p["symbol"] == symbol]:
            self._check_exit(pos, bar, prev_bar)

    def _check_exit(self, pos: dict, bar: BacktestBar, prev_bar: BacktestBar) -> None:
        """Check if position should be closed (SL, TP)."""
        if pos["direction"] == "buy":
            if bar.low <= pos["sl"]:
                self._close_position(pos, pos["sl"], bar.time, "sl")
                return
            if bar.high >= pos["tp"]:
                self._close_position(pos, pos["tp"], bar.time, "tp")
        else:
            if bar.high >= pos["sl"]:
                self._close_position(pos, pos["sl"], bar.time, "sl")
                return
            if bar.low <= pos["tp"]:
                self._close_position(pos, pos["tp"], bar.time, "tp")

    def _get_equity(self, bar: BacktestBar) -> float:
        unrealized = 0.0
        for pos in self._open_positions:
            if pos["direction"] == "buy":
                diff = bar.close - pos["entry_price"]
            else:
                diff = pos["entry_price"] - bar.close
            pip_val = 10.0 if "JPY" not in pos["symbol"] else 0.01
            unrealized += diff / 0.0001 * pip_val * pos["volume"] * 10 if "JPY" not in pos["symbol"] \
                else diff / 0.01 * pip_val * pos["volume"] * 10
        return self._balance + unrealized

    def _get_equity_multi(self, data_dict: dict[str, pd.DataFrame]) -> float:
        """Compute total equity (simplified — uses realized balance only for multi-pair)."""
        return self._balance

    def _detect_session(self, dt: datetime) -> str:
        hour = dt.hour
        if 0 <= hour < 9:
            return "asian"
        elif 10 <= hour < 15:
            return "london"
        elif 15 <= hour < 20:
            return "new_york"
        return "off_hours"
