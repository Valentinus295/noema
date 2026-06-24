//! Order Block detection.
//!
//! Based on JARVIS `core/smc.py` pattern:
//! Last opposing candle before ≥2 consecutive impulsive candles.
//! OB is valid until price closes through it (not wicks).

use serde::{Deserialize, Serialize};

/// An Order Block (OB) — a supply or demand zone.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderBlock {
    /// Index of the OB's candle
    pub index: usize,
    /// OB type: Bullish = Demand, Bearish = Supply
    pub ob_type: OBType,
    /// Top of the OB zone (high of the candle)
    pub high: f64,
    /// Bottom of the OB zone (low of the candle)
    pub low: f64,
    /// Midpoint for entry reference
    pub mid: f64,
    /// Whether the OB has been mitigated (price closed through it)
    pub mitigated: bool,
    /// Index where mitigation occurred (if any)
    pub mitigated_at: Option<usize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OBType {
    /// Bullish Order Block = Demand zone (last bearish candle before bullish impulse)
    Bullish,
    /// Bearish Order Block = Supply zone (last bullish candle before bearish impulse)
    Bearish,
}

/// Detect order blocks from OHLC data.
///
/// A bullish OB (demand zone) = the last bearish candle before ≥2 consecutive bullish candles.
/// A bearish OB (supply zone) = the last bullish candle before ≥2 consecutive bearish candles.
pub fn detect_order_blocks(
    opens: &[f64],
    highs: &[f64],
    lows: &[f64],
    closes: &[f64],
    min_impulse: usize,
) -> Vec<OrderBlock> {
    let n = opens.len();
    if n < min_impulse + 1 {
        return Vec::new();
    }

    let mut obs = Vec::new();

    // Classify each candle: 1 = bullish, -1 = bearish, 0 = doji/neutral
    let dir: Vec<i8> = (0..n)
        .map(|i| {
            if closes[i] > opens[i] { 1 }
            else if closes[i] < opens[i] { -1 }
            else { 0 }
        })
        .collect();

    for i in 1..=(n - min_impulse) {
        // Check if there's an impulse starting at i
        let impulse_dir = dir[i];
        if impulse_dir == 0 {
            continue;
        }

        // Count consecutive candles in same direction
        let mut impulse_len = 1;
        for j in (i + 1)..n {
            if dir[j] == impulse_dir {
                impulse_len += 1;
            } else {
                break;
            }
        }

        if impulse_len >= min_impulse {
            // The OB is the candle before the impulse (opposite direction)
            if i > 0 && dir[i - 1] == -impulse_dir {
                let ob_type = if impulse_dir == 1 {
                    // Bullish impulse → OB is the preceding bearish candle (demand zone)
                    OBType::Bullish
                } else {
                    // Bearish impulse → OB is the preceding bullish candle (supply zone)
                    OBType::Bearish
                };

                obs.push(OrderBlock {
                    index: i - 1,
                    ob_type,
                    high: highs[i - 1],
                    low: lows[i - 1],
                    mid: (highs[i - 1] + lows[i - 1]) / 2.0,
                    mitigated: false,
                    mitigated_at: None,
                });
            }
        }
    }

    // Mark OBs as mitigated when price closes through them
    for ob in &mut obs {
        for j in (ob.index + 1)..n {
            match ob.ob_type {
                OBType::Bullish => {
                    // Demand zone mitigated when price closes below its low
                    if closes[j] < ob.low {
                        ob.mitigated = true;
                        ob.mitigated_at = Some(j);
                        break;
                    }
                }
                OBType::Bearish => {
                    // Supply zone mitigated when price closes above its high
                    if closes[j] > ob.high {
                        ob.mitigated = true;
                        ob.mitigated_at = Some(j);
                        break;
                    }
                }
            }
        }
    }

    obs
}

/// Filter to unmitigated order blocks only.
pub fn unmitigated_obs(obs: &[OrderBlock]) -> Vec<&OrderBlock> {
    obs.iter().filter(|ob| !ob.mitigated).collect()
}

/// Python-facing order block detection.
#[cfg(feature = "python-bindings")]
#[pyo3::pyclass(name = "OrderBlock")]
#[derive(Clone)]
pub struct PyOrderBlock {
    #[pyo3(get)]
    pub index: usize,
    #[pyo3(get)]
    pub ob_type: String,
    #[pyo3(get)]
    pub high: f64,
    #[pyo3(get)]
    pub low: f64,
    #[pyo3(get)]
    pub mitigated: bool,
}

impl From<&OrderBlock> for PyOrderBlock {
    fn from(ob: &OrderBlock) -> Self {
        Self {
            index: ob.index,
            ob_type: match ob.ob_type {
                OBType::Bullish => "Bullish".to_string(),
                OBType::Bearish => "Bearish".to_string(),
            },
            high: ob.high,
            low: ob.low,
            mitigated: ob.mitigated,
        }
    }
}

/// Python function for OB detection.
#[cfg(feature = "python-bindings")]
#[pyo3::pyfunction]
#[pyo3(signature = (opens, highs, lows, closes, min_impulse=None))]
pub fn py_detect_obs(
    opens: Vec<f64>,
    highs: Vec<f64>,
    lows: Vec<f64>,
    closes: Vec<f64>,
    min_impulse: Option<usize>,
) -> Vec<PyOrderBlock> {
    detect_order_blocks(&opens, &highs, &lows, &closes, min_impulse.unwrap_or(2))
        .into_iter()
        .map(|ob| PyOrderBlock::from(&ob))
        .collect()
}
