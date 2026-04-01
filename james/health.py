"""
JAMES Health Monitor — Self-monitoring system health metrics.

Collects real-time metrics about:
  - CPU/memory usage
  - LLM response latency
  - Tool execution success rate
  - Error frequency and patterns
  - Subsystem availability

Exposes a rolling window of metrics for dashboard display.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Optional

logger = logging.getLogger("james.health")


class HealthMetric:
    """A single timestamped health metric."""
    __slots__ = ("name", "value", "unit", "timestamp")

    def __init__(self, name: str, value: float, unit: str = ""):
        self.name = name
        self.value = value
        self.unit = unit
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp,
        }


class HealthMonitor:
    """
    Collect and serve system health metrics.

    Maintains a rolling window of metrics with configurable
    retention period. Thread-safe for concurrent access.
    """

    MAX_HISTORY = 500  # per metric name
    COLLECTION_INTERVAL = 10.0  # seconds

    def __init__(self, orchestrator=None):
        self.orch = orchestrator
        self._metrics: dict[str, deque] = {}
        self._counters: dict[str, int] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._start_time = time.time()

        # Cumulative counters
        self._total_requests = 0
        self._total_errors = 0
        self._total_tool_calls = 0
        self._total_ai_calls = 0

    # ── Metric Recording ─────────────────────────────────────────

    def record(self, name: str, value: float, unit: str = "") -> None:
        """Record a metric value."""
        metric = HealthMetric(name, value, unit)
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = deque(maxlen=self.MAX_HISTORY)
            self._metrics[name].append(metric)

    def increment(self, counter: str, amount: int = 1) -> None:
        """Increment a named counter."""
        with self._lock:
            self._counters[counter] = self._counters.get(counter, 0) + amount

    def record_request(self) -> None:
        """Record an incoming request."""
        self._total_requests += 1

    def record_error(self) -> None:
        """Record an error."""
        self._total_errors += 1

    def record_tool_call(self, tool_name: str, duration_ms: float,
                         success: bool) -> None:
        """Record a tool execution."""
        self._total_tool_calls += 1
        self.record(f"tool.{tool_name}.duration", duration_ms, "ms")
        self.record(f"tool.{tool_name}.success", 1.0 if success else 0.0)
        if not success:
            self.increment("tool_errors")

    def record_ai_call(self, model: str, duration_ms: float) -> None:
        """Record an AI inference call."""
        self._total_ai_calls += 1
        self.record(f"ai.{model}.latency", duration_ms, "ms")

    # ── Metric Retrieval ─────────────────────────────────────────

    def get_metric(self, name: str, limit: int = 50) -> list[dict]:
        """Get recent values for a metric."""
        with self._lock:
            if name not in self._metrics:
                return []
            items = list(self._metrics[name])[-limit:]
        return [m.to_dict() for m in items]

    def get_all_metrics(self) -> dict[str, list[dict]]:
        """Get latest value for all metrics."""
        with self._lock:
            result = {}
            for name, q in self._metrics.items():
                if q:
                    result[name] = q[-1].to_dict()
        return result

    # ── System Health Snapshot ───────────────────────────────────

    def snapshot(self) -> dict:
        """
        Get a full system health snapshot.

        Includes CPU, memory, uptime, error rates, and subsystem status.
        """
        uptime = time.time() - self._start_time

        # Process-level metrics
        process_info = self._get_process_info()

        # Subsystem health
        subsystems = self._check_subsystems()

        # Error rate (errors per minute over uptime)
        uptime_minutes = max(1, uptime / 60)
        error_rate = self._total_errors / uptime_minutes

        return {
            "status": "healthy" if error_rate < 10 else "degraded",
            "uptime_seconds": round(uptime),
            "uptime_human": self._format_uptime(uptime),
            "process": process_info,
            "counters": {
                "total_requests": self._total_requests,
                "total_errors": self._total_errors,
                "total_tool_calls": self._total_tool_calls,
                "total_ai_calls": self._total_ai_calls,
                "error_rate_per_min": round(error_rate, 2),
            },
            "subsystems": subsystems,
            "custom_counters": dict(self._counters),
        }

    def _get_process_info(self) -> dict:
        """Get current process resource usage."""
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mem = proc.memory_info()
            return {
                "pid": os.getpid(),
                "cpu_percent": proc.cpu_percent(interval=0),
                "memory_mb": round(mem.rss / (1024 * 1024)),
                "threads": proc.num_threads(),
            }
        except ImportError:
            # psutil not available — use basic info
            pass
        except Exception:
            pass

        return {
            "pid": os.getpid(),
            "cpu_percent": -1,
            "memory_mb": -1,
            "threads": threading.active_count(),
        }

    def _check_subsystems(self) -> dict:
        """Check health of all subsystems."""
        checks = {}

        if self.orch:
            try:
                checks["memory"] = "ok"
                _ = self.orch.memory.lt_list(limit=1)
            except Exception:
                checks["memory"] = "error"

            try:
                checks["scheduler"] = "ok" if self.orch.scheduler._running else "stopped"
            except Exception:
                checks["scheduler"] = "unknown"

            try:
                checks["vectors"] = "ok" if self.orch.vectors else "missing"
            except Exception:
                checks["vectors"] = "error"

            try:
                checks["rag"] = "ok" if self.orch.rag else "missing"
            except Exception:
                checks["rag"] = "error"

            try:
                checks["watcher"] = "running" if self.orch.watcher.is_running else "idle"
            except Exception:
                checks["watcher"] = "unknown"

            try:
                from james.ai import local_llm
                checks["local_llm"] = "ok" if local_llm._is_server_running() else "offline"
            except Exception:
                checks["local_llm"] = "error"

        return checks

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """Format seconds into human-readable uptime."""
        hours, rem = divmod(int(seconds), 3600)
        minutes, secs = divmod(rem, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    # ── Background Collection ────────────────────────────────────

    def start(self) -> None:
        """Start background metric collection."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._collect_loop,
            name="james-health",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop background collection."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _collect_loop(self) -> None:
        """Periodically collect system metrics."""
        while not self._stop_event.is_set():
            try:
                info = self._get_process_info()
                self.record("system.cpu", info.get("cpu_percent", 0), "%")
                self.record("system.memory", info.get("memory_mb", 0), "MB")
                self.record("system.threads", info.get("threads", 0))
            except Exception:
                pass
            self._stop_event.wait(self.COLLECTION_INTERVAL)

    def status(self) -> dict:
        return self.snapshot()
