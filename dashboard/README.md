# Noema Dashboard

Real-time monitoring dashboard for the Noema multi-agent quantitative FX trading system.

## Overview

The Noema Dashboard provides a professional trading desk interface for monitoring all aspects of the trading system:

- **Main Dashboard** — Real-time P&L, equity curve, open positions, win rate gauges, system status
- **Agent Monitor** — 17-agent grid with real-time status, 12-phase pipeline visualization, agent communication log
- **Trade History** — Filterable/sortable trade table, P&L distribution, win rate by symbol/session/day/hour, drawdown chart
- **Risk Monitor** — Exposure gauges, daily loss limit, consecutive losses, 11 kill-switch indicators, correlation matrix, margin level
- **Settings** — Trading parameters, symbol whitelist, session configuration, broker connection status

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend | React 18 + TypeScript (strict) |
| Build Tool | Vite 5 |
| Routing | React Router v6 |
| Styling | TailwindCSS 3 (dark theme) |
| Charts | Recharts 2 |
| Backend | FastAPI + WebSockets (Python) |
| Data | Redis pub/sub (future), PostgreSQL (future) |

## Quick Start

### 1. Install Frontend Dependencies

```bash
cd dashboard
npm install
```

### 2. Start Development Server

```bash
# Start frontend dev server (port 3000)
npm run dev

# In another terminal, start the API/WS server (port 8000)
cd server
pip install -r requirements.txt
python api.py
```

The frontend dev server proxies `/api` and `/ws` to the backend at `localhost:8000`.

### 3. Production Build

```bash
# Build the React app
npm run build

# Start the Python server (serves both API and static files)
cd server
python api.py
# → http://localhost:8000
```

## Project Structure

```
dashboard/
├── index.html              # Vite entry HTML
├── package.json            # Node dependencies
├── tsconfig.json           # TypeScript config (strict)
├── vite.config.ts          # Vite config with API proxy
├── tailwind.config.ts      # TailwindCSS dark theme
├── postcss.config.js       # PostCSS config
├── public/
│   └── favicon.svg         # Favicon
├── src/
│   ├── main.tsx            # App entry, routing
│   ├── index.css           # Global styles + Tailwind
│   ├── types/
│   │   └── index.ts        # All TypeScript types
│   ├── utils/
│   │   └── format.ts       # Formatting utilities
│   ├── hooks/
│   │   └── useWebSocket.ts # WebSocket hook with auto-reconnect
│   ├── contexts/
│   │   └── DashboardContext.tsx  # Global state + WS integration
│   ├── components/
│   │   ├── Layout.tsx      # App layout + error banner
│   │   ├── Sidebar.tsx     # Navigation sidebar
│   │   └── StatusBadge.tsx # System status indicator
│   └── pages/
│       ├── Dashboard.tsx   # Main dashboard
│       ├── Agents.tsx      # Agent monitor
│       ├── Trades.tsx      # Trade history
│       ├── Risk.tsx        # Risk monitor
│       └── Settings.tsx    # Settings page
└── server/
    ├── __init__.py
    ├── api.py              # FastAPI + WebSocket server
    └── requirements.txt    # Python dependencies
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | System health (broker, Redis, DB, pipeline status) |
| GET | `/api/positions` | Open positions |
| GET | `/api/trades?page=1&limit=50` | Trade history (paginated) |
| GET | `/api/metrics` | P&L, win rate, drawdown, equity curve |
| GET | `/api/agents` | All 17 agent statuses |
| GET | `/api/risk` | Risk metrics + kill switches + correlation matrix |
| GET | `/api/killswitches` | Kill-switch states only |
| GET | `/api/settings` | Trading parameters and configuration |
| WS | `/ws` | Real-time event stream |

## WebSocket Events

The WebSocket connection pushes the following event types:

- `system_status` — System health update
- `agent_update` — Single agent status change
- `agents_update` — Full agent list update
- `position_update` — Open positions update
- `trade_update` — Trade history update
- `metrics_update` — Performance metrics update
- `risk_update` — Risk metrics update
- `pipeline_phase` — Pipeline phase change
- `kill_switch` — Kill switch state change
- `error` — Error notifications

## Key Features

### Dark Theme
Professional trading desk aesthetic with:
- Background: `#0a0e14` (terminal-bg)
- Surface: `#14191f` (terminal-surface)
- Green for profit/bullish, red for loss/bearish

### Real-Time Updates
- WebSocket connection with automatic reconnection (up to 20 attempts, 3s interval)
- No polling — all data pushed in real-time
- Graceful degradation with connection status banner

### Responsive Design
- Works on desktop (1920px+), laptop (1366px+), and tablet (1024px+)
- Grid layouts that collapse gracefully
- Optimized table scrolling on smaller screens

## Integration with Noema Backend

In production, the dashboard server should:

1. **Connect to Redis** — Subscribe to `noema:*` channels for agent messages
2. **Query PostgreSQL** — Fetch historical trade data, daily stats
3. **Push via WebSocket** — Forward real-time events to all connected dashboards

The current `api.py` includes mock data generators. To integrate with the real backend:

```python
# Replace generate_* functions with real database queries:
import asyncpg
import redis.asyncio as redis

# Connect to PostgreSQL
pool = await asyncpg.create_pool(dsn="postgresql://...")

# Connect to Redis
r = redis.Redis.from_url("redis://localhost:6379")

# Subscribe to agent messages
pubsub = r.pubsub()
await pubsub.subscribe("noema:*")
```

## Design Philosophy

- **Conclusions first** — Key metrics visible at a glance
- **Dark terminal aesthetic** — Professional, low eye strain
- **Real-time, not polling** — WebSocket-first architecture
- **Graceful degradation** — Works with stale data when backend is offline
- **Color coding** — Green = profit/healthy, Red = loss/danger, Yellow = warning
