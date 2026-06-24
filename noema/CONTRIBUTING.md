# Contributing to Noema

Thank you for your interest in contributing to Noema! 🧠

## Governance

Noema operates under a structured governance model. See [GOVERNANCE.md](GOVERNANCE.md) for the full board structure, decision authority matrix, and approval requirements. Major architectural changes require board review.

## Pipeline

All contributions flow through the Noema development pipeline:

1. **Proposal** — Document the change, its rationale, and risk assessment
2. **Review** — Architecture/Quality/Security review as needed (see governance matrix)
3. **Implementation** — Code + tests
4. **CI Validation** — All tests pass, lint clean, security scan clear
5. **Merge** — Squash-merge to `main` with conventional commit message

## How to Contribute

### 1. Clone the Repository

```bash
git clone git@github.com:Valentinus295/noema.git
cd noema
```

### 2. Create a Feature Branch

```bash
git checkout -b feature/amazing-feature
```

### 3. Make Your Changes

- Follow existing code style (PEP 8, type hints, structlog)
- Add docstrings to new functions/classes
- Update documentation if needed
- Python: `ruff format` + `ruff check` before commit
- Rust: `cargo fmt` + `cargo clippy` before commit

### 4. Run Tests

```bash
# Python
pytest
ruff check .

# Rust
cargo test --manifest-path rust/Cargo.toml
cargo clippy --manifest-path rust/Cargo.toml

# Dashboard
cd dashboard && npm run lint
```

### 5. Commit Your Changes

```bash
git commit -m "feat: add amazing feature"
```

Use [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` for new features
- `fix:` for bug fixes
- `docs:` for documentation
- `test:` for tests
- `refactor:` for refactoring
- `security:` for security-sensitive changes

### 6. Push and Create PR

```bash
git push origin feature/amazing-feature
```

Then create a Pull Request on GitHub. CI will run automatically.

## Code Style

- Python 3.11+ with type hints
- Rust 2021 edition
- Follow PEP 8 / rustfmt
- Use structlog for all logging (never `print` in agent code)
- Add docstrings to public functions
- Deterministic agents inherit `DeterministicAgent`; LLM-capable agents inherit `LLMAgent`

## Testing

- Write tests for new features
- Guardian kill-switches must have tests before merge
- Risk calculations must have tests before merge
- Statistical functions must have tests before merge
- All tests must pass before submitting PR

## Questions?

Open an issue on GitHub or consult [GOVERNANCE.md](GOVERNANCE.md) for decision-making processes.

---

Thank you for helping make Noema better! 🚀
