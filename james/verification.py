"""
JAMES Verification Engine

Enforces deterministic execution through pre/post condition
validation, execution monitoring, and rollback triggers.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class VerificationStatus(Enum):
    """Result of a verification check."""
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    SKIPPED = "skipped"


@dataclass
class VerificationResult:
    """Detailed result of a verification pass."""
    status: VerificationStatus
    checks_passed: int = 0
    checks_failed: int = 0
    checks_total: int = 0
    diagnostics: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def success(self) -> bool:
        return self.status == VerificationStatus.PASS

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "passed": self.checks_passed,
            "failed": self.checks_failed,
            "total": self.checks_total,
            "diagnostics": self.diagnostics,
            "duration_ms": self.duration_ms,
        }


@dataclass
class Condition:
    """
    A verifiable condition (precondition or postcondition).

    Attributes:
        name:        Human-readable name for the condition
        check:       Callable that returns True if condition is met
        required:    If True, failure blocks execution. If False, it's advisory.
        description: Detailed explanation of what this condition checks
    """
    name: str
    check: Callable[..., bool]
    required: bool = True
    description: str = ""

    def evaluate(self, context: Optional[dict] = None) -> tuple[bool, str]:
        """
        Evaluate the condition.
        Returns (passed: bool, diagnostic_message: str).
        """
        try:
            if context is not None:
                result = self.check(context)
            else:
                result = self.check()

            if result:
                return True, f"✓ {self.name}"
            else:
                return False, f"✗ {self.name}: condition not met"
        except Exception as e:
            return False, f"✗ {self.name}: exception during check — {e}"


class VerificationEngine:
    """
    Validates preconditions before execution, monitors execution,
    and verifies postconditions after completion.
    """

    def __init__(self):
        self._global_preconditions: list[Condition] = []
        self._global_postconditions: list[Condition] = []

    def add_global_precondition(self, condition: Condition) -> None:
        """Add a precondition that applies to ALL executions."""
        self._global_preconditions.append(condition)

    def add_global_postcondition(self, condition: Condition) -> None:
        """Add a postcondition that applies to ALL executions."""
        self._global_postconditions.append(condition)

    def verify_preconditions(
        self,
        conditions: list[Condition],
        context: Optional[dict] = None,
    ) -> VerificationResult:
        """
        Run all precondition checks (global + node-specific).
        Returns a VerificationResult.
        """
        all_conditions = self._global_preconditions + conditions
        return self._run_checks(all_conditions, context)

    def verify_postconditions(
        self,
        conditions: list[Condition],
        context: Optional[dict] = None,
    ) -> VerificationResult:
        """
        Run all postcondition checks (global + node-specific).
        Returns a VerificationResult.
        """
        all_conditions = self._global_postconditions + conditions
        return self._run_checks(all_conditions, context)

    def _run_checks(
        self,
        conditions: list[Condition],
        context: Optional[dict] = None,
    ) -> VerificationResult:
        """Run a list of condition checks and aggregate results."""
        if not conditions:
            return VerificationResult(
                status=VerificationStatus.PASS,
                checks_passed=0,
                checks_failed=0,
                checks_total=0,
            )

        start = time.perf_counter()
        passed = 0
        failed = 0
        required_failed = 0
        diagnostics: list[str] = []

        for cond in conditions:
            ok, msg = cond.evaluate(context)
            diagnostics.append(msg)
            if ok:
                passed += 1
            else:
                failed += 1
                if cond.required:
                    required_failed += 1

        duration_ms = (time.perf_counter() - start) * 1000
        total = passed + failed

        if required_failed > 0:
            status = VerificationStatus.FAIL
        elif failed > 0:
            status = VerificationStatus.PARTIAL  # Advisory failures only
        else:
            status = VerificationStatus.PASS

        return VerificationResult(
            status=status,
            checks_passed=passed,
            checks_failed=failed,
            checks_total=total,
            diagnostics=diagnostics,
            duration_ms=duration_ms,
        )

    @staticmethod
    def monitor_execution(
        action: Callable,
        timeout_seconds: float = 300.0,
        context: Optional[dict] = None,
    ) -> tuple[bool, Any, Optional[str], float]:
        """
        Execute an action with monitoring.

        Returns:
            (success, output, error_message, duration_ms)
        """
        start = time.perf_counter()
        try:
            if context is not None:
                result = action(context)
            else:
                result = action()
            duration = (time.perf_counter() - start) * 1000
            return True, result, None, duration
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            tb = traceback.format_exc()
            return False, None, f"{type(e).__name__}: {e}\n{tb}", duration


# ── Pre-built Common Conditions ──────────────────────────────────

def file_exists_condition(path: str) -> Condition:
    """Create a condition that checks if a file exists."""
    import os
    return Condition(
        name=f"file_exists({path})",
        check=lambda: os.path.isfile(path),
        description=f"Verify that file exists: {path}",
    )


def directory_exists_condition(path: str) -> Condition:
    """Create a condition that checks if a directory exists."""
    import os
    return Condition(
        name=f"dir_exists({path})",
        check=lambda: os.path.isdir(path),
        description=f"Verify that directory exists: {path}",
    )


def command_available_condition(command: str) -> Condition:
    """Create a condition that checks if a command is available on PATH."""
    import shutil
    return Condition(
        name=f"command_available({command})",
        check=lambda: shutil.which(command) is not None,
        description=f"Verify that command is on PATH: {command}",
    )


def process_running_condition(process_name: str) -> Condition:
    """Create a condition that checks if a process is running."""
    def _check():
        import subprocess
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
                capture_output=True, text=True, timeout=10,
            )
            return process_name.lower() in result.stdout.lower()
        except Exception:
            return False
    return Condition(
        name=f"process_running({process_name})",
        check=_check,
        description=f"Verify that process is running: {process_name}",
    )
