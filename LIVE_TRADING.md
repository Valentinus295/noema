# Noema — LIVE DEMO Trading Guide

> **⚠️ CRITICAL: This is DEMO trading only. NO real money is at risk.**
> Noema has a hard-coded safety barrier that BLOCKS trading on real/live accounts.

---

## Prerequisites (Valentine's Setup)

You're on **Pop!_OS Linux** with:
- ✅ Wine installed
- ✅ MetaTrader 5 installed under Wine
- ✅ FxPesa demo account
- ✅ Python 3.11+ with venv
- ✅ Node.js (for dashboard)

---

## Quick Start — 3 Commands

```bash
# 1. One-time setup
cd ~/noema
./noema-setup

# 2. Verify demo account (CRITICAL SAFETY CHECK)
noema demo-check

# 3. Start LIVE DEMO trading
noema live
```

The system will:
- Start MT5 headless under Wine (auto)
- Connect to FxPesa-Demo server
- Launch dashboard at http://localhost:3000
- Begin multi-agent trading pipeline
- Show live P&L, positions, agent activity

---

## Detailed Setup

### Step 1: Clone and Install

```bash
cd ~
git clone https://github.com/Valentinus295/noema.git
cd noema
./noema-setup
```

### Step 2: Configure `.env`

```bash
# ── NVIDIA NIM ──────────────────────
NIM_API_KEY=nvapi-your-key-here

# ── FxPesa Demo Account ─────────────
Noema_MT5_LOGIN=12345678
Noema_MT5_PASSWORD=your_password
Noema_MT5_SERVER=FxPesa-Demo      # MUST contain "Demo"

# ── Telegram (optional) ─────────────
TELEGRAM_BOT_TOKEN=123456:ABC-DEF
TELEGRAM_CHAT_ID=123456789

# ── MT5 Headless ────────────────────
Noema_MT5_HEADLESS=true
Noema_MT5_STARTUP_WAIT=120

# ── Trading ─────────────────────────
TRADING_PAIRS=EURUSD,GBPUSD,USDJPY
CYCLE_INTERVAL=60
```

### Step 3: Install MT5 Expert Advisor

```bash
noema setup-mt5-ea
```

### Step 4: Verify Demo Account

```bash
noema demo-check
```

Expected output:
```
✅ MT5 bridge detected on port 18812
✅ DEMO ACCOUNT: FxPesa-Demo
   Login:    12345678
   Balance:  $10,000.00
```

### Step 5: Start Live Trading

```bash
noema live
```

On first run, micro-lot safety mode is enforced:
```
🔰 FIRST RUN DETECTED — Micro-Lot Safety Mode
   Lot size capped at: 0.01
```

After successful session, unlock full lots:
```bash
noema live --unlock
```

---

## Safety Architecture

### 1. Demo Account Barrier (HARD)
- `noema live` checks MT5 server name MUST contain "Demo"
- If "FxPesa-Live" or "FBS-Real" → **BLOCKED, exit code 1**
- Emergency override: `Noema_ALLOW_LIVE_ACCOUNT=true` (DO NOT USE)

### 2. Guardian Kill-Switches (17 Checks)

| # | Kill-Switch | What It Does |
|---|-------------|--------------|
| 1 | Daily Loss Limit | Halts if P&L exceeds 3% |
| 2 | Weekly Loss Limit | Halts if P&L exceeds 8% |
| 3 | Consecutive Losses | Pauses after 5 losses |
| 4 | Win-Rate Floor | Halts if < 25% after 10+ trades |
| 5 | SPRT Edge Monitor | Sequential prob ratio test |
| 6 | KS Drift Detection | Live-vs-backtest drift |
| 7 | Heartbeat | Guardian timeout (30s) |
| 8 | Margin Level | Below 200% warning |
| 9 | Max Lot Size | Hard cap (0.01 first run) |
| 10 | Spread Guard | > 3.0 pips |
| 11 | News Blackout | High-impact events |
| 12 | Max Drawdown | > 20% |
| 13 | LLM Error Rate | Too many failures |
| 14 | Stale Data | > 5s old |
| 15 | Actor Broken | Agent silenced |
| 16 | Learning Drawdown | Freeze at >10% |
| 17 | Critic Team Down | Zero responses → kill |

### 3. Max Lot Size Physical Gate
Compile-time constant `Noema_MAX_LOT_SIZE` in `broker/lot_protection.py`
rejects any order exceeding cap BEFORE it reaches MT5.

### 4. Stale Data Protection
BrokerHealthMonitor pings MT5 every 5s. If ticks stop > 5s → ALL orders blocked.

### 5. Telegram Alerts
- Kill-switch activations
- MT5 disconnect/reconnect (after 15s)
- News blackout
- Daily summaries (21:00 UTC)

---

## Daily Commands

```bash
noema live          # Start live demo trading
noema status        # Check status + P&L
noema logs          # Tail live logs
noema stop          # Graceful shutdown
noema demo-check    # Verify demo account
noema dashboard     # Dashboard only
noema live --unlock # Lift micro-lot cap
noema setup-mt5-ea  # Install MT5 EA
```

---

## Dashboard

http://localhost:3000 shows:
- **Dashboard**: Equity curve, P&L, positions
- **Trades**: History with entry/exit
- **Agents**: Signals, confidence scores
- **Risk**: Guardian status, margin, drawdown
- **Settings**: Configuration

---

## MT5 Management

```bash
python -m noema.scripts.mt5_daemon start     # Headless
python -m noema.scripts.mt5_daemon start --visible  # Debug mode
python -m noema.scripts.mt5_daemon status    # Check
python -m noema.scripts.mt5_daemon stop      # Stop
python -m noema.scripts.mt5_daemon restart   # Restart
```

---

## Troubleshooting

**"MT5 bridge not detected on port 18812"**
```bash
sudo apt install xvfb
python -m noema.scripts.mt5_daemon start --visible
```

**"mt5linux package not installed"**
```bash
pip install mt5linux
```

**"LIVE TRADING BLOCKED — not a demo account"**
- Set `Noema_MT5_SERVER=FxPesa-Demo` in `.env`
- This is a SAFETY FEATURE — never bypass

**"Dashboard not loading"**
```bash
cd ~/noema/dashboard && npm install
```

---

## Production Readiness Checklist

- [ ] 50+ successful trades with positive expectancy
- [ ] Zero unexpected Guardian kill-switch activations
- [ ] MT5 connection stable > 8 hours
- [ ] Telegram alerts functional
- [ ] Dashboard showing accurate P&L
- [ ] All 17 kill-switches verified
- [ ] Run `noema live --unlock` to lift micro-lot cap
- [ ] Gradual lot increase: 0.01 → 0.02 → 0.05 → 0.10

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  Noema System                     │
│  Layer 1: DATA (3 agents) → Layer 2: ANALYSIS    │
│  (5 agents) → Layer 3: DECISION (3 agents) →     │
│  Layer 4: EXECUTION (2 agents)                   │
│                                                   │
│  GUARDIAN (17 Kill-Switches) — pre-trade veto    │
│  BROKER GATEWAY (Physical Lot Cap)               │
│  MT5LinuxBroker → RPyC → Wine → MT5 → FxPesa    │
│                                                   │
│  DASHBOARD :3000 | TELEGRAM Alerts | LEARNING    │
└──────────────────────────────────────────────────┘
```

---

_Last updated: 24 June 2026 — Engineering Division (Synapse)_
