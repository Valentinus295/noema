//! noema-backtest: Backtesting engine core
//!
//! Event-driven backtesting engine with order matching, position tracking,
//! P&L calculation, and metrics.
//!
//! Architecture inspired by pyeventbt (event-driven MT5 backtesting)
//! and QuantDinger's strategy position sync patterns.

pub mod engine;
pub mod events;
pub mod order;
pub mod position;
pub mod metrics;

use pyo3::prelude::*;

#[cfg(feature = "python-bindings")]
#[pymodule]
fn noema_backtest(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<engine::PyBacktestEngine>()?;
    m.add_class::<metrics::PyMetrics>()?;
    Ok(())
}
