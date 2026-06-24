//! noema-data: Market data ingestion and processing
//!
//! Core crate for tick parsing, OHLCV aggregation, and data pipeline operations.
//! Provides both pure Rust and Python (via PyO3) interfaces.

pub mod aggregation;
pub mod ingestion;
pub mod tick;

use pyo3::prelude::*;

/// Python module entry point for noema_data
#[cfg(feature = "python-bindings")]
#[pymodule]
fn noema_data(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<tick::PyTick>()?;
    m.add_class::<aggregation::PyOhlcvAggregator>()?;
    m.add_function(wrap_pyfunction!(ingestion::py_load_csv_ticks, m)?)?;
    Ok(())
}
