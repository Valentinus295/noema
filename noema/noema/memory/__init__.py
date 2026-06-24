"""Noema Memory Architecture — Phase 4: Self-Learning & Memory Systems.

Four memory stores inspired by human cognitive architecture:
- Episodic: PostgreSQL trade log (what happened)
- Semantic: Vector similarity for pattern matching (what things mean)
- Working: Redis-backed live state (what's happening now)
- Procedural: YAML rule store for learned execution patterns (how to act)

The MemoryManager façade unifies all four stores with a single API.
"""

from noema.memory.episodic import EpisodicMemory
from noema.memory.semantic import SemanticMemory
from noema.memory.working import WorkingMemory
from noema.memory.procedural import ProceduralMemory
from noema.memory.manager import MemoryManager

__all__ = [
    "EpisodicMemory",
    "SemanticMemory",
    "WorkingMemory",
    "ProceduralMemory",
    "MemoryManager",
]
