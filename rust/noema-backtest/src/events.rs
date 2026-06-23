//! Event types for the event-driven backtest loop.

use chrono::{DateTime, Utc};

/// Events that flow through the backtesting engine.
pub enum Event {
    /// A new market tick
    Tick(TickEvent),
    /// An order has been placed
    OrderPlaced(OrderEvent),
    /// An order has been filled
    OrderFilled(OrderEvent),
    /// A position has been opened
    PositionOpened(PositionEvent),
    /// A position has been closed
    PositionClosed(PositionEvent),
}

pub struct TickEvent {
    pub timestamp: DateTime<Utc>,
    pub symbol: String,
    pub bid: f64,
    pub ask: f64,
}

pub struct OrderEvent {
    pub order_id: usize,
    pub symbol: String,
    pub side: String,
    pub volume: f64,
    pub price: f64,
    pub timestamp: DateTime<Utc>,
}

pub struct PositionEvent {
    pub position_id: usize,
    pub symbol: String,
    pub pnl: f64,
    pub timestamp: DateTime<Utc>,
}

/// Simple FIFO event queue.
pub struct EventQueue {
    events: Vec<Event>,
}

impl EventQueue {
    pub fn new() -> Self {
        Self { events: Vec::new() }
    }

    pub fn push(&mut self, event: Event) {
        self.events.push(event);
    }

    pub fn pop(&mut self) -> Option<Event> {
        if self.events.is_empty() {
            None
        } else {
            Some(self.events.remove(0))
        }
    }

    pub fn is_empty(&self) -> bool {
        self.events.is_empty()
    }
}
