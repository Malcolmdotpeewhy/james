"""
JAMES Unit Tests — Failure Intelligence System
"""
import pytest
from james.failure import (
    FailureType, FailureClassifier, FailureTracker, RecoveryAction,
)


class TestFailureClassifier:
    def test_classify_timeout(self):
        assert FailureClassifier.classify("Connection timed out") == FailureType.TRANSIENT

    def test_classify_connection_refused(self):
        assert FailureClassifier.classify("Connection refused by host") == FailureType.TRANSIENT

    def test_classify_resource_busy(self):
        assert FailureClassifier.classify("Resource temporarily unavailable") == FailureType.TRANSIENT

    def test_classify_access_denied(self):
        assert FailureClassifier.classify("Access is denied") == FailureType.PERMISSION

    def test_classify_permission_denied(self):
        assert FailureClassifier.classify("PermissionError: permission denied") == FailureType.PERMISSION

    def test_classify_requires_admin(self):
        assert FailureClassifier.classify("Requires elevation") == FailureType.PERMISSION

    def test_classify_module_not_found(self):
        assert FailureClassifier.classify("ModuleNotFoundError: No module named 'foo'") == FailureType.DEPENDENCY

    def test_classify_command_not_found(self):
        assert FailureClassifier.classify("'xyz' is not recognized as an internal or external command") == FailureType.DEPENDENCY

    def test_classify_type_error(self):
        assert FailureClassifier.classify("TypeError: expected str, got int") == FailureType.STRUCTURAL

    def test_classify_syntax_error(self):
        assert FailureClassifier.classify("SyntaxError: invalid syntax") == FailureType.STRUCTURAL

    def test_classify_unknown(self):
        assert FailureClassifier.classify("something went wrong") == FailureType.UNKNOWN

    def test_classify_empty(self):
        assert FailureClassifier.classify("") == FailureType.UNKNOWN

    def test_classify_exit_code_5(self):
        assert FailureClassifier.classify("", exit_code=5) == FailureType.PERMISSION

    def test_classify_exit_code_137(self):
        assert FailureClassifier.classify("", exit_code=137) == FailureType.TRANSIENT

    def test_classify_winerror_5(self):
        assert FailureClassifier.classify("WinError 5: Access denied") == FailureType.PERMISSION


class TestRecoveryPlan:
    def test_transient_recovery(self):
        plan = FailureClassifier.get_recovery_plan(FailureType.TRANSIENT)
        assert RecoveryAction.RETRY_WITH_BACKOFF in plan

    def test_structural_recovery(self):
        plan = FailureClassifier.get_recovery_plan(FailureType.STRUCTURAL)
        assert RecoveryAction.REDESIGN_METHOD in plan

    def test_permission_recovery(self):
        plan = FailureClassifier.get_recovery_plan(FailureType.PERMISSION)
        assert RecoveryAction.RECONFIGURE_ENV in plan

    def test_dependency_recovery(self):
        plan = FailureClassifier.get_recovery_plan(FailureType.DEPENDENCY)
        assert RecoveryAction.INSTALL_DEPENDENCY in plan

    def test_max_layer_removes_escalation(self):
        plan = FailureClassifier.get_recovery_plan(FailureType.TRANSIENT, current_layer=5)
        assert RecoveryAction.ESCALATE_LAYER not in plan


class TestFailureTracker:
    def test_record_and_track(self):
        tracker = FailureTracker()
        record = tracker.record_failure(
            node_id="n1",
            node_name="test",
            error_message="Connection timed out",
        )
        assert record.failure_type == FailureType.TRANSIENT
        assert not record.resolved
        assert tracker.total_failures == 1
        assert tracker.unresolved_count == 1

    def test_mark_resolved(self):
        tracker = FailureTracker()
        tracker.record_failure("n1", "test", "timeout")
        tracker.mark_resolved("n1", notes="retried successfully")
        assert tracker.unresolved_count == 0

    def test_failure_rate(self):
        tracker = FailureTracker()
        tracker.record_failure("n1", "test", "err1")
        tracker.record_failure("n1", "test", "err2")
        tracker.mark_resolved("n1")
        rate = tracker.get_failure_rate("n1")
        assert rate == 0.5  # 1 resolved, 1 unresolved out of 2

    def test_get_history(self):
        tracker = FailureTracker()
        tracker.record_failure("n1", "test", "err1")
        tracker.record_failure("n2", "test2", "err2")
        history = tracker.get_history()
        assert len(history) == 2
        assert history[0]["node_id"] == "n1"
