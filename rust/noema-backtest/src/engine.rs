//! Event loop and backtest engine.
//!
//! Drives the simulation: processes ticks → generates signals → matches orders → tracks P&L.

use crate::events::{Event, EventQueue};
use crate::order::{Order, OrderSide, OrderStatus, OrderType};
use crate::position::{Position, PositionSide};
use crate::metrics::Metrics;
use noema_data::tick::Tick;
use chrono::{DateTime, Utc};
use std::collections::HashMap;

/// Core backtesting engine.
pub struct BacktestEngine {
    /// Initial account balance
    initial_balance: f64,
    /// Current balance (including realized P&L)
    balance: f64,
    /// Current equity (balance + unrealized P&L)
    equity: f64,
    /// Open positions
    positions: Vec<Position>,
    /// Pending orders (limit/stop)
    pending_orders: Vec<Order>,
    /// Order history
    order_history: Vec<Order>,
    /// Position history (closed)
    closed_positions: Vec<Position>,
    /// Event queue
    events: EventQueue,
    /// Current tick
    current_tick: Option<Tick>,
    /// Spread in pips
    spread: f64,
    /// Commission per lot
    commission_per_lot: f64,
    /// Contract size (standard = 100000)
    contract_size: f64,
    /// Metrics collector
    metrics: Metrics,
}

/// Configuration for the backtest engine.
pub struct BacktestConfig {
    pub initial_balance: f64,
    pub spread: f64,
    pub commission_per_lot: f64,
    pub contract_size: f64,
}

impl Default for BacktestConfig {
    fn default() -> Self {
        Self {
            initial_balance: 10_000.0,
            spread: 1.0, // 1 pip for majors
            commission_per_lot: 3.5,
            contract_size: 100_000.0,
        }
    }
}

impl BacktestEngine {
    pub fn new(config: BacktestConfig) -> Self {
        Self {
            initial_balance: config.initial_balance,
            balance: config.initial_balance,
            equity: config.initial_balance,
            positions: Vec::new(),
            pending_orders: Vec::new(),
            order_history: Vec::new(),
            closed_positions: Vec::new(),
            events: EventQueue::new(),
            current_tick: None,
            spread: config.spread,
            commission_per_lot: config.commission_per_lot,
            contract_size: config.contract_size,
            metrics: Metrics::new(config.initial_balance),
        }
    }

    /// Process a new tick.
    pub fn on_tick(&mut self, tick: &Tick) {
        self.current_tick = Some(tick.clone());

        // Check pending orders for activation
        self.check_pending_orders(tick);

        // Update unrealized P&L
        self.update_equity(tick);

        self.metrics.record_tick();
    }

    /// Place a market order.
    pub fn place_market_order(&mut self, symbol: &str, side: OrderSide, volume: f64) -> Option<usize> {
        let tick = self.current_tick.as_ref()?;
        let price = match side {
            OrderSide::Buy => tick.ask,
            OrderSide::Sell => tick.bid,
        };

        self.open_position(symbol, side, volume, price)
    }

    /// Place a pending order (limit/stop).
    pub fn place_pending_order(
        &mut self,
        symbol: &str,
        side: OrderSide,
        order_type: OrderType,
        volume: f64,
        price: f64,
    ) -> usize {
        let id = self.pending_orders.len();
        let order = Order {
            id,
            symbol: symbol.to_string(),
            side,
            order_type,
            volume,
            price,
            status: OrderStatus::Pending,
            created_at: self.current_tick.as_ref().map(|t| t.timestamp).unwrap_or_else(Utc::now),
            filled_at: None,
            filled_price: None,
        };
        self.pending_orders.push(order);
        id
    }

    /// Check if pending orders should be triggered by current tick.
    fn check_pending_orders(&mut self, tick: &Tick) {
        let mid = tick.mid();
        let mut triggered = Vec::new();

        for (i, order) in self.pending_orders.iter().enumerate() {
            let should_trigger = match order.order_type {
                OrderType::BuyLimit => tick.ask <= order.price,
                OrderType::SellLimit => tick.bid >= order.price,
                OrderType::BuyStop => tick.ask >= order.price,
                OrderType::SellStop => tick.bid <= order.price,
                _ => false,
            };

            if should_trigger {
                triggered.push(i);
            }
        }

        // Process triggered orders (reverse order to avoid index issues)
        for &i in triggered.iter().rev() {
            let order = self.pending_orders.remove(i);
            self.open_position(&order.symbol, order.side, order.volume, order.price);
        }
    }

    /// Open a new position.
    fn open_position(
        &mut self,
        symbol: &str,
        side: OrderSide,
        volume: f64,
        entry_price: f64,
    ) -> Option<usize> {
        // Apply spread cost to entry
        let cost = volume * self.spread * (self.contract_size / 10_000.0); // pip value approx
        let commission = volume * self.commission_per_lot;
        self.balance -= cost + commission;

        let pos_side = match side {
            OrderSide::Buy => PositionSide::Long,
            OrderSide::Sell => PositionSide::Short,
        };

        let id = self.positions.len();
        let position = Position {
            id,
            symbol: symbol.to_string(),
            side: pos_side,
            volume,
            entry_price,
            entry_time: self.current_tick.as_ref().map(|t| t.timestamp).unwrap_or_else(Utc::now),
            exit_price: None,
            exit_time: None,
            realized_pnl: None,
            stop_loss: None,
            take_profit: None,
        };

        self.positions.push(position);
        self.metrics.record_trade_opened();

        Some(id)
    }

    /// Close a position.
    pub fn close_position(&mut self, position_id: usize) -> Option<f64> {
        let tick = self.current_tick.as_ref()?;
        let position = self.positions.get_mut(position_id)?;

        let exit_price = match position.side {
            PositionSide::Long => tick.bid,
            PositionSide::Short => tick.ask,
        };

        let pnl_points = match position.side {
            PositionSide::Long => exit_price - position.entry_price,
            PositionSide::Short => position.entry_price - exit_price,
        };

        let pnl = pnl_points * position.volume * self.contract_size;
        let commission = position.volume * self.commission_per_lot;
        let net_pnl = pnl - commission;

        position.exit_price = Some(exit_price);
        position.exit_time = Some(tick.timestamp);
        position.realized_pnl = Some(net_pnl);

        // Transfer to closed positions
        let closed = self.positions.remove(position_id);
        self.closed_positions.push(closed);

        self.balance += net_pnl;
        self.metrics.record_trade_closed(net_pnl);

        Some(net_pnl)
    }

    /// Update equity based on current prices.
    fn update_equity(&mut self, tick: &Tick) {
        let mut unrealized = 0.0;
        let mid = tick.mid();

        for position in &self.positions {
            let pnl_points = match position.side {
                PositionSide::Long => mid - position.entry_price,
                PositionSide::Short => position.entry_price - mid,
            };
            unrealized += pnl_points * position.volume * self.contract_size;
        }

        self.equity = self.balance + unrealized;
    }

    /// Get current metrics.
    pub fn get_metrics(&self) -> &Metrics {
        &self.metrics
    }

    /// Get final report.
    pub fn report(&self) -> BacktestReport {
        let total_return = (self.balance - self.initial_balance) / self.initial_balance;
        let total_trades = self.closed_positions.len();
        let winning_trades = self.closed_positions.iter()
            .filter(|p| p.realized_pnl.unwrap_or(0.0) > 0.0)
            .count();

        BacktestReport {
            initial_balance: self.initial_balance,
            final_balance: self.balance,
            total_return,
            total_trades,
            winning_trades,
            win_rate: if total_trades > 0 {
                winning_trades as f64 / total_trades as f64
            } else {
                0.0
            },
            max_drawdown: self.metrics.max_drawdown,
            sharpe_ratio: self.metrics.sharpe_ratio(),
            profit_factor: self.metrics.profit_factor(),
        }
    }
}

/// Final backtest report.
#[derive(Debug, Clone)]
pub struct BacktestReport {
    pub initial_balance: f64,
    pub final_balance: f64,
    pub total_return: f64,
    pub total_trades: usize,
    pub winning_trades: usize,
    pub win_rate: f64,
    pub max_drawdown: f64,
    pub sharpe_ratio: f64,
    pub profit_factor: f64,
}

/// Python-facing backtest engine.
#[cfg(feature = "python-bindings")]
#[pyo3::pyclass(name = "BacktestEngine")]
pub struct PyBacktestEngine {
    inner: BacktestEngine,
}

#[cfg(feature = "python-bindings")]
#[pyo3::pymethods]
impl PyBacktestEngine {
    #[new]
    fn new(
        initial_balance: Option<f64>,
        spread: Option<f64>,
        commission: Option<f64>,
        contract_size: Option<f64>,
    ) -> Self {
        let config = BacktestConfig {
            initial_balance: initial_balance.unwrap_or(10_000.0),
            spread: spread.unwrap_or(1.0),
            commission_per_lot: commission.unwrap_or(3.5),
            contract_size: contract_size.unwrap_or(100_000.0),
        };
        Self { inner: BacktestEngine::new(config) }
    }

    fn on_tick(&mut self, timestamp: i64, bid: f64, ask: f64) {
        use chrono::TimeZone;
        let ts = Utc.timestamp_nanos(timestamp);
        let tick = Tick::new(ts, bid, ask);
        self.inner.on_tick(&tick);
    }

    fn report(&self) -> pyo3::PyResult<HashMap<String, pyo3::PyObject>> {
        // Returns report as a Python dict
        let r = self.inner.report();
        let mut map = HashMap::new();
        // Simplified — in production, return proper dict
        Ok(map)
    }
}
