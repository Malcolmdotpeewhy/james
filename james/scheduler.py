"""
JAMES Task Scheduler — Cron-like background task execution.

Features:
  - One-shot delayed tasks ("remind me in 5 minutes")
  - Recurring interval tasks ("every hour, check disk space")
  - SQLite-persisted task queue (survives restarts)
  - Background thread with configurable poll interval
  - Full audit logging of scheduled executions
  - Graceful shutdown with drain support

Architecture:
  User → schedule_task() → SQLite → Background Thread → Orchestrator.run()
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger("james.scheduler")


@dataclass
class ScheduledTask:
    """Represents a task in the scheduler queue."""
    id: str
    name: str
    task: str                      # Command string or JSON plan
    schedule_type: str             # "once", "interval"
    interval_seconds: Optional[int]
    next_run: float                # Unix timestamp
    last_run: Optional[float]
    last_result: Optional[str]
    enabled: bool
    created_at: float
    run_count: int

    @property
    def next_run_dt(self) -> str:
        """Human-readable next run time."""
        if self.next_run:
            return datetime.fromtimestamp(self.next_run).strftime("%Y-%m-%d %H:%M:%S")
        return "N/A"

    @property
    def last_run_dt(self) -> str | None:
        """Human-readable last run time."""
        if self.last_run:
            return datetime.fromtimestamp(self.last_run).strftime("%Y-%m-%d %H:%M:%S")
        return None

    @property
    def interval_human(self) -> str:
        """Human-readable interval."""
        if not self.interval_seconds:
            return "one-shot"
        mins = self.interval_seconds / 60
        if mins < 60:
            return f"every {mins:.0f}m"
        hours = mins / 60
        if hours < 24:
            return f"every {hours:.1f}h"
        return f"every {hours / 24:.1f}d"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "task": self.task,
            "schedule_type": self.schedule_type,
            "interval_seconds": self.interval_seconds,
            "next_run": self.next_run,
            "next_run_human": self.next_run_dt,
            "last_run": self.last_run,
            "last_run_human": self.last_run_dt,
            "last_result": self.last_result,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "run_count": self.run_count,
            "interval_human": self.interval_human,
        }


class TaskScheduler:
    """
    Cron-like task scheduler with SQLite persistence and background execution.

    Lifecycle:
      1. add_task() → insert into scheduled_tasks table
      2. start()   → spawn background thread
      3. _loop()   → every 30s, check for due tasks
      4. _execute_task() → run through orchestrator, update results
      5. stop()    → graceful shutdown
    """

    _TABLE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            task TEXT NOT NULL,
            schedule_type TEXT NOT NULL DEFAULT 'once',
            interval_seconds INTEGER,
            next_run REAL NOT NULL,
            last_run REAL,
            last_result TEXT,
            enabled INTEGER DEFAULT 1,
            created_at REAL NOT NULL,
            run_count INTEGER DEFAULT 0
        )
    """

    def __init__(self, db_path: str, orchestrator: Any = None,
                 poll_interval: int = 30):
        """
        Args:
            db_path: Path to SQLite database for task persistence.
            orchestrator: Reference to the Orchestrator for task execution.
            poll_interval: Seconds between scheduler checks (default 30).
        """
        self.db_path = db_path
        self.orch = orchestrator
        self.poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._init_db()

    def _init_db(self) -> None:
        """Ensure the scheduled_tasks table exists."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(self._TABLE_SCHEMA)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a new SQLite connection (thread-safe)."""
        return sqlite3.connect(self.db_path)

    # ── CRUD Operations ──────────────────────────────────────────

    def add_task(
        self,
        name: str,
        task: str,
        schedule_type: str = "once",
        interval_seconds: Optional[int] = None,
        delay_seconds: Optional[int] = None,
        run_at: Optional[float] = None,
    ) -> str:
        """
        Add a new scheduled task.

        Args:
            name: Human-readable task name.
            task: Command string or task description to execute.
            schedule_type: "once" for one-shot, "interval" for recurring.
            interval_seconds: Repeat interval (required for "interval" type).
            delay_seconds: Run after this many seconds from now.
            run_at: Specific Unix timestamp to run at (overrides delay_seconds).

        Returns:
            Task ID string.
        """
        task_id = f"sched_{uuid.uuid4().hex[:12]}"

        if run_at:
            next_run = run_at
        elif delay_seconds:
            next_run = time.time() + delay_seconds
        elif interval_seconds:
            next_run = time.time() + interval_seconds
        else:
            next_run = time.time()  # Run immediately on next poll

        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO scheduled_tasks "
                "(id, name, task, schedule_type, interval_seconds, "
                "next_run, last_run, last_result, enabled, created_at, run_count) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 1, ?, 0)",
                (task_id, name, task, schedule_type, interval_seconds,
                 next_run, time.time()),
            )
            conn.commit()

        run_time = datetime.fromtimestamp(next_run).strftime("%H:%M:%S")
        logger.info(
            f"Scheduler: added '{name}' ({schedule_type}, "
            f"next_run={run_time}) → {task_id}"
        )
        return task_id

    def cancel_task(self, task_id: str) -> bool:
        """Disable a scheduled task. Returns True if task existed."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE scheduled_tasks SET enabled=0 WHERE id=?",
                (task_id,),
            )
            conn.commit()
            cancelled = cursor.rowcount > 0

        if cancelled:
            logger.info(f"Scheduler: cancelled task {task_id}")
        return cancelled

    def delete_task(self, task_id: str) -> bool:
        """Permanently delete a scheduled task."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM scheduled_tasks WHERE id=?",
                (task_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_tasks(self, include_disabled: bool = False) -> list[ScheduledTask]:
        """List all scheduled tasks."""
        query = "SELECT * FROM scheduled_tasks"
        if not include_disabled:
            query += " WHERE enabled=1"
        query += " ORDER BY next_run ASC"

        with self._get_conn() as conn:
            rows = conn.execute(query).fetchall()

        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Get a specific task by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id=?",
                (task_id,),
            ).fetchone()

        return self._row_to_task(row) if row else None

    def _row_to_task(self, row: tuple) -> ScheduledTask:
        return ScheduledTask(
            id=row[0],
            name=row[1],
            task=row[2],
            schedule_type=row[3],
            interval_seconds=row[4],
            next_run=row[5],
            last_run=row[6],
            last_result=row[7],
            enabled=bool(row[8]),
            created_at=row[9],
            run_count=row[10],
        )

    # ── Background Execution Loop ────────────────────────────────

    def start(self) -> None:
        """Start the background scheduler thread."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="james-scheduler")
        self._thread.start()
        logger.info(f"Scheduler started (poll_interval={self.poll_interval}s)")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("Scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def _loop(self) -> None:
        """Background loop: check for due tasks every poll_interval seconds."""
        while self._running:
            try:
                executed = self._check_due_tasks()
                if executed:
                    logger.debug(f"Scheduler: executed {executed} due task(s)")
            except Exception as e:
                logger.error(f"Scheduler loop error: {type(e).__name__}: {e}")

            self._stop_event.wait(self.poll_interval)

    def _check_due_tasks(self) -> int:
        """Check for and execute any due tasks. Returns count executed."""
        now = time.time()

        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, name, task, schedule_type, interval_seconds "
                "FROM scheduled_tasks "
                "WHERE enabled=1 AND next_run <= ?",
                (now,),
            ).fetchall()

        executed = 0
        for task_id, name, task_str, sched_type, interval in rows:
            logger.info(f"Scheduler: executing '{name}' ({task_id})")

            result_str = self._execute_task(task_str, name)
            executed += 1

            # Update run info
            with self._get_conn() as conn:
                if sched_type == "interval" and interval:
                    # Reschedule for next interval
                    conn.execute(
                        "UPDATE scheduled_tasks SET "
                        "last_run=?, last_result=?, next_run=?, run_count=run_count+1 "
                        "WHERE id=?",
                        (now, result_str, now + interval, task_id),
                    )
                else:
                    # One-shot: disable after execution
                    conn.execute(
                        "UPDATE scheduled_tasks SET "
                        "last_run=?, last_result=?, enabled=0, run_count=run_count+1 "
                        "WHERE id=?",
                        (now, result_str, task_id),
                    )
                conn.commit()

        return executed

    def _execute_task(self, task_str: str, name: str) -> str:
        """Execute a task through the orchestrator. Returns result string."""
        if not self.orch:
            return "error: no orchestrator attached"

        try:
            # Try to parse as JSON plan first
            try:
                plan = json.loads(task_str)
                if isinstance(plan, dict) and "steps" in plan:
                    graph = self.orch.run(plan)
                else:
                    graph = self.orch.run(task_str)
            except (json.JSONDecodeError, ValueError):
                # Treat as command string
                graph = self.orch.run(task_str)

            done, total = graph.progress
            has_failures = graph.has_failures
            result = f"{'success' if not has_failures else 'partial'}: {done}/{total} nodes"

            # Record in audit
            if hasattr(self.orch, "audit"):
                from james.security import AuditEntry, OpClass
                self.orch.audit.record(AuditEntry(
                    operation="scheduled_task_executed",
                    classification=OpClass.SAFE,
                    details=f"'{name}': {result}",
                ))

            return result

        except Exception as e:
            error_msg = f"error: {type(e).__name__}: {str(e)[:200]}"
            logger.error(f"Scheduler task '{name}' failed: {error_msg}")
            return error_msg

    # ── Status & Info ────────────────────────────────────────────

    def status(self) -> dict:
        """Get scheduler status for dashboard/API."""
        tasks = self.list_tasks(include_disabled=True)
        active = [t for t in tasks if t.enabled]
        return {
            "running": self._running,
            "poll_interval_seconds": self.poll_interval,
            "total_tasks": len(tasks),
            "active_tasks": len(active),
            "tasks": [t.to_dict() for t in tasks],
        }
