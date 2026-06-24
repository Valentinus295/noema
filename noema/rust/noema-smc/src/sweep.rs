//! Liquidity sweep detection.
//!
//! Based on JARVIS `core/smc.py` pattern:
//! Price penetrates prior swing level but closes back on original side
//! within the same candle. Search lookback: 30 bars.

use crate::swing::{Swing, SwingType};
use serde::{Deserialize, Serialize};

/// A liquidity sweep — a false breakout that traps traders.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LiquiditySweep {
    /// Index of the sweep candle
    pub index: usize,
    /// The swing level that was swept
    pub swept_level: f64,
    /// Type of sweep
    pub sweep_type: SweepType,
    /// How far the wick penetrated beyond the level
    pub penetration_pips: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SweepType {
    /// Sweep of swing highs (wick above, close below) — bearish signal
    SweepOfHighs,
    /// Sweep of swing lows (wick below, close above) — bullish signal
    SweepOfLows,
}

/// Detect liquidity sweeps around prior swing levels.
///
/// Searches past `lookback` candles for swing levels.
/// A sweep occurs when:
/// - Sweep of highs: high[i] > swing_high_price AND close[i] < swing_high_price
/// - Sweep of lows: low[i] < swing_low_price AND close[i] > swing_low_price
pub fn detect_sweeps(
    highs: &[f64],
    lows: &[f64],
    closes: &[f64],
    swings: &[Swing],
    lookback: usize,
) -> Vec<LiquiditySweep> {
    let n = highs.len();
    let mut sweeps = Vec::new();

    for i in lookback..n {
        let start = if i >= lookback { i - lookback } else { 0 };

        // Find prior swing highs in the lookback window
        for swing in swings.iter().filter(|s| s.index >= start && s.index < i) {
            match swing.swing_type {
                SwingType::SwingHigh => {
                    // Sweep of highs: wick penetrates above, close back below
                    if highs[i] > swing.price && closes[i] < swing.price {
                        let penetration = (highs[i] - swing.price) * 10000.0; // pips
                        sweeps.push(LiquiditySweep {
                            index: i,
                            swept_level: swing.price,
                            sweep_type: SweepType::SweepOfHighs,
                            penetration_pips: penetration,
                        });
                    }
                }
                SwingType::SwingLow => {
                    // Sweep of lows: wick penetrates below, close back above
                    if lows[i] < swing.price && closes[i] > swing.price {
                        let penetration = (swing.price - lows[i]) * 10000.0; // pips
                        sweeps.push(LiquiditySweep {
                            index: i,
                            swept_level: swing.price,
                            sweep_type: SweepType::SweepOfLows,
                            penetration_pips: penetration,
                        });
                    }
                }
            }
        }
    }

    sweeps
}

/// Python-facing sweep detection.
#[cfg(feature = "python-bindings")]
#[pyo3::pyclass(name = "LiquiditySweep")]
#[derive(Clone)]
pub struct PyLiquiditySweep {
    #[pyo3(get)]
    pub index: usize,
    #[pyo3(get)]
    pub swept_level: f64,
    #[pyo3(get)]
    pub sweep_type: String,
    #[pyo3(get)]
    pub penetration_pips: f64,
}

/// Python function for sweep detection.
#[cfg(feature = "python-bindings")]
#[pyo3::pyfunction]
#[pyo3(signature = (highs, lows, closes, swing_highs, swing_lows, lookback=None))]
pub fn py_detect_sweeps(
    highs: Vec<f64>,
    lows: Vec<f64>,
    closes: Vec<f64>,
    swing_highs: Vec<(usize, f64)>,
    swing_lows: Vec<(usize, f64)>,
    lookback: Option<usize>,
) -> Vec<PyLiquiditySweep> {
    let swings: Vec<Swing> = swing_highs
        .into_iter()
        .map(|(idx, price)| Swing {
            index: idx,
            price,
            swing_type: SwingType::SwingHigh,
        })
        .chain(swing_lows.into_iter().map(|(idx, price)| Swing {
            index: idx,
            price,
            swing_type: SwingType::SwingLow,
        }))
        .collect();

    detect_sweeps(&highs, &lows, &closes, &swings, lookback.unwrap_or(30))
        .into_iter()
        .map(|s| PyLiquiditySweep {
            index: s.index,
            swept_level: s.swept_level,
            sweep_type: match s.sweep_type {
                SweepType::SweepOfHighs => "SweepOfHighs".to_string(),
                SweepType::SweepOfLows => "SweepOfLows".to_string(),
            },
            penetration_pips: s.penetration_pips,
        })
        .collect()
}
