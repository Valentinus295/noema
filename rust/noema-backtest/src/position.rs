//! Position tracking.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Position side (long/short).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PositionSide {
    Long,
    Short,
}

/// A trading position.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Position {
    pub id: usize,
    pub symbol: String,
    pub side: PositionSide,
    pub volume: f64,
    pub entry_price: f64,
    pub entry_time: DateTime<Utc>,
    pub exit_price: Option<f64>,
    pub exit_time: Option<DateTime<Utc>>,
    pub realized_pnl: Option<f64>,
    pub stop_loss: Option<f64>,
    pub take_profit: Option<f64>,
}

impl Position {
    /// Check if this position is still open.
    pub fn is_open(&self) -> bool {
        self.exit_price.is_none()
    }

    /// Current unrealized P&L given mid price.
    pub fn unrealized_pnl(&self, mid_price: f64, contract_size: f64) -> f64 {
        let pnl_points = match self.side {
            PositionSide::Long => mid_price - self.entry_price,
            PositionSide::Short => self.entry_price - mid_price,
        };
        pnl_points * self.volume * contract_size
    }
}
