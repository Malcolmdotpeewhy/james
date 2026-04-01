"""
JAMES Failure Intelligence System

Classifies failures, determines recovery strategy, and
manages rollback / layer escalation protocols.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FailureType(Enum):
    """Classification of failure modes."""
    TRANSIENT = "transient"        # Retry-able (timeout, network blip, busy resource)
    STRUCTURAL = "structural"      # Method design flaw, needs redesign
    PERMISSION = "permission"      # Access denied, elevation required
    DEPENDENCY = "dependency"      # Missing tool, package, or service
    UNKNOWN = "unknown"            # Unclassified — triggers learning cycle


class RecoveryAction(Enum):
    """Recovery protocol actions."""
    RETRY = "retry"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    ESCALATE_LAYER = "escalate_layer"
    REDESIGN_METHOD = "redesign_method"
    RECONFIGURE_ENV = "reconfigure_env"
    INSTALL_DEPENDENCY = "install_dependency"
    ROLLBACK = "rollback"
    ABORT = "abort"
    LOG_AND_LEARN = "log_and_learn"


# ── Heuristic Patterns ─────────────────────────────────────────────

_TRANSIENT_PATTERNS = [
    re.compile(r"timeout", re.I),
    re.compile(r"timed?\s*out", re.I),
    re.compile(r"connection\s*(refused|reset|aborted)", re.I),
    re.compile(r"resource\s*(busy|unavailable|temporarily)", re.I),
    re.compile(r"try\s*again", re.I),
    re.compile(r"EAGAIN|ECONNRESET|ETIMEDOUT", re.I),
    re.compile(r"WinError\s*(10053|10054|10060)", re.I),
    re.compile(r"retryable", re.I),
]

_PERMISSION_PATTERNS = [
    re.compile(r"access\s*(is\s*)?denied", re.I),
    re.compile(r"permission\s*denied", re.I),
    re.compile(r"not\s*authorized", re.I),
    re.compile(r"requires?\s*(elevation|admin|root)", re.I),
    re.compile(r"privilege", re.I),
    re.compile(r"WinError\s*(5|1314)", re.I),
    re.compile(r"Operation not permitted", re.I),
]

_DEPENDENCY_PATTERNS = [
    re.compile(r"(command|program|module)\s*not\s*found", re.I),
    re.compile(r"No\s*module\s*named", re.I),
    re.compile(r"is\s*not\s*recognized", re.I),
    re.compile(r"ImportError|ModuleNotFoundError", re.I),
    re.compile(r"not\s*installed", re.I),
    re.compile(r"FileNotFoundError.*exe", re.I),
]

_STRUCTURAL_PATTERNS = [
    re.compile(r"TypeError|ValueError|KeyError|AttributeError", re.I),
    re.compile(r"SyntaxError", re.I),
    re.compile(r"assertion\s*error", re.I),
    re.compile(r"invalid\s*(argument|parameter|option)", re.I),
    re.compile(r"schema\s*(mismatch|error|invalid)", re.I),
]


@dataclass
class FailureContext:
    """Context and details of a failure event to be recorded."""
    node_id: str
    node_name: str
    error_message: str
    exit_code: Optional[int] = None
    layer_attempted: Optional[int] = None


@dataclass
class FailureRecord:
    """Immutable record of a failure event."""
    timestamp: float = field(default_factory=time.time)
    node_id: str = ""
    node_name: str = ""
    failure_type: FailureType = FailureType.UNKNOWN
    error_message: str = ""
    exit_code: Optional[int] = None
    layer_attempted: Optional[int] = None
    recovery_actions: list[RecoveryAction] = field(default_factory=list)
    resolved: bool = False
    resolution_notes: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "failure_type": self.failure_type.value,
            "error_message": self.error_message,
            "exit_code": self.exit_code,
            "layer_attempted": self.layer_attempted,
            "recovery_actions": [a.value for a in self.recovery_actions],
            "resolved": self.resolved,
            "resolution_notes": self.resolution_notes,
        }


class FailureClassifier:
    """
    Classifies errors using heuristic pattern matching
    and determines optimal recovery strategy.
    """

    @staticmethod
    def classify(error_message: str, exit_code: Optional[int] = None) -> FailureType:
        """
        Classify an error into a FailureType.
        Priority order: Permission > Dependency > Transient > Structural > Unknown
        """
        if not error_message and exit_code is None:
            return FailureType.UNKNOWN

        text = error_message or ""

        # Check permission first (most specific, most dangerous to retry)
        for pattern in _PERMISSION_PATTERNS:
            if pattern.search(text):
                return FailureType.PERMISSION

        # Dependency (missing tool/module)
        for pattern in _DEPENDENCY_PATTERNS:
            if pattern.search(text):
                return FailureType.DEPENDENCY

        # Transient (retry-able)
        for pattern in _TRANSIENT_PATTERNS:
            if pattern.search(text):
                return FailureType.TRANSIENT

        # Structural (design flaw)
        for pattern in _STRUCTURAL_PATTERNS:
            if pattern.search(text):
                return FailureType.STRUCTURAL

        # Exit code heuristics
        if exit_code is not None:
            if exit_code in (1, 2):
                return FailureType.STRUCTURAL
            if exit_code == 5:
                return FailureType.PERMISSION
            if exit_code in (-1, 137, 143):
                return FailureType.TRANSIENT  # killed / OOM

        return FailureType.UNKNOWN

    @staticmethod
    def get_recovery_plan(failure_type: FailureType, current_layer: int = 1) -> list[RecoveryAction]:
        """
        Determine recovery actions based on failure type.
        Returns ordered list of actions to attempt.
        """
        plans = {
            FailureType.TRANSIENT: [
                RecoveryAction.RETRY_WITH_BACKOFF,
                RecoveryAction.RETRY,
                RecoveryAction.ESCALATE_LAYER,
            ],
            FailureType.STRUCTURAL: [
                RecoveryAction.REDESIGN_METHOD,
                RecoveryAction.ESCALATE_LAYER,
                RecoveryAction.ABORT,
            ],
            FailureType.PERMISSION: [
                RecoveryAction.RECONFIGURE_ENV,
                RecoveryAction.ESCALATE_LAYER,
                RecoveryAction.ABORT,
            ],
            FailureType.DEPENDENCY: [
                RecoveryAction.INSTALL_DEPENDENCY,
                RecoveryAction.RETRY,
                RecoveryAction.ABORT,
            ],
            FailureType.UNKNOWN: [
                RecoveryAction.LOG_AND_LEARN,
                RecoveryAction.RETRY,
                RecoveryAction.ESCALATE_LAYER,
                RecoveryAction.ABORT,
            ],
        }
        actions = plans.get(failure_type, [RecoveryAction.ABORT])

        # If already at highest layer, remove ESCALATE_LAYER
        if current_layer >= 5:
            actions = [a for a in actions if a != RecoveryAction.ESCALATE_LAYER]

        return actions


class FailureTracker:
    """Tracks and manages failure history for analysis."""

    def __init__(self):
        self._records: list[FailureRecord] = []
        self._classifier = FailureClassifier()

    def record_failure(
        self,
        context: FailureContext,
    ) -> FailureRecord:
        """Record and classify a failure. Returns the FailureRecord."""
        ftype = self._classifier.classify(context.error_message, context.exit_code)
        recovery = self._classifier.get_recovery_plan(
            ftype, current_layer=context.layer_attempted or 1
        )
        record = FailureRecord(
            node_id=context.node_id,
            node_name=context.node_name,
            failure_type=ftype,
            error_message=context.error_message,
            exit_code=context.exit_code,
            layer_attempted=context.layer_attempted,
            recovery_actions=recovery,
        )
        self._records.append(record)
        return record

    def mark_resolved(self, node_id: str, notes: str = "") -> None:
        """Mark the latest failure for a node as resolved."""
        for record in reversed(self._records):
            if record.node_id == node_id and not record.resolved:
                record.resolved = True
                record.resolution_notes = notes
                break

    def get_unresolved(self) -> list[FailureRecord]:
        """Get all unresolved failure records."""
        return [r for r in self._records if not r.resolved]

    def get_failure_rate(self, node_id: str) -> float:
        """Get failure rate for a specific node (0.0 - 1.0)."""
        records = [r for r in self._records if r.node_id == node_id]
        if not records:
            return 0.0
        failed = sum(1 for r in records if not r.resolved)
        return failed / len(records)

    def get_history(self, limit: int = 50) -> list[dict]:
        """Get recent failure history as dicts."""
        return [r.to_dict() for r in self._records[-limit:]]

    @property
    def total_failures(self) -> int:
        return len(self._records)

    @property
    def unresolved_count(self) -> int:
        return len(self.get_unresolved())
