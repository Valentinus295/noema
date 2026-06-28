"""Agent Registry — self-registration pattern for Noema agents.

Replaces the manual imports + instantiation in main.py with a
decorator-based registry. Each agent module registers itself at
import time; the registry instantiates all agents from config.

Usage in agent modules:
    from noema.core.registry import AgentRegistry

    @AgentRegistry.register("macro-economic", layer="data")
    class MacroEconomicAgent(DeterministicAgent):
        ...

Usage in main.py / orchestrator factory:
    from noema.core.registry import AgentRegistry
    agents = AgentRegistry.create_all(config)
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable, Type

import structlog

logger = structlog.get_logger(__name__)


class AgentRegistry:
    """Central registry for Noema agents.

    Agents register via the ``@AgentRegistry.register(name, layer)`` decorator.
    At startup, ``create_all(config)`` instantiates every registered agent and
    returns them grouped by layer for the orchestrator.
    """

    # name → {cls, layer, kwargs}
    _registry: dict[str, dict[str, Any]] = {}

    # Canonical layer ordering matching the wave pipeline
    LAYERS = ("data", "analysis", "decision", "execution", "learning")

    @classmethod
    def register(
        cls,
        name: str,
        layer: str = "analysis",
        needs_nim: bool = False,
        needs_broker: bool = False,
        **extra_kwargs: Any,
    ) -> Callable[[Type], Type]:
        """Decorator to register an agent class.

        Args:
            name: Canonical agent name (e.g. "macro-economic", "trade-thesis").
            layer: Pipeline layer — one of "data", "analysis", "decision",
                   "execution", "learning".
            needs_nim: If True, ``create_all`` passes ``nim_client`` to the ctor.
            needs_broker: If True, ``create_all`` passes ``broker`` to the ctor.
            **extra_kwargs: Additional keyword arguments forwarded to the ctor.
        """
        def decorator(agent_cls: Type) -> Type:
            if name in cls._registry:
                logger.warning(
                    "agent_registry_overwrite",
                    name=name,
                    old_cls=cls._registry[name]["cls"].__name__,
                    new_cls=agent_cls.__name__,
                )
            cls._registry[name] = {
                "cls": agent_cls,
                "layer": layer,
                "needs_nim": needs_nim,
                "needs_broker": needs_broker,
                "extra_kwargs": extra_kwargs,
            }
            return agent_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> Type | None:
        """Get a registered agent class by name."""
        entry = cls._registry.get(name)
        return entry["cls"] if entry else None

    @classmethod
    def get_entry(cls, name: str) -> dict[str, Any] | None:
        """Get the full registry entry for an agent name."""
        return cls._registry.get(name)

    @classmethod
    def list_agents(cls, layer: str | None = None) -> list[str]:
        """List registered agent names, optionally filtered by layer."""
        if layer is None:
            return list(cls._registry.keys())
        return [n for n, e in cls._registry.items() if e["layer"] == layer]

    @classmethod
    def create_all(
        cls,
        config: Any,
        nim_client: Any = None,
        broker: Any = None,
    ) -> dict[str, dict[str, Any]]:
        """Instantiate all registered agents and return them grouped by layer.

        Returns:
            {
                "data": [agent, ...],
                "analysis": [agent, ...],
                "decision": {"thesis": agent, "devil": agent, "cio": agent},
                "execution": {"risk": agent, "execution": agent},
                "learning": [agent, ...],
            }
        """
        result: dict[str, Any] = {layer: [] for layer in cls.LAYERS}
        # decision and execution are dicts, not lists
        result["decision"] = {}
        result["execution"] = {}

        for name, entry in sorted(cls._registry.items(), key=lambda x: x[0]):
            agent_cls = entry["cls"]
            layer = entry["layer"]
            kwargs: dict[str, Any] = {"config": config}
            if entry["needs_nim"] and nim_client:
                kwargs["nim_client"] = nim_client
            if entry["needs_broker"] and broker:
                kwargs["broker"] = broker
            kwargs.update(entry.get("extra_kwargs", {}))

            try:
                agent = agent_cls(**kwargs)
            except Exception as exc:
                logger.error(
                    "agent_registry_create_failed",
                    name=name,
                    cls=agent_cls.__name__,
                    error=str(exc),
                )
                continue

            logger.debug("agent_registry_created", name=name, layer=layer)

            # Place into the right bucket
            if layer == "decision":
                # decision agents keyed by role
                role = getattr(agent, "role", name).lower()
                if "thesis" in role or "thesis" in name:
                    result["decision"]["thesis"] = agent
                elif "devil" in role or "advocate" in name:
                    result["decision"]["devil"] = agent
                elif "cio" in role or "cio" in name:
                    result["decision"]["cio"] = agent
                else:
                    result["decision"][name] = agent
            elif layer == "execution":
                role = getattr(agent, "role", name).lower()
                if "risk" in role or "risk" in name:
                    result["execution"]["risk"] = agent
                elif "execution" in role or "exec" in name:
                    result["execution"]["execution"] = agent
                else:
                    result["execution"][name] = agent
            else:
                result[layer].append(agent)

        return result

    @classmethod
    def discover_agents(cls, package_name: str = "noema.agents") -> None:
        """Auto-discover and import all agent modules in a package.

        This triggers the ``@AgentRegistry.register`` decorators in each
        module. Call once at startup before ``create_all``.
        """
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            logger.warning("agent_registry_discover_failed", package=package_name)
            return

        if not hasattr(package, "__path__"):
            return

        for importer, modname, ispkg in pkgutil.walk_packages(
            path=package.__path__,
            prefix=package.__name__ + ".",
        ):
            try:
                importlib.import_module(modname)
            except Exception as exc:
                logger.debug(
                    "agent_registry_import_skip",
                    module=modname,
                    error=str(exc),
                )

    @classmethod
    def reset(cls) -> None:
        """Clear the registry (useful for testing)."""
        cls._registry.clear()
