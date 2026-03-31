"""
JAMES Unit Tests — Verification Engine
"""
import pytest
from unittest.mock import patch
from james.verification import (
    Condition, VerificationEngine, VerificationStatus,
    file_exists_condition, directory_exists_condition, command_available_condition,
)


class TestCondition:
    def test_passing_condition(self):
        cond = Condition(name="always_true", check=lambda: True)
        passed, msg = cond.evaluate()
        assert passed is True

    def test_failing_condition(self):
        cond = Condition(name="always_false", check=lambda: False)
        passed, msg = cond.evaluate()
        assert passed is False

    def test_exception_in_check(self):
        def bad_check():
            raise RuntimeError("boom")
        cond = Condition(name="exploder", check=bad_check)
        passed, msg = cond.evaluate()
        assert passed is False
        assert "exception" in msg.lower()

    def test_context_passing(self):
        cond = Condition(name="ctx", check=lambda ctx: ctx.get("ready", False))
        passed, _ = cond.evaluate(context={"ready": True})
        assert passed is True
        passed, _ = cond.evaluate(context={"ready": False})
        assert passed is False


class TestVerificationEngine:
    def test_all_pass(self):
        engine = VerificationEngine()
        conditions = [
            Condition(name="c1", check=lambda: True),
            Condition(name="c2", check=lambda: True),
        ]
        result = engine.verify_preconditions(conditions)
        assert result.status == VerificationStatus.PASS
        assert result.checks_passed == 2
        assert result.checks_failed == 0

    def test_required_failure(self):
        engine = VerificationEngine()
        conditions = [
            Condition(name="must_pass", check=lambda: False, required=True),
        ]
        result = engine.verify_preconditions(conditions)
        assert result.status == VerificationStatus.FAIL

    def test_advisory_failure_partial(self):
        engine = VerificationEngine()
        conditions = [
            Condition(name="required_ok", check=lambda: True, required=True),
            Condition(name="advisory_fail", check=lambda: False, required=False),
        ]
        result = engine.verify_preconditions(conditions)
        assert result.status == VerificationStatus.PARTIAL

    def test_empty_conditions(self):
        engine = VerificationEngine()
        result = engine.verify_preconditions([])
        assert result.status == VerificationStatus.PASS

    def test_global_preconditions(self):
        engine = VerificationEngine()
        engine.add_global_precondition(
            Condition(name="global", check=lambda: True)
        )
        result = engine.verify_preconditions([])
        assert result.checks_total == 1
        assert result.status == VerificationStatus.PASS

    def test_global_postconditions(self):
        engine = VerificationEngine()
        engine.add_global_postcondition(
            Condition(name="global_post", check=lambda: True)
        )
        result = engine.verify_postconditions([])
        assert result.checks_total == 1
        assert result.status == VerificationStatus.PASS

    def test_monitor_execution_success(self):
        ok, output, error, duration = VerificationEngine.monitor_execution(
            lambda: "hello"
        )
        assert ok is True
        assert output == "hello"
        assert error is None
        assert duration > 0

    def test_monitor_execution_failure(self):
        def failing():
            raise ValueError("bad")
        ok, output, error, duration = VerificationEngine.monitor_execution(failing)
        assert ok is False
        assert "ValueError" in error


class TestPrebuiltConditions:
    def test_file_exists_true(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        cond = file_exists_condition(str(f))
        passed, _ = cond.evaluate()
        assert passed is True

    def test_file_exists_false(self, tmp_path):
        cond = file_exists_condition(str(tmp_path / "nope.txt"))
        passed, _ = cond.evaluate()
        assert passed is False

    def test_directory_exists_true(self, tmp_path):
        d = tmp_path / "test_dir"
        d.mkdir()
        cond = directory_exists_condition(str(d))
        passed, _ = cond.evaluate()
        assert passed is True

    def test_directory_exists_false(self, tmp_path):
        cond = directory_exists_condition(str(tmp_path / "nope_dir"))
        passed, _ = cond.evaluate()
        assert passed is False

    def test_directory_exists_not_a_dir(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        cond = directory_exists_condition(str(f))
        passed, _ = cond.evaluate()
        assert passed is False

    def test_command_available(self):
        cond = command_available_condition("python")
        passed, _ = cond.evaluate()
        assert passed is False
