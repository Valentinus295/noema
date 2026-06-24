"""Procedural Memory — YAML rule store for learned execution patterns.

Stores trading "muscle memory": concrete, executable rules that the system
has learned from experience. Unlike semantic memory (similarity-based),
procedural memory holds if/then action rules.

Rules are:
- Conditional: "IF {conditions} THEN {action}"
- Scored: Each rule has a confidence score based on historical performance
- Versioned: Rules track when they were created and last reinforced
- Mutable: Rules can be updated, deprecated, or superseded
- Persisted: Stored as YAML for audit trail and human review
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger(__name__)


@dataclass
class ProceduralRule:
    """A learned trading execution rule.

    Encodes: IF conditions are met → take action with confidence.
    """
    rule_id: str
    name: str
    conditions: dict[str, Any]  # e.g. {"trend": "bullish", "rsi": {"lt": 30}}
    action: str  # "BUY", "SELL", "WAIT", "REDUCE_SIZE", "WIDEN_SL", "TIGHTEN_TP"
    confidence: float = 0.5  # 0.0 - 1.0, based on historical outcomes
    priority: int = 0  # Higher = evaluated first
    category: str = "general"  # "entry", "exit", "risk", "filter", "timing"
    total_applications: int = 0
    successful_applications: int = 0
    created_at: str = ""
    last_applied: str = ""
    last_reinforced: str = ""
    source_pattern_ids: list[str] = field(default_factory=list)  # Linked semantic patterns
    superseded_by: str | None = None  # Rule ID of newer rule that replaces this
    version: int = 1
    notes: str = ""

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.last_reinforced:
            self.last_reinforced = now

    @property
    def success_rate(self) -> float:
        if self.total_applications == 0:
            return self.confidence  # Use prior confidence
        return self.successful_applications / self.total_applications

    @property
    def is_active(self) -> bool:
        """Rule is active if not superseded and confidence > 0."""
        return self.superseded_by is None and self.confidence > 0

    def record_application(self, success: bool) -> None:
        """Record whether the rule application led to success."""
        self.total_applications += 1
        if success:
            self.successful_applications += 1
            self.confidence = min(self.confidence * 1.05, 1.0)
        else:
            self.confidence = max(self.confidence * 0.90, 0.05)
        self.last_applied = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "conditions": self.conditions,
            "action": self.action,
            "confidence": round(self.confidence, 4),
            "priority": self.priority,
            "category": self.category,
            "total_applications": self.total_applications,
            "successful_applications": self.successful_applications,
            "success_rate": round(self.success_rate, 4),
            "created_at": self.created_at,
            "last_applied": self.last_applied,
            "last_reinforced": self.last_reinforced,
            "source_pattern_ids": self.source_pattern_ids,
            "superseded_by": self.superseded_by,
            "version": self.version,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProceduralRule:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ProceduralMemory:
    """YAML-backed procedural rule store.

    Stores learned execution patterns as conditional rules.
    Rules persist to disk for audit trail and human review.
    Supports rule creation, evaluation, reinforcement, and superseding.
    """

    DEFAULT_RULESET = "default"
    MAX_RULES = 500
    MIN_CONFIDENCE_FOR_APPLICATION = 0.3

    def __init__(self, rules_dir: str | Path = ""):
        self._rules_dir = Path(rules_dir) if rules_dir else Path("noema_rules")
        self._rules_dir.mkdir(parents=True, exist_ok=True)
        self._rules: dict[str, ProceduralRule] = {}
        self._rules_by_category: dict[str, list[str]] = {}

    async def initialize(self) -> None:
        """Load all rules from YAML files."""
        loaded = 0
        for yaml_file in self._rules_dir.glob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                for rule_data in data.get("rules", []):
                    rule = ProceduralRule.from_dict(rule_data)
                    self._rules[rule.rule_id] = rule
                    self._rules_by_category.setdefault(rule.category, []).append(rule.rule_id)
                    loaded += 1
            except Exception as e:
                logger.warning("procedural_load_failed", file=str(yaml_file), error=str(e))

        logger.info("procedural_memory_loaded", rules_loaded=loaded, categories=list(self._rules_by_category.keys()))

    def create_rule(
        self,
        name: str,
        conditions: dict[str, Any],
        action: str,
        category: str = "general",
        confidence: float = 0.5,
        priority: int = 0,
        source_pattern_ids: list[str] | None = None,
        notes: str = "",
    ) -> ProceduralRule:
        """Create a new procedural rule.

        Args:
            name: Human-readable name (e.g. "RSI oversold in uptrend → BUY")
            conditions: Dict of conditions, e.g. {"trend": "bullish", "rsi": {"lt": 30}}
            action: What to do ("BUY", "SELL", "WAIT", "REDUCE_SIZE", etc.)
            category: Rule category ("entry", "exit", "risk", "filter", "timing")
            confidence: Initial confidence (0.0 - 1.0)
            priority: Higher = evaluated first
            source_pattern_ids: Linked semantic patterns that produced this rule
            notes: Human-readable explanation

        Returns:
            The created ProceduralRule
        """
        rule_id = f"{category}_{name.lower().replace(' ', '_')[:50]}_{int(time.time())}"

        rule = ProceduralRule(
            rule_id=rule_id,
            name=name,
            conditions=conditions,
            action=action,
            confidence=confidence,
            priority=priority,
            category=category,
            source_pattern_ids=source_pattern_ids or [],
            notes=notes,
        )

        self._rules[rule_id] = rule
        self._rules_by_category.setdefault(category, []).append(rule_id)

        logger.info(
            "procedural_rule_created",
            rule_id=rule_id,
            name=name,
            category=category,
            confidence=f"{confidence:.2f}",
        )

        # Auto-save the ruleset
        self._save_ruleset()

        return rule

    def get_rules(
        self,
        category: str | None = None,
        min_confidence: float = MIN_CONFIDENCE_FOR_APPLICATION,
        only_active: bool = True,
    ) -> list[ProceduralRule]:
        """Get rules matching criteria.

        Args:
            category: Filter by category (None = all)
            min_confidence: Minimum confidence threshold
            only_active: Exclude superseded/deprecated rules

        Returns:
            List of ProceduralRules sorted by priority desc, confidence desc
        """
        if category:
            rule_ids = self._rules_by_category.get(category, [])
            candidates = [self._rules[rid] for rid in rule_ids if rid in self._rules]
        else:
            candidates = list(self._rules.values())

        result = [
            r for r in candidates
            if r.confidence >= min_confidence
            and (not only_active or r.is_active)
        ]
        result.sort(key=lambda r: (-r.priority, -r.confidence))
        return result

    def evaluate_rules(
        self, context: dict[str, Any], category: str | None = None
    ) -> list[tuple[ProceduralRule, bool]]:
        """Evaluate all active rules against a market context.

        Returns list of (rule, matched) tuples for all evaluated rules.
        """
        candidates = self.get_rules(category=category, only_active=True)
        results: list[tuple[ProceduralRule, bool]] = []

        for rule in candidates:
            matched = self._check_conditions(rule.conditions, context)
            results.append((rule, matched))

        return results

    def get_matching_rules(
        self, context: dict[str, Any], category: str | None = None
    ) -> list[ProceduralRule]:
        """Get only rules that match the given context."""
        evaluated = self.evaluate_rules(context, category=category)
        return [rule for rule, matched in evaluated if matched]

    def get_best_action(
        self, context: dict[str, Any], category: str = "entry"
    ) -> tuple[str | None, float]:
        """Get the highest-confidence matching action.

        Returns (action, confidence) or (None, 0.0) if no match.
        """
        matches = self.get_matching_rules(context, category=category)
        if not matches:
            return None, 0.0

        best = max(matches, key=lambda r: (r.confidence, r.priority))
        return best.action, best.confidence

    def reinforce_rule(self, rule_id: str, success: bool) -> None:
        """Reinforce a rule based on a trade outcome.

        Successful application → increase confidence.
        Failed application → decrease confidence (with decay floor).
        """
        rule = self._rules.get(rule_id)
        if rule is None:
            logger.warning("procedural_reinforce_not_found", rule_id=rule_id)
            return

        rule.record_application(success)
        rule.last_reinforced = datetime.now(timezone.utc).isoformat()

        if rule.confidence < 0.1:
            logger.info(
                "procedural_rule_deprecated_low_confidence",
                rule_id=rule_id,
                confidence=f"{rule.confidence:.4f}",
            )

        logger.debug(
            "procedural_rule_reinforced",
            rule_id=rule_id,
            success=success,
            confidence=f"{rule.confidence:.4f}",
            success_rate=f"{rule.success_rate:.4f}",
        )

    def supersede_rule(self, old_rule_id: str, new_rule_id: str) -> None:
        """Mark an old rule as superseded by a newer one."""
        old = self._rules.get(old_rule_id)
        new = self._rules.get(new_rule_id)
        if old and new:
            old.superseded_by = new_rule_id
            logger.info(
                "procedural_rule_superseded",
                old=old_rule_id,
                new=new_rule_id,
            )
            self._save_ruleset()

    def deprecate_rule(self, rule_id: str, reason: str = "") -> None:
        """Manually deprecate a rule (set confidence to 0)."""
        rule = self._rules.get(rule_id)
        if rule:
            rule.confidence = 0.0
            rule.notes += f" | Deprecated: {reason}"
            logger.info("procedural_rule_deprecated", rule_id=rule_id, reason=reason)
            self._save_ruleset()

    def _check_conditions(self, conditions: dict, context: dict) -> bool:
        """Evaluate rule conditions against a context dict.

        Supports:
        - Equality: {"key": "value"}
        - Comparison: {"key": {"gt": 0.5, "lt": 2.0, "gte": 0, "lte": 1.0}}
        - List membership: {"key": {"in": ["a", "b"]}}
        - AND across all top-level keys
        """
        for key, expected in conditions.items():
            actual = context.get(key)
            if actual is None:
                return False

            if isinstance(expected, dict):
                # Comparison operators
                for op, val in expected.items():
                    if op == "gt" and not (actual > val):
                        return False
                    elif op == "gte" and not (actual >= val):
                        return False
                    elif op == "lt" and not (actual < val):
                        return False
                    elif op == "lte" and not (actual <= val):
                        return False
                    elif op == "eq" and not (actual == val):
                        return False
                    elif op == "neq" and actual == val:
                        return False
                    elif op == "in" and actual not in val:
                        return False
                    elif op == "not_in" and actual in val:
                        return False
            else:
                # Direct equality match
                if actual != expected:
                    return False

        return True

    def _save_ruleset(self) -> None:
        """Persist all rules to the default ruleset YAML file."""
        rules_list = [r.to_dict() for r in self._rules.values()]
        rules_by_category: dict[str, list[dict]] = {}
        for rule_dict in rules_list:
            cat = rule_dict["category"]
            rules_by_category.setdefault(cat, []).append(rule_dict)

        output = {
            "metadata": {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "total_rules": len(rules_list),
                "categories": list(rules_by_category.keys()),
            },
            "rules": rules_list,
        }

        rules_file = self._rules_dir / f"{self.DEFAULT_RULESET}.yaml"
        with open(rules_file, "w") as f:
            yaml.safe_dump(output, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    @property
    def stats(self) -> dict[str, Any]:
        active = [r for r in self._rules.values() if r.is_active]
        return {
            "total_rules": len(self._rules),
            "active_rules": len(active),
            "superseded_rules": len([r for r in self._rules.values() if r.superseded_by]),
            "by_category": {
                cat: len(ids)
                for cat, ids in self._rules_by_category.items()
            },
            "avg_confidence": round(
                sum(r.confidence for r in active) / max(len(active), 1), 4
            ),
            "rules_dir": str(self._rules_dir),
        }

    def clear(self) -> None:
        """Clear all rules (for testing)."""
        self._rules.clear()
        self._rules_by_category.clear()
