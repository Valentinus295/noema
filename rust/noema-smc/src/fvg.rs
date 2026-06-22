//! Fair Value Gap (FVG) detection.
//!
//! Based on JARVIS `core/smc.py` pattern:
//! 3-candle imbalance. Bullish: low[i+1] > high[i-1]. Bearish: high[i+1] < low[i-1].
//! Tracks mitigation (price revisits gap).

use serde::{Deserialize, Serialize};

/// A Fair Value Gap — an imbalance between 3 candles.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FVG {
    /// Index of the FVG (middle candle)
    pub index: usize,
    /// FVG type: Bullish or Bearish
    pub fvg_type: FVGType,
    /// Top of the gap zone
    pub top: f64,
    /// Bottom of the gap zone
    pub bottom: f64,
    /// Whether the FVG has been mitigated (price revisited)
    pub mitigated: bool,
    /// Price that caused mitigation
    pub mitigation_price: Option<f64>,
    /// Index where mitigation occurred
    pub mitigated_at: Option<usize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FVGType {
    Bullish,
    Bearish,
}

/// Detect FVGs from OHLC data.
///
/// Bullsih FVG: low[i+1] > high[i-1] (gap up — price left a void)
/// Bearish FVG: high[i+1] < low[i-1] (gap down — price left a void)
pub fn detect_fvgs(
    highs: &[f64],
    lows: &[f64],
) -> Vec<FVG> {
    let n = highs.len();
    if n < 3 {
        return Vec::new();
    }

    let mut fvgs = Vec::new();

    for i in 1..(n - 1) {
        // Check for bullish FVG
        if lows[i + 1] > highs[i - 1] {
            fvgs.push(FVG {
                index: i,
                fvg_type: FVGType::Bullish,
                top: lows[i + 1],
                bottom: highs[i - 1],
                mitigated: false,
                mitigation_price: None,
                mitigated_at: None,
            });
        }
        // Check for bearish FVG
        else if highs[i + 1] < lows[i - 1] {
            fvgs.push(FVG {
                index: i,
                fvg_type: FVGType::Bearish,
                top: lows[i - 1],
                bottom: highs[i + 1],
                mitigated: false,
                mitigation_price: None,
                mitigated_at: None,
            });
        }
    }

    // Mark mitigation: when price revisits the gap zone
    for fvg in &mut fvgs {
        for j in (fvg.index + 1)..n {
            let price_touches = match fvg.fvg_type {
                FVGType::Bullish => lows[j] <= fvg.top,
                FVGType::Bearish => highs[j] >= fvg.bottom,
            };

            if price_touches {
                fvg.mitigated = true;
                fvg.mitigation_price = Some(match fvg.fvg_type {
                    FVGType::Bullish => lows[j],
                    FVGType::Bearish => highs[j],
                });
                fvg.mitigated_at = Some(j);
                break;
            }
        }
    }

    fvgs
}

/// Filter to unmitigated FVGs only.
pub fn unmitigated_fvgs(fvgs: &[FVG]) -> Vec<&FVG> {
    fvgs.iter().filter(|f| !f.mitigated).collect()
}

/// Find the nearest unmitigated FVG to a given price.
pub fn nearest_unmitigated_fvg(
    fvgs: &[FVG],
    price: f64,
    fvg_type: Option<FVGType>,
) -> Option<&FVG> {
    unmitigated_fvgs(fvgs)
        .into_iter()
        .filter(|f| fvg_type.map_or(true, |t| t == f.fvg_type))
        .min_by(|a, b| {
            let dist_a = match a.fvg_type {
                FVGType::Bullish => (a.bottom - price).abs(),
                FVGType::Bearish => (a.top - price).abs(),
            };
            let dist_b = match b.fvg_type {
                FVGType::Bullish => (b.bottom - price).abs(),
                FVGType::Bearish => (b.top - price).abs(),
            };
            dist_a.partial_cmp(&dist_b).unwrap_or(std::cmp::Ordering::Equal)
        })
}

/// Python-facing FVG detection.
#[cfg(feature = "python-bindings")]
#[pyo3::pyclass(name = "FVG")]
#[derive(Clone)]
pub struct PyFVG {
    #[pyo3(get)]
    pub index: usize,
    #[pyo3(get)]
    pub fvg_type: String,
    #[pyo3(get)]
    pub top: f64,
    #[pyo3(get)]
    pub bottom: f64,
    #[pyo3(get)]
    pub mitigated: bool,
}

impl From<&FVG> for PyFVG {
    fn from(f: &FVG) -> Self {
        Self {
            index: f.index,
            fvg_type: match f.fvg_type {
                FVGType::Bullish => "Bullish".to_string(),
                FVGType::Bearish => "Bearish".to_string(),
            },
            top: f.top,
            bottom: f.bottom,
            mitigated: f.mitigated,
        }
    }
}

/// Python function for FVG detection.
#[cfg(feature = "python-bindings")]
#[pyo3::pyfunction]
pub fn py_detect_fvgs(highs: Vec<f64>, lows: Vec<f64>) -> Vec<PyFVG> {
    detect_fvgs(&highs, &lows)
        .into_iter()
        .map(|f| PyFVG::from(&f))
        .collect()
}
