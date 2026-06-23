//! OHLCV aggregation from tick data.
//!
//! Efficiently aggregates tick streams into candlestick bars at
//! configurable timeframes (M1, M5, M15, H1, H4, D1, etc.).

use crate::tick::Tick;
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};

/// A candlestick (OHLCV) bar.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OhlcvBar {
    pub timestamp: DateTime<Utc>,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
    pub tick_count: u32,
}

/// Timeframe for OHLCV aggregation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Timeframe {
    M1,
    M5,
    M15,
    M30,
    H1,
    H4,
    D1,
    W1,
    MN1,
}

impl Timeframe {
    /// Duration of each bar.
    pub fn duration(&self) -> Duration {
        match self {
            Self::M1 => Duration::minutes(1),
            Self::M5 => Duration::minutes(5),
            Self::M15 => Duration::minutes(15),
            Self::M30 => Duration::minutes(30),
            Self::H1 => Duration::hours(1),
            Self::H4 => Duration::hours(4),
            Self::D1 => Duration::days(1),
            Self::W1 => Duration::weeks(1),
            Self::MN1 => Duration::days(30), // approximate
        }
    }

    /// Align a timestamp to the bar boundary.
    pub fn align(&self, ts: DateTime<Utc>) -> DateTime<Utc> {
        let d = self.duration();
        let nanos = ts.timestamp_nanos_opt().unwrap_or(0);
        let d_nanos = d.num_nanoseconds().unwrap_or(0);
        let aligned = (nanos / d_nanos) * d_nanos;
        DateTime::from_timestamp_nanos(aligned)
    }
}

/// Aggregates ticks into OHLCV bars.
pub struct OhlcvAggregator {
    timeframe: Timeframe,
    current_bar: Option<OhlcvBar>,
}

impl OhlcvAggregator {
    pub fn new(timeframe: Timeframe) -> Self {
        Self {
            timeframe,
            current_bar: None,
        }
    }

    /// Process a tick and return completed bars if any.
    pub fn push(&mut self, tick: &Tick) -> Vec<OhlcvBar> {
        let aligned = self.timeframe.align(tick.timestamp);
        let mid = tick.mid();
        let mut completed = Vec::new();

        match &mut self.current_bar {
            Some(bar) if bar.timestamp == aligned => {
                // Same bar: update high/low/close/volume
                bar.high = bar.high.max(mid);
                bar.low = bar.low.min(mid);
                bar.close = mid;
                bar.volume += tick.volume.unwrap_or(0.0);
                bar.tick_count += 1;
            }
            Some(existing) => {
                // New bar started: finish old, start new
                let finished = existing.clone();
                completed.push(finished);

                self.current_bar = Some(OhlcvBar {
                    timestamp: aligned,
                    open: mid,
                    high: mid,
                    low: mid,
                    close: mid,
                    volume: tick.volume.unwrap_or(0.0),
                    tick_count: 1,
                });
            }
            None => {
                // First bar
                self.current_bar = Some(OhlcvBar {
                    timestamp: aligned,
                    open: mid,
                    high: mid,
                    low: mid,
                    close: mid,
                    volume: tick.volume.unwrap_or(0.0),
                    tick_count: 1,
                });
            }
        }

        completed
    }

    /// Flush the current incomplete bar.
    pub fn flush(&mut self) -> Option<OhlcvBar> {
        self.current_bar.take()
    }
}

/// Python-facing OHLCV aggregator.
#[cfg(feature = "python-bindings")]
#[pyo3::pyclass(name = "OhlcvAggregator")]
#[allow(dead_code)]
pub struct PyOhlcvAggregator {
    inner: OhlcvAggregator,
}

#[cfg(feature = "python-bindings")]
#[pyo3::pymethods]
impl PyOhlcvAggregator {
    #[new]
    fn new(timeframe_str: &str) -> pyo3::PyResult<Self> {
        let tf = match timeframe_str {
            "M1" => Timeframe::M1,
            "M5" => Timeframe::M5,
            "M15" => Timeframe::M15,
            "M30" => Timeframe::M30,
            "H1" => Timeframe::H1,
            "H4" => Timeframe::H4,
            "D1" => Timeframe::D1,
            _ => return Err(pyo3::exceptions::PyValueError::new_err(
                format!("Unknown timeframe: {}", timeframe_str)
            )),
        };
        Ok(Self { inner: OhlcvAggregator::new(tf) })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_timeframe_align() {
        let ts = DateTime::from_timestamp(1700000000, 0).unwrap();
        let aligned = Timeframe::H1.align(ts);
        // Should be aligned to the hour
        assert_eq!(aligned.minute(), 0);
        assert_eq!(aligned.second(), 0);
    }
}
