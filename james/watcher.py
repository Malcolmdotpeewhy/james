"""
JAMES Watch Mode — File system watcher that triggers tasks on changes.

Monitors directories for file changes and automatically runs
associated tasks when modifications are detected.

Uses polling (no external deps) with configurable interval.
Supports glob-based include/exclude patterns.

Usage:
    watcher = FileWatcher(orchestrator=orch)
    watcher.watch("C:/Projects/myapp/src", task="!python -m pytest", pattern="*.py")
    watcher.start()
"""

from __future__ import annotations

import fnmatch
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("james.watcher")


@dataclass
class WatchRule:
    """A single file watch rule."""
    id: str
    directory: str
    task: str                      # Command or AI instruction to run
    patterns: list[str]            # Glob patterns to include (e.g., ["*.py"])
    exclude: list[str] = field(default_factory=list)  # Glob patterns to exclude
    debounce_seconds: float = 2.0   # Minimum seconds between triggers
    enabled: bool = True
    last_triggered: float = 0.0
    trigger_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "directory": self.directory,
            "task": self.task,
            "patterns": self.patterns,
            "exclude": self.exclude,
            "debounce_seconds": self.debounce_seconds,
            "enabled": self.enabled,
            "trigger_count": self.trigger_count,
        }


class FileWatcher:
    """
    Polls directories for file changes and triggers tasks.

    No external dependencies — uses os.stat polling instead of
    watchdog/inotify for maximum portability.
    """

    DEFAULT_POLL_INTERVAL = 3.0  # seconds

    def __init__(self, orchestrator=None, poll_interval: float = None):
        self.orch = orchestrator
        self._poll_interval = poll_interval or self.DEFAULT_POLL_INTERVAL
        self._rules: dict[str, WatchRule] = {}
        self._snapshots: dict[str, dict[str, float]] = {}  # rule_id → {path: mtime}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._rule_counter = 0

    # ── Rule Management ──────────────────────────────────────────

    def watch(self, directory: str, task: str,
              patterns: list[str] = None,
              exclude: list[str] = None,
              debounce: float = 2.0) -> str:
        """
        Add a watch rule.

        Args:
            directory: Directory to monitor.
            task: Command or instruction to execute on change.
            patterns: Glob patterns to match (default: ["*"]).
            exclude: Glob patterns to exclude.
            debounce: Minimum seconds between triggers.

        Returns:
            Rule ID.
        """
        directory = os.path.abspath(directory)
        if not os.path.isdir(directory):
            raise ValueError(f"Not a directory: {directory}")

        self._rule_counter += 1
        rule_id = f"watch_{self._rule_counter}"

        rule = WatchRule(
            id=rule_id,
            directory=directory,
            task=task,
            patterns=patterns or ["*"],
            exclude=exclude or [],
            debounce_seconds=debounce,
        )

        with self._lock:
            self._rules[rule_id] = rule
            self._snapshots[rule_id] = self._scan_directory(rule)

        logger.info(f"Watch rule '{rule_id}': {directory} → {task}")
        return rule_id

    def unwatch(self, rule_id: str) -> bool:
        """Remove a watch rule."""
        with self._lock:
            if rule_id in self._rules:
                del self._rules[rule_id]
                self._snapshots.pop(rule_id, None)
                logger.info(f"Watch rule '{rule_id}' removed")
                return True
        return False

    def list_rules(self) -> list[dict]:
        """List all watch rules."""
        with self._lock:
            return [r.to_dict() for r in self._rules.values()]

    # ── Lifecycle ────────────────────────────────────────────────

    def start(self) -> None:
        """Start the watcher thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="james-watcher",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"File watcher started (poll={self._poll_interval}s)")

    def stop(self) -> None:
        """Stop the watcher thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("File watcher stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Core Loop ────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Main polling loop."""
        while not self._stop_event.is_set():
            try:
                self._check_all_rules()
            except Exception as e:
                logger.error(f"Watcher poll error: {e}")
            self._stop_event.wait(self._poll_interval)

    def _check_all_rules(self) -> None:
        """Check all watch rules for changes."""
        with self._lock:
            rules = list(self._rules.values())

        for rule in rules:
            if not rule.enabled:
                continue
            try:
                self._check_rule(rule)
            except Exception as e:
                logger.error(f"Error checking rule {rule.id}: {e}")

    def _check_rule(self, rule: WatchRule) -> None:
        """Check a single rule for file changes."""
        current = self._scan_directory(rule)
        previous = self._snapshots.get(rule.id, {})

        # Find changes
        changed_files = []
        for path, mtime in current.items():
            if path not in previous or previous[path] != mtime:
                changed_files.append(path)

        # Find deleted files
        deleted = set(previous.keys()) - set(current.keys())

        if changed_files or deleted:
            # Debounce check
            now = time.time()
            if now - rule.last_triggered < rule.debounce_seconds:
                return

            rule.last_triggered = now
            rule.trigger_count += 1

            change_summary = []
            if changed_files:
                change_summary.append(f"{len(changed_files)} modified")
            if deleted:
                change_summary.append(f"{len(deleted)} deleted")

            logger.info(
                f"Watch [{rule.id}]: {', '.join(change_summary)} in {rule.directory} "
                f"→ triggering: {rule.task}"
            )

            # Update snapshot
            with self._lock:
                self._snapshots[rule.id] = current

            # Execute the task
            self._trigger_task(rule, changed_files, list(deleted))

    def _trigger_task(self, rule: WatchRule, changed: list[str],
                      deleted: list[str]) -> None:
        """Execute the task associated with a watch rule."""
        if not self.orch:
            logger.warning(f"No orchestrator — cannot execute task for {rule.id}")
            return

        try:
            # Inject changed files into the task context
            task = rule.task
            if "{files}" in task:
                task = task.replace("{files}", " ".join(changed[:10]))

            result = self.orch.run(task)
            logger.info(f"Watch [{rule.id}] task completed: {result.name}")
        except Exception as e:
            logger.error(f"Watch [{rule.id}] task failed: {e}")

    def _scan_directory(self, rule: WatchRule) -> dict[str, float]:
        """Scan a directory and return {path: mtime} for matching files."""
        result = {}
        try:
            for root, dirs, files in os.walk(rule.directory):
                # Skip common directories
                dirs[:] = [d for d in dirs if d not in {
                    ".git", "__pycache__", "node_modules", ".venv",
                    "venv", "dist", "build", ".tox",
                }]

                for f in files:
                    full_path = os.path.join(root, f)

                    # Check include patterns
                    if not any(fnmatch.fnmatch(f, p) for p in rule.patterns):
                        continue

                    # Check exclude patterns
                    if any(fnmatch.fnmatch(f, p) for p in rule.exclude):
                        continue

                    try:
                        result[full_path] = os.path.getmtime(full_path)
                    except OSError:
                        pass

        except Exception as e:
            logger.warning(f"Scan error for {rule.directory}: {e}")

        return result

    # ── Status ───────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "running": self.is_running,
            "poll_interval": self._poll_interval,
            "rules": len(self._rules),
            "active_rules": sum(1 for r in self._rules.values() if r.enabled),
            "total_triggers": sum(r.trigger_count for r in self._rules.values()),
        }
