"""
JAMES Skill Object Model

Self-modifying skill system with governance:
  - CRUD operations (create, read, update, archive)
  - JSON serialization to persistent store
  - Confidence scoring based on execution outcomes
  - Method ranking by historical success rate
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class Skill:
    """
    A reusable, self-improving execution skill.

    Skills are learned from successful task executions and
    refined over time based on performance metrics.
    """
    id: str
    name: str = ""
    description: str = ""
    methods: list[str] = field(default_factory=lambda: ["CLI"])
    steps: list[dict] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)  # Stored as descriptions
    postconditions: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    confidence_score: float = 0.5
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    execution_count: int = 0
    success_count: int = 0
    total_duration_ms: float = 0.0
    optimization_log: list[dict] = field(default_factory=list)

    # ── Confidence & Performance ─────────────────────────────────

    def record_execution(self, success: bool, duration_ms: float = 0.0) -> None:
        """Record an execution outcome and update confidence score."""
        self.execution_count += 1
        self.total_duration_ms += duration_ms
        if success:
            self.success_count += 1
        self.updated_at = time.time()
        self._recalculate_confidence()

    def _recalculate_confidence(self) -> None:
        """
        Recalculate confidence score using Bayesian-ish smoothing.
        Starts at 0.5 (uncertain), converges to actual success rate.
        Uses Laplace smoothing: (successes + 1) / (total + 2)
        """
        self.confidence_score = (self.success_count + 1) / (self.execution_count + 2)

    @property
    def success_rate(self) -> float:
        """Raw success rate (0.0 - 1.0)."""
        if self.execution_count == 0:
            return 0.0
        return self.success_count / self.execution_count

    @property
    def avg_duration_ms(self) -> float:
        """Average execution duration in milliseconds."""
        if self.execution_count == 0:
            return 0.0
        return self.total_duration_ms / self.execution_count

    @property
    def preferred_method(self) -> str:
        """Get the first (highest priority) method."""
        return self.methods[0] if self.methods else "CLI"

    # ── Optimization Log ─────────────────────────────────────────

    def log_optimization(self, description: str, improvement: float) -> None:
        """Record an optimization event."""
        self.optimization_log.append({
            "timestamp": time.time(),
            "description": description,
            "improvement": improvement,
        })
        self.updated_at = time.time()

    # ── Serialization ────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize skill to dict."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "methods": self.methods,
            "steps": self.steps,
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "failure_modes": self.failure_modes,
            "confidence_score": round(self.confidence_score, 4),
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "optimization_log": self.optimization_log,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "Skill":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            methods=data.get("methods", ["CLI"]),
            steps=data.get("steps", []),
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            failure_modes=data.get("failure_modes", []),
            confidence_score=data.get("confidence_score", 0.5),
            tags=data.get("tags", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            execution_count=data.get("execution_count", 0),
            success_count=data.get("success_count", 0),
            total_duration_ms=data.get("total_duration_ms", 0.0),
            optimization_log=data.get("optimization_log", []),
        )

    def __repr__(self) -> str:
        return (
            f"<Skill '{self.id}' conf={self.confidence_score:.2f} "
            f"runs={self.execution_count} rate={self.success_rate:.0%}>"
        )


class SkillStore:
    """
    Persistent JSON-file-based skill store.
    Each skill is stored as a separate JSON file for easy inspection.
    """

    def __init__(self, store_dir: str):
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Skill] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all skills from disk into cache."""
        self._cache.clear()
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                skill = Skill.from_dict(data)
                self._cache[skill.id] = skill
            except Exception:
                continue

    def _save_skill(self, skill: Skill) -> None:
        """Persist a single skill to disk."""
        safe_id = skill.id.replace("/", "_").replace("\\", "_")
        path = self._dir / f"{safe_id}.json"
        path.write_text(skill.to_json(), encoding="utf-8")

    # ── CRUD ─────────────────────────────────────────────────────

    def create(self, skill: Skill) -> Skill:
        """Create or overwrite a skill."""
        self._cache[skill.id] = skill
        self._save_skill(skill)
        return skill

    def get(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by ID."""
        return self._cache.get(skill_id)

    def update(self, skill: Skill) -> Skill:
        """Update an existing skill."""
        skill.updated_at = time.time()
        self._cache[skill.id] = skill
        self._save_skill(skill)
        return skill

    def delete(self, skill_id: str) -> bool:
        """Delete a skill."""
        if skill_id in self._cache:
            del self._cache[skill_id]
            safe_id = skill_id.replace("/", "_").replace("\\", "_")
            path = self._dir / f"{safe_id}.json"
            if path.exists():
                path.unlink()
            return True
        return False

    def list_all(self) -> list[Skill]:
        """List all skills, sorted by confidence score (descending)."""
        return sorted(self._cache.values(), key=lambda s: s.confidence_score, reverse=True)

    def search(self, query: str) -> list[Skill]:
        """Search skills by name, description, or tags."""
        query_lower = query.lower()
        results = []
        for skill in self._cache.values():
            if (
                query_lower in skill.name.lower()
                or query_lower in skill.description.lower()
                or any(query_lower in tag.lower() for tag in skill.tags)
            ):
                results.append(skill)
        return sorted(results, key=lambda s: s.confidence_score, reverse=True)

    def find_by_method(self, method: str) -> list[Skill]:
        """Find skills that support a specific method."""
        return [s for s in self._cache.values() if method in s.methods]

    @property
    def count(self) -> int:
        return len(self._cache)

    def __repr__(self) -> str:
        return f"<SkillStore dir='{self._dir}' skills={self.count}>"
