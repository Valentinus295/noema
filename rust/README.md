# Noema Rust Workspace

High-performance Rust crates for the Noema quantitative trading system.
All crates support both pure-Rust usage and Python bindings via PyO3.

## Crate Structure

```
rust/
├── Cargo.toml              # Workspace root
├── README.md               # This file
├── noema-data/             # Market data ingestion & processing
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs          # Module root + Python module init
│       ├── tick.rs         # Tick data structures & parsing
│       ├── aggregation.rs  # OHLCV bar aggregation from ticks
│       └── ingestion.rs    # CSV/Parquet loading
├── noema-backtest/         # Backtesting engine
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs          # Module root + Python module init
│       ├── engine.rs       # Event loop, order matching, P&L
│       ├── events.rs       # Event types for event-driven loop
│       ├── order.rs        # Order types & status
│       ├── position.rs     # Position tracking
│       └── metrics.rs      # Sharpe, drawdown, profit factor
└── noema-smc/              # SMC indicators (PyO3 bindings)
    ├── Cargo.toml
    └── src/
        ├── lib.rs          # Module root + Python module init
        ├── swing.rs        # Fractal swing point detection
        ├── structure.rs    # BOS/CHoCH market structure
        ├── order_block.rs  # Order Block (OB) detection
        ├── fvg.rs          # Fair Value Gap (FVG) detection
        └── sweep.rs        # Liquidity sweep detection
```

## Dependencies

- **PyO3 0.23** — Python bindings
- **numpy 0.23** — NumPy interop
- **Arrow 54** — Columnar data format
- **Polars 0.45** — Fast DataFrame operations
- **ndarray 0.16** — N-dimensional arrays
- **Rayon** — Data parallelism
- **Tokio** — Async runtime
- **Serde** — Serialization

## Building

### Prerequisites

1. Install Rust (1.75+):
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```

2. Install Python 3.11+ with development headers:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install python3.11-dev
   
   # macOS
   brew install python@3.11
   ```

3. Create a virtual environment:
   ```bash
   cd ..  # back to project root
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install maturin
   ```

### Build all crates

```bash
# Debug build (fast compile, slower runtime)
cd rust
cargo build

# Release build (slow compile, fast runtime)
cargo build --release
```

### Build Python wheels with maturin

```bash
# Build individual crate
cd rust/noema-smc
maturin develop --release

# Or build all from workspace
cd rust
maturin build --release -m noema-smc/Cargo.toml
maturin build --release -m noema-data/Cargo.toml
maturin build --release -m noema-backtest/Cargo.toml
```

### Run tests

```bash
cd rust
cargo test
cargo test --release
```

### Feature flags

- `default` = `["python-bindings"]` — builds PyO3 extension modules
- `pure-rust` — builds only the Rust library (no Python bindings), useful for:
  - CI builds (faster compilation, no Python headers needed)
  - Embedding in Rust-only applications
  - WASM targets

Example:
```bash
cargo build --no-default-features --features pure-rust
```

## Usage from Python

After building with `maturin develop`:

```python
# These imports will work after maturin build
from noema_smc import detect_fvgs, detect_obs, detect_structure, detect_sweeps
from noema_data import OhlcvAggregator, Tick
from noema_backtest import BacktestEngine, Metrics

# FVG detection
import numpy as np
highs = np.array([1.1000, 1.1010, 1.1005, 1.1020, 1.1030])
lows  = np.array([1.0990, 1.1000, 1.0995, 1.1010, 1.1020])
fvgs = detect_fvgs(highs.tolist(), lows.tolist())
for fvg in fvgs:
    print(f"FVG at {fvg.index}: {fvg.fvg_type} [{fvg.bottom:.4f}-{fvg.top:.4f}]")
```

## Architecture Notes

### Why Rust?

1. **Latency**: Tick-by-tick SMC computation in Python is ~50-100ms per 1000 bars.
   Rust reduces this to ~1-5ms.
2. **Memory**: Arrow/Polars columnar ops avoid pandas DataFrame overhead.
3. **Safety**: No GIL contention when running analysis in background threads.
4. **Deployment**: Single `.so`/`.dylib` file — no dependency hell.

### Crate Dependency Graph

```
noema-data (foundation: tick, OHLCV, ingestion)
    ↑
    ├── noema-backtest (engine uses data structures from noema-data)
    └── noema-smc (indicators use data structures from noema-data)
```

### Performance Targets (estimated on 100k bars)

| Operation | Python (pandas) | Rust (native) | Speedup |
|-----------|----------------|---------------|---------|
| FVG detection | ~85ms | ~2ms | 42x |
| Order Block detection | ~120ms | ~3ms | 40x |
| Liquidity sweeps | ~200ms | ~5ms | 40x |
| OHLCV aggregation (1M ticks) | ~500ms | ~15ms | 33x |
| Backtest (10k trades) | ~2s | ~50ms | 40x |

## Roadmap

- [x] Workspace scaffold
- [x] SMC indicators (FVG, OB, sweeps, structure)
- [x] Tick parsing and OHLCV aggregation
- [x] Backtest engine core
- [ ] MT5 tick stream integration
- [ ] Parquet/Arrow I/O pipeline
- [ ] Real-time indicator streaming via Redis
- [ ] GPU-accelerated backtesting (CUDA via cust)
- [ ] WASM build for web-based backtest visualizer
