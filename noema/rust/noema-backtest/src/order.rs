//! Order types and status enums.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Order side (buy/sell).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderSide {
    Buy,
    Sell,
}

/// Order type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderType {
    Market,
    BuyLimit,
    SellLimit,
    BuyStop,
    SellStop,
}

/// Order status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderStatus {
    Pending,
    Filled,
    Cancelled,
    Expired,
    Rejected,
}

/// An order in the system.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub id: usize,
    pub symbol: String,
    pub side: OrderSide,
    pub order_type: OrderType,
    pub volume: f64,
    pub price: f64,
    pub status: OrderStatus,
    pub created_at: DateTime<Utc>,
    pub filled_at: Option<DateTime<Utc>>,
    pub filled_price: Option<f64>,
}
