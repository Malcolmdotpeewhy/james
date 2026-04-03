"""
JAMES Hierarchical Memory System

SQLite-backed memory with three tiers:
  - Short-term: Active task state (in-memory, flushed on completion)
  - Long-term:  Skills catalog, system map, performance metrics
  - Meta:       Optimization history — which improvements worked
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ExecutionMetric:
    """Encapsulates an execution metric for recording."""
    node_id: str
    success: bool
    duration_ms: float
    node_name: str = ""
    layer: Optional[int] = None
    error: Optional[str] = None


class MemoryStore:
    """
    Hierarchical memory system using SQLite for persistence
    and in-memory dicts for short-term state.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._short_term: dict[str, Any] = {}
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema with auto-migration."""
        with self._connect() as conn:
            conn.executescript("""
                -- Long-term: Key-value store for system knowledge
                CREATE TABLE IF NOT EXISTS long_term (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                -- Metrics: Performance tracking
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL,
                    node_name TEXT DEFAULT '',
                    layer INTEGER,
                    success INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    error TEXT,
                    timestamp REAL NOT NULL
                );

                -- Meta-memory: Optimization history
                CREATE TABLE IF NOT EXISTS meta (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL,
                    optimization TEXT NOT NULL,
                    before_score REAL,
                    after_score REAL,
                    improvement REAL,
                    timestamp REAL NOT NULL
                );

                -- System map: Installed tools, paths, capabilities
                CREATE TABLE IF NOT EXISTS system_map (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT DEFAULT 'tool',
                    verified_at REAL
                );

                -- Indexes for common queries
                -- ⚡ Bolt: Kept composite index for node-specific queries, but restored standalone
                -- timestamp index to optimize get_metrics() when fetching all recent metrics
                -- without a node_id filter. Eliminates O(N log N) Temp B-Tree sorts.
                CREATE INDEX IF NOT EXISTS idx_metrics_node_ts ON metrics(node_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_meta_skill_ts ON meta(skill_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_meta_ts ON meta(timestamp);
                CREATE INDEX IF NOT EXISTS idx_lt_category_updated ON long_term(category, updated_at);
                CREATE INDEX IF NOT EXISTS idx_lt_updated ON long_term(updated_at);
                CREATE INDEX IF NOT EXISTS idx_meta_improvement ON meta(improvement);
                CREATE INDEX IF NOT EXISTS idx_system_map_category_key ON system_map(category, key);
            """)

    def _connect(self) -> sqlite3.Connection:
        """Create a thread-safe SQLite connection."""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ── Short-Term Memory ────────────────────────────────────────

    def st_set(self, key: str, value: Any) -> None:
        """Set a short-term memory value (in-memory only)."""
        self._short_term[key] = value

    def st_get(self, key: str, default: Any = None) -> Any:
        """Get a short-term memory value."""
        return self._short_term.get(key, default)

    def st_delete(self, key: str) -> None:
        """Delete a short-term memory value."""
        self._short_term.pop(key, None)

    def st_clear(self) -> None:
        """Clear all short-term memory."""
        self._short_term.clear()

    def st_dump(self) -> dict:
        """Dump all short-term memory."""
        return dict(self._short_term)

    # ── Long-Term Memory ─────────────────────────────────────────

    def lt_set(self, key: str, value: Any, category: str = "general") -> None:
        """Store a long-term memory value (persisted to SQLite)."""
        now = time.time()
        serialized = json.dumps(value, default=str)
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO long_term (key, value, category, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     value=excluded.value,
                     category=excluded.category,
                     updated_at=excluded.updated_at""",
                (key, serialized, category, now, now),
            )

    def lt_get(self, key: str) -> Optional[Any]:
        """Retrieve a long-term memory value."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM long_term WHERE key = ?", (key,)
            ).fetchone()
            if row:
                return json.loads(row["value"])
            return None

    def lt_list(self, category: Optional[str] = None, limit: int = 100) -> list[dict]:
        """List long-term memory entries."""
        with self._lock, self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT key, value, category, updated_at FROM long_term "
                    "WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, value, category, updated_at FROM long_term "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "key": r["key"],
                    "value": json.loads(r["value"]),
                    "category": r["category"],
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ]

    def lt_delete(self, key: str) -> bool:
        """Delete a long-term memory entry."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM long_term WHERE key = ?", (key,))
            return cursor.rowcount > 0

    # ── Metrics Recording ────────────────────────────────────────

    def record_metric(self, metric: ExecutionMetric) -> None:
        """Record an execution metric."""
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO metrics
                   (node_id, node_name, layer, success, duration_ms, error, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    metric.node_id,
                    metric.node_name,
                    metric.layer,
                    int(metric.success),
                    metric.duration_ms,
                    metric.error,
                    time.time(),
                ),
            )

    def get_metrics(
        self,
        node_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve execution metrics."""
        with self._lock, self._connect() as conn:
            if node_id:
                rows = conn.execute(
                    "SELECT * FROM metrics WHERE node_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (node_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM metrics ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_success_rate(self, node_id: str) -> float:
        """Get success rate for a specific node."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as total, SUM(success) as successes "
                "FROM metrics WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            if row and row["total"] > 0:
                return row["successes"] / row["total"]
            return 0.0

    def get_avg_duration(self, node_id: str) -> float:
        """Get average execution duration for a node."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT AVG(duration_ms) as avg_ms FROM metrics WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            return row["avg_ms"] or 0.0

    # ── Meta-Memory ──────────────────────────────────────────────

    def record_optimization(
        self,
        skill_id: str,
        optimization: str,
        before_score: float,
        after_score: float,
    ) -> None:
        """Record an optimization event in meta-memory."""
        improvement = after_score - before_score
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO meta
                   (skill_id, optimization, before_score, after_score, improvement, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (skill_id, optimization, before_score, after_score, improvement, time.time()),
            )

    def get_optimization_history(
        self,
        skill_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get optimization history from meta-memory."""
        with self._lock, self._connect() as conn:
            if skill_id:
                rows = conn.execute(
                    "SELECT * FROM meta WHERE skill_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (skill_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM meta ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_best_optimizations(self, limit: int = 10) -> list[dict]:
        """Get the most effective optimizations historically."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM meta WHERE improvement > 0 ORDER BY improvement DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── System Map ───────────────────────────────────────────────

    def map_set(self, key: str, value: str, category: str = "tool") -> None:
        """Store a system map entry (tool paths, capabilities)."""
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO system_map (key, value, category, verified_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     value=excluded.value,
                     category=excluded.category,
                     verified_at=excluded.verified_at""",
                (key, value, category, time.time()),
            )

    def map_get(self, key: str) -> Optional[str]:
        """Retrieve a system map entry."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM system_map WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def map_list(self, category: Optional[str] = None) -> list[dict]:
        """List system map entries."""
        with self._lock, self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM system_map WHERE category = ? ORDER BY key",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM system_map ORDER BY key"
                ).fetchall()
            return [dict(r) for r in rows]

    # ── Stats ────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get overall memory system statistics."""
        with self._lock, self._connect() as conn:
            lt_count = conn.execute("SELECT COUNT(*) as c FROM long_term").fetchone()["c"]
            metric_count = conn.execute("SELECT COUNT(*) as c FROM metrics").fetchone()["c"]
            meta_count = conn.execute("SELECT COUNT(*) as c FROM meta").fetchone()["c"]
            map_count = conn.execute("SELECT COUNT(*) as c FROM system_map").fetchone()["c"]

            return {
                "short_term_entries": len(self._short_term),
                "long_term_entries": lt_count,
                "metrics_recorded": metric_count,
                "optimizations_logged": meta_count,
                "system_map_entries": map_count,
                "db_path": self._db_path,
            }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"<MemoryStore lt={stats['long_term_entries']} "
            f"metrics={stats['metrics_recorded']} "
            f"meta={stats['optimizations_logged']}>"
        )
