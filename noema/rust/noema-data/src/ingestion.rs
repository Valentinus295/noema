//! Data ingestion from file formats (CSV, Parquet) and broker APIs.

use crate::tick::Tick;
use anyhow::Result;
use chrono::{DateTime, Utc};

/// Load ticks from a CSV file.
/// Expected columns: timestamp, bid, ask [, volume]
pub fn load_csv_ticks(path: &str) -> Result<Vec<Tick>> {
    let mut reader = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_path(path)?;

    let mut ticks = Vec::new();

    for result in reader.records() {
        let record = result?;
        let timestamp_str = record.get(0).ok_or_else(|| {
            anyhow::anyhow!("Missing timestamp column")
        })?;
        let timestamp = DateTime::parse_from_rfc3339(timestamp_str)?
            .with_timezone(&Utc);

        let bid: f64 = record.get(1).unwrap_or("0").parse()?;
        let ask: f64 = record.get(2).unwrap_or("0").parse()?;
        let volume: Option<f64> = record.get(3).and_then(|v| v.parse().ok());

        ticks.push(Tick {
            timestamp,
            bid,
            ask,
            volume,
            spread: Some((ask - bid) * 10000.0),
        });
    }

    Ok(ticks)
}

/// Python-facing CSV loader.
#[cfg(feature = "python-bindings")]
#[pyo3::pyfunction]
pub fn py_load_csv_ticks(path: &str) -> pyo3::PyResult<Vec<crate::tick::PyTick>> {
    let ticks = load_csv_ticks(path)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    Ok(ticks
        .into_iter()
        .map(|t| crate::tick::PyTick {
            timestamp: t.timestamp.timestamp_nanos_opt().unwrap_or(0),
            bid: t.bid,
            ask: t.ask,
            volume: t.volume,
        })
        .collect())
}
