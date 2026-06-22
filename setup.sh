#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# Noema — One-Command Production Setup
# ═══════════════════════════════════════════════════════════════
# Usage: bash setup.sh
#
# This script sets up EVERYTHING:
#   • Python virtual environment + all dependencies
#   • Rust toolchain + crate compilation
#   • Node.js + dashboard dependencies
#   • Environment credentials (interactive prompts)
#   • Docker services (optional)
#
# After running, you'll have a fully operational Noema installation.
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

banner() {
    echo -e "${CYAN}${BOLD}"
    echo "╔═══════════════════════════════════════════╗"
    echo "║   🧠  Noema — Production Setup            ║"
    echo "║   Multi-Agent Quantitative Forex Trading  ║"
    echo "╚═══════════════════════════════════════════╝"
    echo -e "${NC}"
}

section() {
    echo ""
    echo -e "${BLUE}${BOLD}━━━ $1 ━━━${NC}"
    echo ""
}

success() { echo -e "  ${GREEN}✓${NC} $1"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail()    { echo -e "  ${RED}✗${NC} $1"; }
info()    { echo -e "  ${CYAN}→${NC} $1"; }

prompt_secret() {
    # prompt_secret "Label" "ENV_VAR_NAME" "default_value" "help_text"
    local label="$1" var="$2" default="$3" help="$4"
    local value
    echo ""
    echo -e "  ${BOLD}${label}${NC}"
    if [ -n "$help" ]; then
        echo -e "  ${CYAN}${help}${NC}"
    fi
    read -r -p "  Enter value [${default}]: " value
    value="${value:-$default}"
    echo "${var}=${value}" >> .env
    success "${var} configured"
}

prompt_choice() {
    # prompt_choice "Label" "ENV_VAR_NAME" "default" "options" "help"
    local label="$1" var="$2" default="$3" options="$4" help="$5"
    local value
    echo ""
    echo -e "  ${BOLD}${label}${NC}"
    if [ -n "$help" ]; then echo -e "  ${CYAN}${help}${NC}"; fi
    echo -e "  Options: ${options}"
    read -r -p "  Enter value [${default}]: " value
    value="${value:-$default}"
    echo "${var}=${value}" >> .env
    success "${var}=${value}"
}

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

banner

# Paths for Pop!_OS / Ubuntu
WINE_MT5_PATH="$HOME/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"

# ── Step 0: Prerequisites Check ───────────────────────────────
section "Step 0: Checking prerequisites"

OS="$(uname -s)"
echo -e "  ${BOLD}System:${NC} $(uname -s) $(uname -m)"
echo -e "  ${BOLD}Python:${NC} $(python3 --version 2>&1)"
echo ""
if [ "$OS" = "Linux" ]; then
    echo -e "  ${GREEN}✓${NC} Linux — Wine + mt5linux for MT5"
    NEED_WINE=true
elif echo "$OS" | grep -qE "MINGW|MSYS|CYGWIN"; then
    echo -e "  ${GREEN}✓${NC} Windows — native MT5"
    NEED_WINE=false
elif [ "$OS" = "Darwin" ]; then
    echo -e "  ${YELLOW}⚠${NC}  macOS — paper trading only"
    NEED_WINE=false
else
    echo -e "  ${YELLOW}⚠${NC}  Unknown OS — paper trading"
    NEED_WINE=false
fi
echo ""
MISSING=()

check_cmd() {
    if command -v "$1" &> /dev/null; then
        success "$1 ($($1 --version 2>&1 | head -1))"
    else
        fail "$1 — NOT FOUND"
        MISSING+=("$1")
    fi
}

check_cmd python3
# Only require Wine on Linux
if [ "$NEED_WINE" = "true" ]; then
    if command -v wine &> /dev/null; then
        success "wine ($(wine --version 2>&1))"
    else
        warn "wine — NOT FOUND (needed for MT5 on Linux)"
        MISSING+=("wine")
    fi
fi
check_cmd pip3 2>/dev/null || check_cmd uv
check_cmd cargo 2>/dev/null || true  # Rust optional at first
check_cmd node   2>/dev/null || true  # Node optional at first

if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}${BOLD}Missing prerequisites:${NC}"
    for m in "${MISSING[@]}"; do
        case "$m" in
            python3) echo "  python3 → install from https://python.org or 'apt install python3.11'" ;;
            cargo)   echo "  cargo   → install from https://rustup.rs" ;;
            node)    echo "  node    → install from https://nodejs.org (LTS)" ;;
            *)       echo "  $m — please install manually" ;;
        esac
    done
    echo ""
    if [[ "${MISSING[*]}" =~ "python3" ]]; then
        echo -e "${RED}Cannot continue without Python 3.11+. Install it first.${NC}"
        exit 1
    fi
    echo -e "${YELLOW}Continuing with available tools. Install missing ones later.${NC}"
fi

# ── Step 1: Wine + MT5 (platform-aware) ──────────────────────
section "Step 1: Platform-specific setup"

if [ "$NEED_WINE" = "true" ] && ! command -v wine &> /dev/null; then
    echo ""
    echo -e "  ${YELLOW}${BOLD}MT5 requires Wine on Linux.${NC}"
    echo -e "  ${CYAN}Pop!_OS 24.04 / Ubuntu — one command:${NC}"
    echo -e "  sudo dpkg --add-architecture i386"
    echo -e "  sudo apt update && sudo apt install wine64 wine32"
    echo ""
    echo -e "  ${CYAN}Then install MT5 from your broker:${NC}"
    echo -e "  wine ~/Downloads/fxpesa5setup.exe"
    echo ""
elif [ "$NEED_WINE" = "true" ] && [ -f "$WINE_MT5_PATH" ]; then
    success "Wine + MT5 detected"
elif [ "$NEED_WINE" = "true" ]; then
    success "Wine detected — install MT5: wine ~/Downloads/fxpesa5setup.exe"
elif [ "$NEED_WINE" = "false" ] && echo "$OS" | grep -qE "MINGW|MSYS|CYGWIN"; then
    success "Windows — native MT5 available"
elif [ "$OS" = "Darwin" ]; then
    warn "macOS — paper trading only. MT5 not supported."
fi

# ── Step 2:
section "Step 2: Python environment"

# Detect package manager
if command -v uv &> /dev/null; then
    PKG_MGR="uv"
    info "Using uv (fast Python package manager)"
    uv venv .venv 2>/dev/null || true
    source .venv/bin/activate 2>/dev/null || true
    uv sync
    success "Python dependencies installed via uv"
else
    PKG_MGR="pip"
    info "Using pip"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    # Install core deps + mt5linux (Linux only)
    pip install -e ".[dev]"
    [ "$NEED_WINE" = "true" ] && pip install mt5linux && success "mt5linux installed (Linux MT5 bridge)"
    success "Python dependencies installed via pip (incl. mt5linux for Linux MT5)"
fi

# ── Step 3: Credentials ───────────────────────────────────────
section "Step 3: Credentials Configuration"

echo ""
echo -e "  ${YELLOW}${BOLD}🔑  Credential Setup${NC}"
echo -e "  Press Enter to skip optional values."
echo -e "  All values are stored in ${CYAN}.env${NC} (never committed)."
echo ""

# Initialize .env with header
cat > .env << 'HEADER'
# ═══════════════════════════════════════════════════════════
# Noema Environment Configuration
# Generated by setup.sh — DO NOT COMMIT THIS FILE
# ═══════════════════════════════════════════════════════════

HEADER

echo ""
echo -e "  ${BOLD}${CYAN}── NVIDIA NIM / LLM ──${NC}"

prompt_secret \
    "NVIDIA NIM API Key" \
    "NIM_API_KEY" \
    "" \
    "→ Get your key at https://build.nvidia.com/  (REQUIRED for LLM agents)"

prompt_choice \
    "Primary LLM Model" \
    "Noema_LLM_MODEL" \
    "minimax/minimax-m3" \
    "minimax/minimax-m3, claude-4-opus, gpt-5" \
    "→ Model ID as recognized by NVIDIA NIM endpoint"

echo ""
echo -e "  ${BOLD}${CYAN}── MetaTrader 5 ──${NC}"

prompt_secret \
    "MT5 Account Number" \
    "Noema_MT5_LOGIN" \
    "" \
    "→ Your MT5 trading account login (REQUIRED for live/paper trading)"

prompt_secret \
    "MT5 Password" \
    "Noema_MT5_PASSWORD" \
    "" \
    "→ Your MT5 trading account password"

prompt_secret \
    "MT5 Server" \
    "Noema_MT5_SERVER" \
    "FxPesa-Demo" \
    "→ Broker server name (FxPesa-Demo, FBS-Real, MetaQuotes-Demo, etc.)"

echo ""
echo -e "  ${BOLD}${CYAN}── Database ──${NC}"

prompt_secret \
    "PostgreSQL URL" \
    "DATABASE_URL" \
    "postgresql+asyncpg://noema:noema@localhost:5432/noema" \
    "→ Leave default for Docker setup, or enter your own PostgreSQL URL"

prompt_secret \
    "Redis URL" \
    "REDIS_URL" \
    "redis://localhost:6379/0" \
    "→ Leave default for Docker setup, or enter your own Redis URL"

echo ""
echo -e "  ${BOLD}${CYAN}── Trading ──${NC}"

prompt_choice \
    "Trading Pairs" \
    "TRADING_PAIRS" \
    "EURUSD,GBPUSD,USDJPY,AUDUSD" \
    "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCHF,USDCAD,NZDUSD,XAUUSD" \
    "→ Comma-separated list of MT5 symbols"

prompt_choice \
    "Cycle Interval (seconds)" \
    "CYCLE_INTERVAL" \
    "60" \
    "60, 300, 900, 3600" \
    "→ How often the pipeline scans for setups"

prompt_choice \
    "Trading Mode" \
    "TRADING_MODE" \
    "paper" \
    "paper, live, analyze" \
    "→ paper=simulated, live=real money, analyze=read-only"

echo ""
echo -e "  ${BOLD}${CYAN}── Optional: Dashboard ──${NC}"

DASH_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || echo "")
prompt_secret \
    "Dashboard API Key" \
    "DASHBOARD_API_KEY" \
    "$DASH_KEY" \
    "→ Auto-generated random key. Use this to access the monitoring dashboard."

echo ""
echo -e "  ${BOLD}${CYAN}── Optional: Telegram Alerts ──${NC}"

prompt_secret \
    "Telegram Bot Token" \
    "TELEGRAM_BOT_TOKEN" \
    "" \
    "→ Get from @BotFather on Telegram (skip to disable)"

prompt_secret \
    "Telegram Chat ID" \
    "TELEGRAM_CHAT_ID" \
    "" \
    "→ Your Telegram user/group ID for trade alerts"

echo ""
echo -e "  ${BOLD}${CYAN}── Optional: Observability ──${NC}"

prompt_secret \
    "Langfuse Public Key" \
    "LANGFUSE_PUBLIC_KEY" \
    "" \
    "→ From https://cloud.langfuse.com (skip to disable LLM tracing)"

prompt_secret \
    "Langfuse Secret Key" \
    "LANGFUSE_SECRET_KEY" \
    "" \
    "→ From https://cloud.langfuse.com"

echo ""
echo -e "  ${BOLD}${CYAN}── Logging ──${NC}"

prompt_choice \
    "Log Level" \
    "LOG_LEVEL" \
    "INFO" \
    "DEBUG, INFO, WARNING, ERROR" \
    "→ DEBUG for development, INFO for production"

# ── Finalize .env ─────────────────────────────────────────────
cat >> .env << 'FOOTER'

# ── Docker Compose Environment ──────────────────────────────
POSTGRES_USER=noema
POSTGRES_PASSWORD=noema
POSTGRES_DB=noema
REDIS_PASSWORD=noema
GRAFANA_ADMIN_PASSWORD=noema
FOOTER

success ".env file created with $(wc -l < .env) lines"

# ── Step 4: Verify Configuration ──────────────────────────────
section "Step 4: Verifying configuration"

if [ -n "${NIM_API_KEY:-}" ] || grep -q "NIM_API_KEY=nvapi-" .env 2>/dev/null; then
    success "NVIDIA NIM API key configured"
else
    warn "NVIDIA NIM API key not set — LLM agents will be disabled"
fi

if grep -q "Noema_MT5_LOGIN=" .env 2>/dev/null && ! grep -q "Noema_MT5_LOGIN=$" .env; then
    success "MT5 credentials configured"
else
    warn "MT5 credentials not set — broker connection disabled"
fi

# ── Step 5: Rust Build (if available) ─────────────────────────
section "Step 5: Rust workspace"

if command -v cargo &> /dev/null; then
    info "Building Rust crates..."
    cd rust
    if cargo build --release 2>&1 | tail -3; then
        success "Rust crates compiled (noema-data, noema-backtest, noema-smc)"
    else
        warn "Rust build had issues — Python fallbacks will be used"
    fi
    cd ..
else
    warn "Rust not installed — using Python fallbacks for backtesting/SMC"
    info "Install Rust later: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
fi

# ── Step 6: Dashboard Setup ───────────────────────────────────
section "Step 6: Dashboard"

if command -v node &> /dev/null && command -v npm &> /dev/null; then
    info "Installing dashboard dependencies..."
    cd dashboard
    npm install --silent 2>&1 | tail -1
    success "Dashboard dependencies installed"
    info "Start dashboard: cd dashboard && npm run dev"
    cd ..
else
    warn "Node.js not installed — dashboard unavailable"
    info "Install Node.js: https://nodejs.org (LTS version)"
fi

# ── Step 7: Docker Services (optional) ────────────────────────
section "Step 7: Docker services"

if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    info "Docker detected. Starting background services..."
    if docker compose up -d postgres redis 2>&1 | tail -3; then
        success "PostgreSQL + Redis running"
        info "Prometheus + Grafana available: docker compose up -d"
    else
        warn "Docker compose had issues — check docker-compose.yml"
    fi
else
    warn "Docker not available — services must be run manually"
    info "Install Docker: https://docs.docker.com/engine/install/"
fi

# ── Step 8: MT5 Connection Test ──────────────────────────────
section "Step 8: MT5 Connection Test"

if [ -f noema/scripts/start_mt5.py ] && command -v wine &> /dev/null; then
    info "Testing MT5 connection..."
    if python3 -m noema.scripts.start_mt5 2>/dev/null; then
        success "MT5 connection test passed"
    else
        warn "MT5 not currently running — start it with: python -m noema.scripts.start_mt5"
    fi
fi

# ── Step 9: Quick validation ──────────────────────────────────
section "Step 9: Quick validation"

if [ -f noema/scripts/run_tests.sh ]; then
    info "Running import validation..."
    if python3 -c "import sys; sys.path.insert(0,'.'); from noema.core.types import Bar; print('OK')" 2>/dev/null; then
        success "Package imports resolve correctly"
    else
        warn "Import check had issues — run full tests: bash noema/scripts/run_tests.sh unit"
    fi
fi

# ── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔═══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║   🧠  Noema Setup Complete!               ║${NC}"
echo -e "${GREEN}${BOLD}╚═══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Quick Start:${NC}"
echo ""
echo -e "  ${CYAN}# Activate environment${NC}"
echo -e "  source .venv/bin/activate"
echo ""
echo -e "  ${BOLD}${CYAN}── Platform: ${OS} ──${NC}"
echo ""
if [ "$NEED_WINE" = "true" ]; then
    echo -e "  ${CYAN}# Start MT5 under Wine${NC}"
    echo -e "  python -m noema.scripts.start_mt5"
    echo ""
fi
echo -e "  ${BOLD}${CYAN}── Trading (auto-detects platform) ──${NC}"
echo ""
echo -e "  ${CYAN}# Paper trading (safe — works everywhere)${NC}"
echo -e "  python -m noema.main --mode paper --pair EURUSD"
echo ""
if [ "$NEED_WINE" = "true" ] || echo "$OS" | grep -qE "MINGW|MSYS|CYGWIN"; then
    echo -e "  ${CYAN}# Live trading (auto-detects MT5)${NC}"
    echo -e "  python -m noema.main --mode live"
else
    echo -e "  ${YELLOW}# Live trading unavailable on ${OS}${NC}"
fi
echo ""
echo -e "  ${BOLD}${CYAN}── Dashboard (watch trades live) ──${NC}"
echo ""
echo -e "  ${CYAN}# Terminal 1: Start the backend${NC}"
echo -e "  cd dashboard && python server/api.py"
echo ""
echo -e "  ${CYAN}# Terminal 2: Start the frontend${NC}"
echo -e "  cd dashboard && npm run dev"
echo ""
echo -e "  ${CYAN}# Open http://localhost:3000 in your browser${NC}"
echo ""
echo -e "  ${CYAN}# Run tests${NC}"
echo -e "  bash noema/scripts/run_tests.sh coverage"
echo ""
echo -e "  ${BOLD}Documentation:${NC}"
echo -e "  README.md               — Overview & strategy"
echo -e "  docs/ARCHITECTURE.md     — System design"
echo -e "  docs/SECURITY.md         — Security model"
echo -e "  docs/CREDENTIAL_ROTATION.md — Token management"
echo -e "  docs/ROADMAP.md          — Future plans"
echo ""
echo -e "  ${YELLOW}⚠️  Remember: Start with paper trading. Never go live without${NC}"
echo -e "  ${YELLOW}    validating on demo for at least 2 weeks.${NC}"
echo ""
