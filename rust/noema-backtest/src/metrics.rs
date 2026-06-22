//! Backtest performance metrics.
//!
//! Tracks drawdown, Sharpe ratio, profit factor, and other
//! risk-adjusted performance measures.

use serde::{Deserialize, Serialize};

/// Performance metrics for a backtest run.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Metrics {
    /// Initial account balance
    pub initial_balance: f64,
    /// Total number of ticks processed
    pub ticks_processed: u64,
    /// Total number of trades opened
    pub trades_opened: u64,
    /// Total number of trades closed
    pub trades_closed: u64,
    /// Cumulative realized P&L
    pub cumulative_pnl: f64,
    /// Maximum drawdown (as fraction, e.g. 0.15 = 15%)
    pub max_drawdown: f64,
    /// Peak equity reached
    pub peak_equity: f64,
    /// Current drawdown
    pub current_drawdown: f64,
    /// Sum of all winning trade P&Ls
    pub gross_profit: f64,
    /// Sum of all losing trade P&Ls (negative)
    pub gross_loss: f64,
    /// P&L time series for Sharpe calculation
    pnl_series: Vec<f64>,
    /// Equity time series for drawdown tracking
    equity_series: Vec<f64>,
}

impl Metrics {
    pub fn new(initial_balance: f64) -> Self {
        Self {
            initial_balance,
            ticks_processed: 0,
            trades_opened: 0,
            trades_closed: 0,
            cumulative_pnl: 0.0,
            max_drawdown: 0.0,
            peak_equity: initial_balance,
            current_drawdown: 0.0,
            gross_profit: 0.0,
            gross_loss: 0.0,
            pnl_series: Vec::new(),
            equity_series: vec![initial_balance],
        }
    }

    /// Record a tick being processed.
    pub fn record_tick(&mut self) {
        self.ticks_processed += 1;
    }

    /// Record a trade being opened.
    pub fn record_trade_opened(&mut self) {
        self.trades_opened += 1;
    }

    /// Record a trade being closed with its P&L.
    pub fn record_trade_closed(&mut self, pnl: f64) {
        self.trades_closed += 1;
        self.cumulative_pnl += pnl;
        self.pnl_series.push(pnl);

        if pnl > 0.0 {
            self.gross_profit += pnl;
        } else {
            self.gross_loss += pnl;
        }

        // Update equity
        let new_equity = self.initial_balance + self.cumulative_pnl;
        self.equity_series.push(new_equity);

        // Update drawdown
        if new_equity > self.peak_equity {
            self.peak_equity = new_equity;
        }
        self.current_drawdown = if self.peak_equity > 0.0 {
            (self.peak_equity - new_equity) / self.peak_equity
        } else {
            0.0
        };
        if self.current_drawdown > self.max_drawdown {
            self.max_drawdown = self.current_drawdown;
        }
    }

    /// Calculate annualized Sharpe ratio (assuming daily P&L).
    /// Simplified: uses trade-level returns.
    pub fn sharpe_ratio(&self) -> f64 {
        if self.pnl_series.is_empty() || self.initial_balance <= 0.0 {
            return 0.0;
        }
        let returns: Vec<f64> = self.pnl_series.iter()
            .map(|pnl| pnl / self.initial_balance)
            .collect();

        let n = returns.len() as f64;
        let mean = returns.iter().sum::<f64>() / n;
        let variance = returns.iter()
            .map(|r| (r - mean).powi(2))
            .sum::<f64>() / n;
        let std_dev = variance.sqrt();

        if std_dev == 0.0 {
            return 0.0;
        }

        // Annualize (assuming 252 trading days, approx scaling)
        mean / std_dev * (252.0_f64).sqrt()
    }

    /// Calculate profit factor (gross profit / |gross loss|).
    pub fn profit_factor(&self) -> f64 {
        if self.gross_loss == 0.0 {
            if self.gross_profit > 0.0 { f64::INFINITY } else { 0.0 }
        } else {
            self.gross_profit / self.gross_loss.abs()
        }
    }

    /// Win rate.
    pub fn win_rate(&self) -> f64 {
        if self.trades_closed == 0 {
            return 0.0;
        }
        let wins = self.pnl_series.iter().filter(|&&p| p > 0.0).count();
        wins as f64 / self.trades_closed as f64
    }

    /// Average win size.
    pub fn avg_win(&self) -> f64 {
        let wins: Vec<f64> = self.pnl_series.iter().filter(|&&p| p > 0.0).copied().collect();
        if wins.is_empty() { 0.0 } else { wins.iter().sum::<f64>() / wins.len() as f64 }
    }

    /// Average loss size.
    pub fn avg_loss(&self) -> f64 {
        let losses: Vec<f64> = self.pnl_series.iter().filter(|&&p| p < 0.0).copied().collect();
        if losses.is_empty() { 0.0 } else { losses.iter().sum::<f64>() / losses.len() as f64 }
    }
}

/// Python-facing metrics.
#[cfg(feature = "python-bindings")]
#[pyo3::pyclass(name = "Metrics")]
pub struct PyMetrics {
    #[pyo3(get)]
    pub ticks_processed: u64,
    #[pyo3(get)]
    pub trades_closed: u64,
    #[pyo3(get)]
    pub cumulative_pnl: f64,
    #[pyo3(get)]
    pub max_drawdown: f64,
    #[pyo3(get)]
    pub sharpe_ratio: f64,
    #[pyo3(get)]
    pub profit_factor: f64,
    #[pyo3(get)]
    pub win_rate: f64,
}

impl From<&Metrics> for PyMetrics {
    fn from(m: &Metrics) -> Self {
        Self {
            ticks_processed: m.ticks_processed,
            trades_closed: m.trades_closed,
            cumulative_pnl: m.cumulative_pnl,
            max_drawdown: m.max_drawdown,
            sharpe_ratio: m.sharpe_ratio(),
            profit_factor: m.profit_factor(),
            win_rate: m.win_rate(),
        }
    }
}
