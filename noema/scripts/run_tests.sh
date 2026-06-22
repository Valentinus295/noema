#!/usr/bin/env bash
#
# Noema Test Runner
# =================
# Runs the Noema test suite with multiple configurations.
#
# Usage:
#   ./scripts/run_tests.sh              # Run all unit tests
#   ./scripts/run_tests.sh unit         # Run unit tests only
#   ./scripts/run_tests.sh integration  # Run integration tests only
#   ./scripts/run_tests.sh all          # Run everything (unit + integration)
#   ./scripts/run_tests.sh coverage     # Generate coverage report
#   ./scripts/run_tests.sh ci           # CI mode (strict, with coverage fail-under)
#
# Requirements:
#   - Python 3.11+
#   - Virtual env with dev dependencies installed
#   - Redis server (for integration tests)
#   - PostgreSQL (for full integration tests)
#
set -euo pipefail

# ── Resolve project root ────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Colors ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── Configuration ───────────────────────────────────────────────────
COV_DIR="${PROJECT_ROOT}/htmlcov"
COV_FILE="${PROJECT_ROOT}/.coverage"
COV_FAIL_UNDER=60
PYTEST_ARGS_UNIT="-v --tb=short -m unit"
PYTEST_ARGS_INTEGRATION="-v --tb=short -m integration --timeout=60"
PYTEST_ARGS_COV="--cov=noema --cov-report=term-missing --cov-report=html:${COV_DIR} --cov-fail-under=${COV_FAIL_UNDER}"

# ── Help ────────────────────────────────────────────────────────────
show_help() {
    cat <<EOF
Noema Test Runner

Usage: $(basename "$0") [COMMAND]

Commands:
  unit          Run unit tests (fast, no external deps)
  integration   Run integration tests (requires Redis/Postgres)
  all           Run all tests
  coverage      Run all tests with coverage report
  ci            CI mode — strict checks, fail under ${COV_FAIL_UNDER}% coverage
  slow          Run slow tests
  live          Run live tests (requires MT5/NIM API)
  help          Show this help

Environment:
  REDIS_URL         Redis connection (default: redis://localhost:6379/0)
  DATABASE_URL      PostgreSQL connection (default: sqlite)
  NIM_API_KEY       NVIDIA NIM API key for live tests
  Noema_MT5_LOGIN   MT5 login for live tests
  Noema_MT5_PASSWORD MT5 password
  Noema_MT5_SERVER  MT5 server

Examples:
  $(basename "$0") unit
  $(basename "$0") coverage
  $(basename "$0") ci
EOF
}

# ── Setup ────────────────────────────────────────────────────────────
setup_env() {
    echo -e "${CYAN}[setup]${NC} Checking environment..."
    
    # Check Python version
    PYTHON_BIN="${PYTHON_BIN:-python3}"
    if ! command -v "$PYTHON_BIN" &>/dev/null; then
        echo -e "${RED}[ERROR]${NC} python3 not found"
        exit 1
    fi
    
    PY_VER=$("$PYTHON_BIN" --version 2>&1 | awk '{print $2}')
    echo -e "  Python: ${PY_VER}"
    
    # Check if pytest is available
    if ! "$PYTHON_BIN" -m pytest --version &>/dev/null; then
        echo -e "${RED}[ERROR]${NC} pytest not found. Install dev dependencies:"
        echo "  pip install -e '.[dev]'"
        exit 1
    fi
    
    # Ensure test directory exists
    if [ ! -d "${PROJECT_ROOT}/noema/tests" ]; then
        echo -e "${RED}[ERROR]${NC} Test directory not found at noema/tests/"
        exit 1
    fi
    
    echo -e "${GREEN}[setup]${NC} Environment OK"
    echo ""
}

# ── Unit Tests ───────────────────────────────────────────────────────
run_unit() {
    echo -e "${CYAN}[unit]${NC} Running unit tests..."
    "$PYTHON_BIN" -m pytest ${PYTEST_ARGS_UNIT} "${PROJECT_ROOT}/noema/tests/"
    local exit_code=$?
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}[unit]${NC} All unit tests passed! ✅"
    else
        echo -e "${RED}[unit]${NC} Unit tests failed ❌"
        return $exit_code
    fi
}

# ── Integration Tests ────────────────────────────────────────────────
run_integration() {
    echo -e "${CYAN}[integration]${NC} Running integration tests..."
    
    # Check if Redis is available
    REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
    if command -v redis-cli &>/dev/null; then
        if redis-cli ping &>/dev/null 2>&1; then
            echo -e "  Redis: ${GREEN}available${NC}"
        else
            echo -e "  Redis: ${YELLOW}unavailable — skipping Redis tests${NC}"
            export SKIP_REDIS_TESTS=1
        fi
    else
        echo -e "  Redis: ${YELLOW}redis-cli not found — skipping Redis tests${NC}"
        export SKIP_REDIS_TESTS=1
    fi
    
    "$PYTHON_BIN" -m pytest ${PYTEST_ARGS_INTEGRATION} "${PROJECT_ROOT}/noema/tests/"
    local exit_code=$?
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}[integration]${NC} All integration tests passed! ✅"
    else
        echo -e "${RED}[integration]${NC} Integration tests failed ❌"
        return $exit_code
    fi
}

# ── Coverage ─────────────────────────────────────────────────────────
run_coverage() {
    echo -e "${CYAN}[coverage]${NC} Running tests with coverage..."
    echo -e "  Output: ${COV_DIR}/index.html"
    
    "$PYTHON_BIN" -m pytest ${PYTEST_ARGS_COV} \
        -m "not slow and not live" \
        "${PROJECT_ROOT}/noema/tests/"
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}[coverage]${NC} Coverage report generated ✅"
        
        # Show summary
        "$PYTHON_BIN" -m coverage report --fail-under=${COV_FAIL_UNDER} 2>/dev/null || true
    else
        echo -e "${RED}[coverage]${NC} Tests failed or coverage below ${COV_FAIL_UNDER}% ❌"
        return $exit_code
    fi
}

# ── CI Mode ──────────────────────────────────────────────────────────
run_ci() {
    echo -e "${CYAN}[ci]${NC} Running CI test suite..."
    echo ""
    
    # Run unit tests first (fail fast)
    run_unit || exit 1
    
    echo ""
    
    # Run coverage with strict checks
    echo -e "${CYAN}[ci]${NC} Running coverage check..."
    "$PYTHON_BIN" -m pytest ${PYTEST_ARGS_COV} \
        -m "not slow and not live" \
        --junitxml=test-results.xml \
        "${PROJECT_ROOT}/noema/tests/"
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo ""
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}  CI Suite Passed! ✅${NC}"
        echo -e "${GREEN}  Coverage ≥ ${COV_FAIL_UNDER}%${NC}"
        echo -e "${GREEN}  Report: ${COV_DIR}/index.html${NC}"
        echo -e "${GREEN}  JUnit XML: test-results.xml${NC}"
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    else
        echo ""
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${RED}  CI Suite Failed ❌${NC}"
        echo -e "${RED}  Check report above for details${NC}"
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        exit 1
    fi
}

# ── Slow Tests ───────────────────────────────────────────────────────
run_slow() {
    echo -e "${CYAN}[slow]${NC} Running slow tests..."
    "$PYTHON_BIN" -m pytest -v --tb=short -m slow "${PROJECT_ROOT}/noema/tests/"
}

# ── Live Tests ───────────────────────────────────────────────────────
run_live() {
    echo -e "${YELLOW}[live]${NC} Running live tests (requires MT5/NIM API)..."
    "$PYTHON_BIN" -m pytest -v --tb=long -m live "${PROJECT_ROOT}/noema/tests/"
}

# ── Main ─────────────────────────────────────────────────────────────
main() {
    local cmd="${1:-unit}"
    
    case "$cmd" in
        unit)
            setup_env
            run_unit
            ;;
        integration)
            setup_env
            run_integration
            ;;
        all)
            setup_env
            run_unit
            echo ""
            run_integration
            ;;
        coverage)
            setup_env
            run_coverage
            ;;
        ci)
            setup_env
            run_ci
            ;;
        slow)
            setup_env
            run_slow
            ;;
        live)
            setup_env
            run_live
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo -e "${RED}[ERROR]${NC} Unknown command: $cmd"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
