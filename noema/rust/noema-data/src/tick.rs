//! Tick data structures and parsing.
//!
//! Handles raw tick data from MT5 and other brokers, converting between
//! different formats and providing efficient access patterns.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// A single market tick.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tick {
    /// Timestamp in UTC
    pub timestamp: DateTime<Utc>,
    /// Bid price
    pub bid: f64,
    /// Ask price
    pub ask: f64,
    /// Trade volume (if available)
    pub volume: Option<f64>,
    /// Spread in pips
    pub spread: Option<f64>,
}

impl Tick {
    /// Create a new tick.
    pub fn new(timestamp: DateTime<Utc>, bid: f64, ask: f64) -> Self {
        let spread = Some((ask - bid) * 10000.0); // FX spread in pips (approx)
        Self {
            timestamp,
            bid,
            ask,
            volume: None,
            spread,
        }
    }

    /// Mid price (bid+ask)/2
    pub fn mid(&self) -> f64 {
        (self.bid + self.ask) / 2.0
    }

    /// Spread in raw points
    pub fn raw_spread(&self) -> f64 {
        self.ask - self.bid
    }
}

/// Python-facing Tick type.
#[cfg(feature = "python-bindings")]
#[pyo3::pyclass(name = "Tick")]
#[derive(Debug, Clone)]
pub struct PyTick {
    #[pyo3(get)]
    pub timestamp: i64, // nanosecond epoch
    #[pyo3(get)]
    pub bid: f64,
    #[pyo3(get)]
    pub ask: f64,
    #[pyo3(get)]
    pub volume: Option<f64>,
}

#[cfg(feature = "python-bindings")]
#[pyo3::pymethods]
impl PyTick {
    #[new]
    fn new(timestamp: i64, bid: f64, ask: f64) -> Self {
        Self { timestamp, bid, ask, volume: None }
    }

    fn mid(&self) -> f64 {
        (self.bid + self.ask) / 2.0
    }
}
