# Contributing to VMPM

Thank you for your interest in contributing to the Valentine Money Printing Machine! 🤖

## How to Contribute

### 1. Fork the Repository

```bash
git clone https://github.com/ovalentine964/valentine-money-printing-machine.git
cd valentine-money-printing-machine
```

### 2. Create a Feature Branch

```bash
git checkout -b feature/amazing-feature
```

### 3. Make Your Changes

- Follow the existing code style
- Add docstrings to new functions/classes
- Update documentation if needed

### 4. Run Tests

```bash
pytest
ruff check .
mypy vmpm/
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

### 6. Push and Create PR

```bash
git push origin feature/amazing-feature
```

Then create a Pull Request on GitHub.

## Code Style

- Use Python 3.11+ features
- Follow PEP 8
- Use type hints
- Keep functions focused and small
- Add docstrings to public functions

## Testing

- Write tests for new features
- Ensure all tests pass before submitting PR
- Aim for high test coverage

## Questions?

Open an issue on GitHub!

---

Thank you for helping make VMPM better! 🚀
