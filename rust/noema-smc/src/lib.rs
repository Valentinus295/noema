//! noema-smc: Smart Money Concepts indicator computation
//!
//! Rust-native implementation of SMC indicators with PyO3 bindings.
//!
//! Implements (per JARVIS reference patterns):
//! - Market structure detection (BOS/CHoCH)
//! - Order Block detection
//! - Fair Value Gap (FVG) detection
//! - Liquidity sweep detection
//! - Swing point detection

pub mod structure;
pub mod order_block;
pub mod fvg;
pub mod sweep;
pub mod swing;

use pyo3::prelude::*;

/// Python module entry point for noema_smc
#[cfg(feature = "python-bindings")]
#[pymodule]
fn noema_smc(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<structure::PyMarketStructure>()?;
    m.add_class::<order_block::PyOrderBlock>()?;
    m.add_class::<fvg::PyFVG>()?;
    m.add_class::<sweep::PyLiquiditySweep>()?;
    m.add_class::<swing::PySwingDetector>()?;
    m.add_function(wrap_pyfunction!(structure::py_detect_structure, m)?)?;
    m.add_function(wrap_pyfunction!(fvg::py_detect_fvgs, m)?)?;
    m.add_function(wrap_pyfunction!(order_block::py_detect_obs, m)?)?;
    m.add_function(wrap_pyfunction!(sweep::py_detect_sweeps, m)?)?;
    Ok(())
}
