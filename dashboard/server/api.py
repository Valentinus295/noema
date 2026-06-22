"""
Noema Dashboard API Server

FastAPI + WebSocket server that:
- Serves REST API endpoints for dashboard data
- Connects to Redis for agent message bus subscription
- Pushes real-time updates via WebSocket
- Serves the built React app as static files

Security: API key auth on all endpoints (env: DASHBOARD_API_KEY).
See dashboard/DASHBOARD_SECURITY.md for production setup.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Any

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

logger = structlog.get_logger(__name__)

# ── Security Configuration ──────────────────────────────────────────

DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")
SKIP_AUTH = os.getenv("DASHBOARD_SKIP_AUTH", "0") == "1" or not DASHBOARD_API_KEY

if not DASHBOARD_API_KEY:
    logger.warning(
        "dashboard_no_api_key",
        message="DASHBOARD_API_KEY not set — auth is DISABLED. "
                "Set in production. See DASHBOARD_SECURITY.md.",
    )


def verify_api_key(request: Request) -> bool:
    """Check API key from Authorization header or ?token= query parameter."""
    if SKIP_AUTH:
        return True
    # Header: Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == DASHBOARD_API_KEY:
            return True
    # Query: ?token=<token>
    token = request.query_params.get("token", "")
    if token and token == DASHBOARD_API_KEY:
        return True
    return False


# ── Rate Limiting (simple token bucket, in-memory) ──────────────────

class TokenBucket:
    """Simple in-memory token bucket rate limiter."""

    def __init__(self, rate: int = 60, burst: int = 120):
        self.rate = rate  # tokens per minute
        self.burst = burst  # max burst
        self.tokens: dict[str, float] = {}  # client -> token count
        self.last_refill: dict[str, float] = {}  # client -> last refill timestamp

    def is_allowed(self, client_id: str) -> bool:
        now = time.monotonic()
        # Initialize if first request
        if client_id not in self.tokens:
            self.tokens[client_id] = self.burst
            self.last_refill[client_id] = now
            return True

        # Refill tokens
        elapsed = now - self.last_refill[client_id]
        refill_tokens = elapsed * (self.rate / 60.0)
        self.tokens[client_id] = min(self.burst, self.tokens[client_id] + refill_tokens)
        self.last_refill[client_id] = now

        # Consume 1 token
        if self.tokens[client_id] >= 1:
            self.tokens[client_id] -= 1
            return True
        return False


rate_limiter = TokenBucket(rate=120, burst=200)


def get_client_id(request: Request) -> str:
    """Derive a client identifier for rate limiting."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Auth Middleware ──────────────────────────────────────────────────

async def auth_middleware(request: Request, call_next):
    """API key authentication middleware for all /api/* routes."""
    path = request.url.path

    # Skip auth for static files, docs, WebSocket (handled separately)
    if not path.startswith("/api/"):
        return await call_next(request)

    # Rate limiting
    client = get_client_id(request)
    if not rate_limiter.is_allowed(client):
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Try again later."},
            headers={"Retry-After": "30"},
        )

    # Auth check
    if not verify_api_key(request):
        logger.warning("dashboard_unauthorized", client=client, path=path)
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized. Provide DASHBOARD_API_KEY via Authorization header or ?token= parameter."},
        )

    return await call_next(request)

# ── App Setup ───────────────────────────────────────────────────────

app = FastAPI(
    title="Noema Dashboard API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)

# Register auth middleware
app.middleware("http")(auth_middleware)

# CORS: Restrict to dev frontends in development.
# In production, replace with your actual dashboard domain(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

START_TIME = time.time()

# ── WebSocket Manager ───────────────────────────────────────────────

class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        client_id = f"client-{len(self._connections) + 1}-{int(time.time() * 1000)}"
        async with self._lock:
            self._connections[client_id] = ws
        logger.info("ws_client_connected", client_id=client_id, total=len(self._connections))
        return client_id

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            self._connections.pop(client_id, None)
        logger.info("ws_client_disconnected", client_id=client_id, total=len(self._connections))

    async def broadcast(self, event_type: str, data: Any) -> None:
        message = json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        async with self._lock:
            dead: list[str] = []
            for cid, ws in self._connections.items():
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.append(cid)
            for cid in dead:
                self._connections.pop(cid, None)

    @property
    def client_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()

# ── Mock Data Generators ────────────────────────────────────────────

AGENT_DEFS = [
    {"id": "macro", "name": "MacroEconomic", "layer": 1, "phase": "data_collection", "type": "deterministic"},
    {"id": "currency", "name": "CurrencyStrength", "layer": 1, "phase": "data_collection", "type": "deterministic"},
    {"id": "session", "name": "SessionIntelligence", "layer": 1, "phase": "data_collection", "type": "deterministic"},
    {"id": "structure", "name": "MarketStructure", "layer": 2, "phase": "technical_analysis", "type": "deterministic"},
    {"id": "institutional", "name": "InstitutionalFootprint", "layer": 2, "phase": "technical_analysis", "type": "deterministic"},
    {"id": "sr", "name": "SupportResistance", "layer": 2, "phase": "technical_analysis", "type": "deterministic"},
    {"id": "momentum", "name": "Momentum", "layer": 2, "phase": "macro_analysis", "type": "deterministic"},
    {"id": "price_action", "name": "PriceAction", "layer": 2, "phase": "technical_analysis", "type": "deterministic"},
    {"id": "trend", "name": "TrendAnalyzer", "layer": 2, "phase": "macro_analysis", "type": "deterministic"},
    {"id": "confluence", "name": "Confluence", "layer": 2, "phase": "confluence", "type": "deterministic"},
    {"id": "fundamental", "name": "Fundamental", "layer": 2, "phase": "sentiment_analysis", "type": "deterministic"},
    {"id": "thesis", "name": "TradeThesis", "layer": 3, "phase": "thesis_generation", "type": "llm"},
    {"id": "devil", "name": "DevilsAdvocate", "layer": 3, "phase": "devils_advocate", "type": "llm"},
    {"id": "cio", "name": "CIO", "layer": 3, "phase": "cio_decision", "type": "llm"},
    {"id": "risk", "name": "RiskManager", "layer": 4, "phase": "risk_assessment", "type": "deterministic"},
    {"id": "execution", "name": "Execution", "layer": 4, "phase": "execution", "type": "deterministic"},
    {"id": "learning", "name": "Learning", "layer": 5, "phase": "learning", "type": "llm"},
]


def generate_agents() -> list[dict[str, Any]]:
    """Generate agent status data."""
    agents = []
    now = datetime.now(timezone.utc)
    for i, ad in enumerate(AGENT_DEFS):
        # Cycle states: most idle, some active
        if i < 3:
            state = "active"
        elif i < 14:
            state = "idle"
        else:
            state = "idle"

        agents.append({
            "id": ad["id"],
            "name": ad["name"],
            "layer": ad["layer"],
            "phase": ad["phase"],
            "type": ad["type"],
            "state": state,
            "lastActivity": (now - timedelta(seconds=i * 5)).isoformat(),
            "lastOutput": (
                "Bullish structure, BOS at 1.0850" if ad["id"] == "structure"
                else "RSI=42, neutral" if ad["id"] == "momentum"
                else "No major news in window" if ad["id"] == "fundamental"
                else "Confluence score: 0.78" if ad["id"] == "confluence"
                else "Awaiting market data…"
            ),
            "errorMessage": None,
            "executionTimeMs": 12.5 + i * 3.2 if i < 12 else None,
        })
    return agents


def generate_system_health() -> dict[str, Any]:
    """Generate system health status."""
    uptime = time.time() - START_TIME
    return {
        "status": "green",
        "uptime": uptime,
        "pipelineActive": True,
        "brokerConnected": True,
        "redisConnected": True,
        "dbConnected": True,
        "lastPipelineRun": datetime.now(timezone.utc).isoformat(),
        "pipelineLatencyMs": 245.3,
        "llmStatus": "online",
        "activeAgents": 3,
        "totalAgents": 17,
        "version": "0.1.0",
    }


def generate_positions() -> list[dict[str, Any]]:
    """Generate mock open positions."""
    return [
        {
            "ticket": 10042,
            "symbol": "EURUSD",
            "direction": "sell",
            "volume": 0.05,
            "openPrice": 1.08500,
            "currentPrice": 1.08420,
            "stopLoss": 1.08750,
            "takeProfit": 1.08100,
            "pnl": 4.00,
            "pnlPips": 8.0,
            "magic": 42001,
        },
        {
            "ticket": 10045,
            "symbol": "GBPUSD",
            "direction": "buy",
            "volume": 0.03,
            "openPrice": 1.27100,
            "currentPrice": 1.27240,
            "stopLoss": 1.26850,
            "takeProfit": 1.27600,
            "pnl": 4.20,
            "pnlPips": 14.0,
            "magic": 42002,
        },
    ]


def generate_metrics() -> dict[str, Any]:
    """Generate mock metrics."""
    equity = 10245.30
    initial = 10000.0
    return {
        "balance": 10210.50,
        "equity": equity,
        "dailyPnl": 45.30,
        "weeklyPnl": 312.80,
        "monthlyPnl": 1280.50,
        "totalTrades": 247,
        "winRate": 0.52,
        "profitFactor": 1.34,
        "sharpeRatio": 1.12,
        "maxDrawdown": -0.085,
        "currentDrawdown": -0.012,
        "avgRR": 1.85,
        "bestTrade": 340.20,
        "worstTrade": -180.50,
        "equityCurve": [
            {"timestamp": (datetime.now(timezone.utc) - timedelta(hours=24 - i)).isoformat(), "equity": equity * (1 + (i - 12) * 0.002 + (i % 3) * 0.001)}
            for i in range(25)
        ],
        "dailyWinRateHistory": [
            {"date": (datetime.now(timezone.utc) - timedelta(days=30 - i)).strftime("%Y-%m-%d"), "winRate": 0.45 + i * 0.005, "trades": 3 + i % 5}
            for i in range(30)
        ],
        "pnlDistribution": [
            {"range": "-$200-", "count": 12},
            {"range": "-$100", "count": 28},
            {"range": "-$50", "count": 35},
            {"range": "$0", "count": 22},
            {"range": "+$50", "count": 45},
            {"range": "+$100", "count": 38},
            {"range": "+$200+", "count": 25},
        ],
        "winRateBySymbol": [
            {"symbol": "EURUSD", "winRate": 0.54, "trades": 78},
            {"symbol": "GBPUSD", "winRate": 0.49, "trades": 62},
            {"symbol": "USDJPY", "winRate": 0.56, "trades": 45},
            {"symbol": "AUDUSD", "winRate": 0.47, "trades": 38},
            {"symbol": "XAUUSD", "winRate": 0.52, "trades": 24},
        ],
        "winRateBySession": [
            {"session": "London", "winRate": 0.55, "trades": 89},
            {"session": "NewYork", "winRate": 0.50, "trades": 72},
            {"session": "Overlap", "winRate": 0.58, "trades": 45},
            {"session": "Tokyo", "winRate": 0.43, "trades": 26},
            {"session": "Sydney", "winRate": 0.38, "trades": 15},
        ],
        "winRateByDayOfWeek": [
            {"day": "Mon", "winRate": 0.48, "trades": 42},
            {"day": "Tue", "winRate": 0.55, "trades": 55},
            {"day": "Wed", "winRate": 0.53, "trades": 60},
            {"day": "Thu", "winRate": 0.51, "trades": 52},
            {"day": "Fri", "winRate": 0.47, "trades": 38},
        ],
        "winRateByHour": [
            {"hour": hour, "winRate": 0.45 + (hour % 4) * 0.04, "trades": 10 + hour % 6}
            for hour in range(0, 24, 2)
        ],
        "drawdownHistory": [
            {"timestamp": (datetime.now(timezone.utc) - timedelta(days=30 - i)).isoformat(), "equity": -0.02 + (i - 15) * 0.003}
            for i in range(30)
        ],
    }


def generate_risk_metrics() -> dict[str, Any]:
    """Generate mock risk metrics."""
    return {
        "currentExposurePct": 8.0,
        "maxExposurePct": 75.0,
        "dailyLossPct": 0.45,
        "dailyLossLimitPct": 1.0,
        "consecutiveLosses": 1,
        "maxConsecutiveLosses": 5,
        "marginLevel": 450.5,
        "marginLevelWarning": 200.0,
        "freeMargin": 8740.20,
        "killSwitches": [
            {"id": "ks-1", "name": "Daily Loss Limit", "description": "Halts if daily loss exceeds limit", "active": False, "value": "0.45%", "threshold": "1.0%", "timestamp": None},
            {"id": "ks-2", "name": "Max Drawdown", "description": "Halts if drawdown exceeds configured maximum", "active": False, "value": "1.2%", "threshold": "8.0%", "timestamp": None},
            {"id": "ks-3", "name": "Consecutive Losses", "description": "Pauses trading after consecutive losses", "active": False, "value": "1", "threshold": "5", "timestamp": None},
            {"id": "ks-4", "name": "Beta Win-Rate Floor", "description": "Bayesian posterior mass below floor", "active": False, "value": "0.12", "threshold": "0.95", "timestamp": None},
            {"id": "ks-5", "name": "SPRT Edge Monitor", "description": "Sequential probability ratio test", "active": False, "value": "H1", "threshold": "H0", "timestamp": None},
            {"id": "ks-6", "name": "Drawdown EWMA Sigma", "description": "EWMA control chart signal", "active": False, "value": "0.8σ", "threshold": "2.0σ", "timestamp": None},
            {"id": "ks-7", "name": "KS Drift Detection", "description": "Live-vs-backtest distribution drift", "active": False, "value": "p=0.42", "threshold": "p<0.01", "timestamp": None},
            {"id": "ks-8", "name": "Guardian Heartbeat", "description": "Guardian agent heartbeat timeout", "active": False, "value": "2s", "threshold": "30s", "timestamp": None},
            {"id": "ks-9", "name": "Margin Level", "description": "Margin below warning threshold", "active": False, "value": "450%", "threshold": "200%", "timestamp": None},
            {"id": "ks-10", "name": "Spread Guard", "description": "Spread exceeds max allowed", "active": False, "value": "1.2 pips", "threshold": "3.0 pips", "timestamp": None},
            {"id": "ks-11", "name": "News Blackout", "description": "Trading halted for high-impact news", "active": False, "value": "Clear", "threshold": "15 min", "timestamp": None},
        ],
        "correlationMatrix": {
            "symbols": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"],
            "values": [
                [1.00, 0.72, -0.45, 0.58],
                [0.72, 1.00, -0.38, 0.62],
                [-0.45, -0.38, 1.00, -0.28],
                [0.58, 0.62, -0.28, 1.00],
            ],
        },
        "openPositions": generate_positions(),
    }


def generate_trades(page: int = 1, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
    """Generate mock trade history."""
    symbols = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]
    directions = ["BUY", "SELL"]
    base = (page - 1) * limit
    total = 247

    trades = []
    for i in range(min(limit, total - base)):
        idx = base + i
        symbol = symbols[idx % len(symbols)]
        direction = directions[idx % 2]
        is_winner = (idx % 3) != 1  # 2/3 win rate mock

        opened = datetime.now(timezone.utc) - timedelta(days=idx % 30, hours=idx % 24)
        closed = opened + timedelta(hours=2 + idx % 8)

        if direction == "BUY":
            entry = 1.08000 + idx * 0.0005
            exit_p = entry + (0.0050 if is_winner else -0.0025)
        else:
            entry = 1.09000 - idx * 0.0005
            exit_p = entry - (0.0050 if is_winner else -0.0025)

        pnl = 25.5 if is_winner else -35.2
        pnl_pips = 15.0 if is_winner else -10.0

        trades.append({
            "id": 1000 + idx,
            "ticket": 50000 + idx,
            "symbol": symbol,
            "direction": direction,
            "volume": 0.01 + (idx % 5) * 0.01,
            "entryPrice": round(entry, 5),
            "exitPrice": round(exit_p, 5),
            "stopLoss": round(entry - 0.0025 if direction == "BUY" else entry + 0.0025, 5),
            "takeProfit": round(entry + 0.0050 if direction == "BUY" else entry - 0.0050, 5),
            "pnl": round(pnl, 2),
            "pnlPips": round(pnl_pips, 1),
            "riskReward": 2.0,
            "status": "closed",
            "session": ["London", "NewYork", "Overlap"][idx % 3],
            "confidence": 0.65 + (idx % 20) * 0.01,
            "closeReason": "TP Hit" if is_winner else "SL Hit",
            "openedAt": opened.isoformat(),
            "closedAt": closed.isoformat(),
            "durationSeconds": (closed - opened).total_seconds(),
        })

    return trades, total


def generate_settings() -> dict[str, Any]:
    """Generate mock settings."""
    return {
        "riskPctPerTrade": 0.25,
        "maxConcurrentPositions": 3,
        "maxPerSymbol": 1,
        "dailyLossLimitPct": 1.0,
        "maxSpreadPips": 3.0,
        "minRR": 2.0,
        "slMethod": "atr",
        "confluenceThreshold": 0.70,
        "llmReviewEnabled": False,
        "symbols": [
            {"symbol": "EURUSD", "enabled": True, "maxSpread": 1.5},
            {"symbol": "GBPUSD", "enabled": True, "maxSpread": 2.0},
            {"symbol": "USDJPY", "enabled": True, "maxSpread": 1.5},
            {"symbol": "AUDUSD", "enabled": True, "maxSpread": 2.0},
            {"symbol": "XAUUSD", "enabled": True, "maxSpread": 5.0},
        ],
        "sessions": {
            "sydney": False,
            "tokyo": False,
            "london": True,
            "newYork": True,
            "londonNYOverlap": True,
            "sydneyTime": "00:00-08:00",
            "tokyoTime": "02:00-11:00",
            "londonTime": "11:00-19:00",
            "newYorkTime": "16:00-24:00",
            "overlapTime": "16:00-19:00",
        },
        "brokerConnected": True,
        "brokerAccount": "Demo-420420",
        "brokerServer": "ICMarkets-Demo",
    }


# ── REST Endpoints ──────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    """System health check."""
    return generate_system_health()


@app.get("/api/positions")
async def api_positions():
    """Get open positions."""
    return generate_positions()


@app.get("/api/trades")
async def api_trades(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=500)):
    """Get trade history (paginated)."""
    trades_data, total = generate_trades(page, limit)
    return {
        "trades": trades_data,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@app.get("/api/metrics")
async def api_metrics():
    """Get P&L, win rate, drawdown metrics."""
    return generate_metrics()


@app.get("/api/agents")
async def api_agents():
    """Get agent statuses."""
    return generate_agents()


@app.get("/api/risk")
async def api_risk():
    """Get risk metrics."""
    return generate_risk_metrics()


@app.get("/api/killswitches")
async def api_killswitches():
    """Get kill-switch states."""
    return generate_risk_metrics()["killSwitches"]


@app.get("/api/settings")
async def api_settings():
    """Get current settings."""
    return generate_settings()


# ── WebSocket Endpoint ──────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query("")):
    """Real-time event stream via WebSocket.

    Authentication: provide ?token=DASHBOARD_API_KEY as query parameter.
    """
    # Auth check
    if not SKIP_AUTH and token != DASHBOARD_API_KEY:
        logger.warning("ws_auth_rejected")
        await ws.close(code=4001, reason="Unauthorized: invalid or missing token")
        return

    client_id = await manager.connect(ws)

    # Send initial state
    try:
        await ws.send_json({
            "type": "system_status",
            "data": generate_system_health(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await ws.send_json({
            "type": "agents_update",
            "data": generate_agents(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await ws.send_json({
            "type": "position_update",
            "data": generate_positions(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await ws.send_json({
            "type": "metrics_update",
            "data": generate_metrics(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await ws.send_json({
            "type": "risk_update",
            "data": generate_risk_metrics(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning("ws_initial_state_failed", error=str(e))

    # Keep connection alive and simulate real-time updates
    try:
        pipeline_phases = [
            "data_collection", "macro_analysis", "technical_analysis",
            "sentiment_analysis", "confluence", "thesis_generation",
            "devils_advocate", "cio_decision", "risk_assessment",
            "execution", "management", "learning",
        ]
        phase_idx = 0

        while True:
            # Check for client messages (keep-alive ping/pong)
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
                if data == "ping":
                    await ws.send_text("pong")
            except asyncio.TimeoutError:
                pass

            # Simulate pipeline progress
            phase_idx = (phase_idx + 1) % len(pipeline_phases)
            phase = pipeline_phases[phase_idx]

            await ws.send_json({
                "type": "pipeline_phase",
                "data": {"phase": phase, "active": True},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            # Send updated metrics every few cycles
            if phase_idx % 3 == 0:
                await ws.send_json({
                    "type": "metrics_update",
                    "data": generate_metrics(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            if phase_idx % 5 == 0:
                await ws.send_json({
                    "type": "risk_update",
                    "data": generate_risk_metrics(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            if phase_idx % 7 == 0:
                await ws.send_json({
                    "type": "position_update",
                    "data": generate_positions(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            await asyncio.sleep(2.0)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("ws_error", error=str(e))
    finally:
        await manager.disconnect(client_id)


# ── Static files (production mode) ──────────────────────────────────

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "dist")
if os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA for all non-API routes."""
        file_path = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ── Entrypoint ──────────────────────────────────────────────────────

def main():
    """Run the dashboard server."""
    import uvicorn
    uvicorn.run(
        "noema.dashboard.server.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
