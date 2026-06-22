//! Swing point detection (fractal-style).
//!
//! Based on JARVIS `core/smc.py` pattern:
//! A swing high = price higher than `lookback` candles on each side, unique max.

use serde::{Deserialize, Serialize};

/// A swing point (high or low).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Swing {
    /// Index in the price array
    pub index: usize,
    /// Price level
    pub price: f64,
    /// SwingHigh or SwingLow
    pub swing_type: SwingType,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SwingType {
    SwingHigh,
    SwingLow,
}

/// Detect swing highs from OHLC data.
///
/// A swing high exists at index `i` if `high[i]` is:
/// - Higher than all highs in `[i-lookback .. i-1]`
/// - Higher than all highs in `[i+1 .. i+lookback]`
pub fn detect_swing_highs(highs: &[f64], lookback: usize) -> Vec<Swing> {
    let n = highs.len();
    if n < 2 * lookback + 1 {
        return Vec::new();
    }

    let mut swings = Vec::new();

    for i in lookback..(n - lookback) {
        let current = highs[i];
        let left_max = highs[i - lookback..i].iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let right_max = highs[i + 1..=i + lookback].iter().cloned().fold(f64::NEG_INFINITY, f64::max);

        if current > left_max && current >= right_max {
            // Check uniqueness — no equal high in the window
            let is_unique = highs[i - lookback..=i + lookback]
                .iter()
                .filter(|&&h| (h - current).abs() < 1e-8)
                .count() == 1;

            if is_unique {
                swings.push(Swing {
                    index: i,
                    price: current,
                    swing_type: SwingType::SwingHigh,
                });
            }
        }
    }

    swings
}

/// Detect swing lows from OHLC data.
pub fn detect_swing_lows(lows: &[f64], lookback: usize) -> Vec<Swing> {
    let n = lows.len();
    if n < 2 * lookback + 1 {
        return Vec::new();
    }

    let mut swings = Vec::new();

    for i in lookback..(n - lookback) {
        let current = lows[i];
        let left_min = lows[i - lookback..i].iter().cloned().fold(f64::INFINITY, f64::min);
        let right_min = lows[i + 1..=i + lookback].iter().cloned().fold(f64::INFINITY, f64::min);

        if current < left_min && current <= right_min {
            let is_unique = lows[i - lookback..=i + lookback]
                .iter()
                .filter(|&&l| (l - current).abs() < 1e-8)
                .count() == 1;

            if is_unique {
                swings.push(Swing {
                    index: i,
                    price: current,
                    swing_type: SwingType::SwingLow,
                });
            }
        }
    }

    swings
}

/// Detect all swings (highs + lows), sorted by index.
pub fn detect_swings(highs: &[f64], lows: &[f64], lookback: usize) -> Vec<Swing> {
    let mut swings = detect_swing_highs(highs, lookback);
    swings.extend(detect_swing_lows(lows, lookback));
    swings.sort_by_key(|s| s.index);
    swings
}

/// Python-facing swing detector.
#[cfg(feature = "python-bindings")]
#[pyo3::pyclass(name = "SwingDetector")]
pub struct PySwingDetector {
    lookback: usize,
}

#[cfg(feature = "python-bindings")]
#[pyo3::pymethods]
impl PySwingDetector {
    #[new]
    fn new(lookback: Option<usize>) -> Self {
        Self { lookback: lookback.unwrap_or(3) }
    }

    fn detect_highs(&self, highs: Vec<f64>) -> Vec<(usize, f64)> {
        detect_swing_highs(&highs, self.lookback)
            .into_iter()
            .map(|s| (s.index, s.price))
            .collect()
    }

    fn detect_lows(&self, lows: Vec<f64>) -> Vec<(usize, f64)> {
        detect_swing_lows(&lows, self.lookback)
            .into_iter()
            .map(|s| (s.index, s.price))
            .collect()
    }
}
