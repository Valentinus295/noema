"""Knowledge base model — stores learned patterns from trading history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class KnowledgeBase:
    """Persistent knowledge base that learns from trade outcomes.

    Stores which setups, sessions, and patterns work best.
    """

    def __init__(self, path: str = "vmpm_knowledge.json") -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = self._load()

    def record_trade(self, trade: dict[str, Any]) -> None:
        """Record a completed trade outcome."""
        self.data.setdefault("trades", []).append(trade)
        self._save()

    def get_best_sessions(self) -> dict[str, float]:
        """Return session win rates."""
        sessions: dict[str, dict[str, int]] = {}
        for t in self.data.get("trades", []):
            s = t.get("session", "unknown")
            sessions.setdefault(s, {"wins": 0, "total": 0})
            sessions[s]["total"] += 1
            if t.get("outcome") == "win":
                sessions[s]["wins"] += 1
        return {s: v["wins"] / v["total"] for s, v in sessions.items() if v["total"] > 0}

    def get_best_patterns(self) -> dict[str, float]:
        """Return candlestick pattern win rates."""
        patterns: dict[str, dict[str, int]] = {}
        for t in self.data.get("trades", []):
            p = t.get("candlestick_pattern", "none")
            patterns.setdefault(p, {"wins": 0, "total": 0})
            patterns[p]["total"] += 1
            if t.get("outcome") == "win":
                patterns[p]["wins"] += 1
        return {p: v["wins"] / v["total"] for p, v in patterns.items() if v["total"] > 0}

    def get_total_trades(self) -> int:
        return len(self.data.get("trades", []))

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return {"trades": []}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, indent=2))
        except Exception as exc:
            logger.error("knowledge_save_failed", error=str(exc))
