//! Market structure detection (BOS/CHoCH).
//!
//! Based on JARVIS `core/smc.py` pattern:
//! Walk-forward that tracks last swing high/low.
//! - Close above last SH + prior trend bearish = CHoCH (bullish reversal)
//! - Close above last SH + already bullish = BOS (continuation)
//! - Close below last SL + prior trend bullish = CHoCH (bearish reversal)
//! - Close below last SL + already bearish = BOS (continuation)

use serde::{Deserialize, Serialize};

/// A market structure event.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StructureEvent {
    /// Index where the event occurred
    pub index: usize,
    /// BOS (Break of Structure) or CHoCH (Change of Character)
    pub event_type: StructureEventType,
    /// Bullish or Bearish
    pub direction: Direction,
    /// Price level that was broken
    pub broken_level: f64,
    /// Price that caused the break
    pub break_price: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum StructureEventType {
    BOS,   // Break of Structure — trend continuation
    CHoCH, // Change of Character — trend reversal
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Direction {
    Bullish,
    Bearish,
}

/// Current market trend state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Trend {
    Bullish,
    Bearish,
    Neutral,
}

/// Detect market structure events from OHLC and swing data.
///
/// Uses close prices to determine breaks of swing levels.
pub fn detect_structure(
    closes: &[f64],
    highs: &[f64],
    lows: &[f64],
    swing_highs: &[(usize, f64)],
    swing_lows: &[(usize, f64)],
) -> Vec<StructureEvent> {
    let n = closes.len();
    let mut events = Vec::new();
    let mut trend = Trend::Neutral;

    // Track latest unbroken swing levels
    let mut last_sh: Option<(usize, f64)> = None;
    let mut last_sl: Option<(usize, f64)> = None;
    let mut sh_idx = 0usize;
    let mut sl_idx = 0usize;

    for i in 1..n {
        // Update last swing high
        while sh_idx < swing_highs.len() && swing_highs[sh_idx].0 <= i {
            last_sh = Some(swing_highs[sh_idx]);
            sh_idx += 1;
        }

        // Update last swing low
        while sl_idx < swing_lows.len() && swing_lows[sl_idx].0 <= i {
            last_sl = Some(swing_lows[sl_idx]);
            sl_idx += 1;
        }

        // Check for bullish breaks (close above last swing high)
        if let Some((_sh_i, sh_price)) = last_sh {
            if closes[i] > sh_price {
                match trend {
                    Trend::Bearish | Trend::Neutral => {
                        events.push(StructureEvent {
                            index: i,
                            event_type: StructureEventType::CHoCH,
                            direction: Direction::Bullish,
                            broken_level: sh_price,
                            break_price: closes[i],
                        });
                        trend = Trend::Bullish;
                    }
                    Trend::Bullish => {
                        events.push(StructureEvent {
                            index: i,
                            event_type: StructureEventType::BOS,
                            direction: Direction::Bullish,
                            broken_level: sh_price,
                            break_price: closes[i],
                        });
                    }
                }
            }
        }

        // Check for bearish breaks (close below last swing low)
        if let Some((_sl_i, sl_price)) = last_sl {
            if closes[i] < sl_price {
                match trend {
                    Trend::Bullish | Trend::Neutral => {
                        events.push(StructureEvent {
                            index: i,
                            event_type: StructureEventType::CHoCH,
                            direction: Direction::Bearish,
                            broken_level: sl_price,
                            break_price: closes[i],
                        });
                        trend = Trend::Bearish;
                    }
                    Trend::Bearish => {
                        events.push(StructureEvent {
                            index: i,
                            event_type: StructureEventType::BOS,
                            direction: Direction::Bearish,
                            broken_level: sl_price,
                            break_price: closes[i],
                        });
                    }
                }
            }
        }
    }

    events
}

/// Python-facing structure detection.
#[cfg(feature = "python-bindings")]
#[pyo3::pyclass(name = "MarketStructure")]
pub struct PyMarketStructure {
    events: Vec<StructureEvent>,
}

#[cfg(feature = "python-bindings")]
#[pyo3::pymethods]
impl PyMarketStructure {
    #[new]
    fn new() -> Self {
        Self { events: Vec::new() }
    }

    fn detect(
        &mut self,
        closes: Vec<f64>,
        highs: Vec<f64>,
        lows: Vec<f64>,
        swing_highs: Vec<(usize, f64)>,
        swing_lows: Vec<(usize, f64)>,
    ) {
        self.events = detect_structure(&closes, &highs, &lows, &swing_highs, &swing_lows);
    }

    fn last_event(&self) -> Option<(usize, String, String, f64)> {
        self.events.last().map(|e| {
            let event_type = match e.event_type {
                StructureEventType::BOS => "BOS".to_string(),
                StructureEventType::CHoCH => "CHoCH".to_string(),
            };
            let direction = match e.direction {
                Direction::Bullish => "Bullish".to_string(),
                Direction::Bearish => "Bearish".to_string(),
            };
            (e.index, event_type, direction, e.broken_level)
        })
    }
}

/// Standalone Python function for structure detection.
#[cfg(feature = "python-bindings")]
#[pyo3::pyfunction]
pub fn py_detect_structure(
    closes: Vec<f64>,
    highs: Vec<f64>,
    lows: Vec<f64>,
    swing_highs: Vec<(usize, f64)>,
    swing_lows: Vec<(usize, f64)>,
) -> Vec<(usize, String, String, f64)> {
    detect_structure(&closes, &highs, &lows, &swing_highs, &swing_lows)
        .into_iter()
        .map(|e| {
            let event_type = match e.event_type {
                StructureEventType::BOS => "BOS".to_string(),
                StructureEventType::CHoCH => "CHoCH".to_string(),
            };
            let direction = match e.direction {
                Direction::Bullish => "Bullish".to_string(),
                Direction::Bearish => "Bearish".to_string(),
            };
            (e.index, event_type, direction, e.broken_level)
        })
        .collect()
}
