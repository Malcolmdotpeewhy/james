"""
Tests for Plan Validator, Model Router, and Task Scheduler.
"""

import os
import sys
import tempfile
import time
import unittest

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestPlanValidator(unittest.TestCase):
    """Test AI plan pre-flight validation."""

    def setUp(self):
        from james.ai.plan_validator import PlanValidator
        self.validator = PlanValidator()

    def test_valid_simple_plan(self):
        plan = {
            "name": "test_plan",
            "steps": [
                {"name": "step1", "action": {"type": "command", "target": "echo hello"}, "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        self.assertTrue(result.valid)
        self.assertEqual(len(result.errors), 0)

    def test_empty_steps_rejected(self):
        plan = {"name": "empty", "steps": []}
        result = self.validator.validate(plan)
        self.assertFalse(result.valid)
        self.assertIn("no steps", result.errors[0].lower())

    def test_dangerous_rm_rf_blocked(self):
        plan = {
            "steps": [
                {"name": "danger", "action": {"type": "command", "target": "rm -rf /"}, "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        self.assertFalse(result.valid)
        self.assertTrue(any("BLOCKED" in e for e in result.errors))

    def test_dangerous_format_blocked(self):
        plan = {
            "steps": [
                {"name": "format_c", "action": {"type": "command", "target": "format C:"}, "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        self.assertFalse(result.valid)

    def test_dangerous_shutdown_blocked(self):
        plan = {
            "steps": [
                {"name": "shutdown", "action": {"type": "command", "target": "shutdown /s"}, "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        self.assertFalse(result.valid)

    def test_layer_autocorrect(self):
        plan = {
            "steps": [
                {"name": "step1", "action": {"type": "tool_call", "target": "system_info", "kwargs": {}}, "layer": 3}
            ],
        }
        result = self.validator.validate(plan)
        self.assertTrue(result.valid)
        self.assertEqual(result.corrected_plan["steps"][0]["layer"], 1)
        self.assertTrue(result.corrections_applied > 0)
        self.assertTrue(len(result.warnings) > 0)

    def test_missing_kwargs_autocorrect(self):
        plan = {
            "steps": [
                {"name": "step1", "action": {"type": "tool_call", "target": "system_info"}, "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        self.assertTrue(result.valid)
        self.assertIn("kwargs", result.corrected_plan["steps"][0]["action"])

    def test_missing_action_type_rejected(self):
        plan = {
            "steps": [
                {"name": "bad", "action": {"target": "something"}, "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        self.assertFalse(result.valid)
        self.assertTrue(any("Missing 'action.type'" in e for e in result.errors))

    def test_action_not_dict_rejected(self):
        plan = {
            "steps": [
                {"name": "bad", "action": "not_a_dict", "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        self.assertFalse(result.valid)

    def test_unknown_tool_with_registry(self):
        """Test that unknown tools are caught when registry is provided."""
        from james.ai.plan_validator import PlanValidator

        # Create a mock registry
        class MockRegistry:
            def list_tools(self):
                return [{"name": "system_info"}, {"name": "disk_usage"}]

        validator = PlanValidator(tool_registry=MockRegistry())
        plan = {
            "steps": [
                {"name": "bad_tool", "action": {"type": "tool_call", "target": "nonexistent_tool", "kwargs": {}}, "layer": 1}
            ],
        }
        result = validator.validate(plan)
        self.assertFalse(result.valid)
        self.assertTrue(any("Unknown tool" in e for e in result.errors))

    def test_valid_tool_with_registry(self):
        """Test that known tools pass validation."""
        from james.ai.plan_validator import PlanValidator

        class MockRegistry:
            def list_tools(self):
                return [{"name": "system_info"}, {"name": "disk_usage"}]

        validator = PlanValidator(tool_registry=MockRegistry())
        plan = {
            "steps": [
                {"name": "good_tool", "action": {"type": "tool_call", "target": "system_info", "kwargs": {}}, "layer": 1}
            ],
        }
        result = validator.validate(plan)
        self.assertTrue(result.valid)

    def test_path_traversal_warning(self):
        plan = {
            "steps": [
                {"name": "traverse", "action": {"type": "tool_call", "target": "file_read", "kwargs": {"path": "../../etc/passwd"}}, "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        # Path traversal is a warning, not error (unless registry blocks the tool)
        self.assertTrue(len(result.warnings) > 0)

    def test_blocked_system_path(self):
        plan = {
            "steps": [
                {"name": "sys_read", "action": {"type": "file_read", "target": "C:\\Windows\\System32\\config\\SAM"}, "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        self.assertFalse(result.valid)

    def test_multi_step_mixed_validation(self):
        """Test plan with both valid and invalid steps."""
        plan = {
            "steps": [
                {"name": "good", "action": {"type": "command", "target": "echo hello"}, "layer": 1},
                {"name": "bad", "action": {"type": "command", "target": "rm -rf /"}, "layer": 1},
            ],
        }
        result = self.validator.validate(plan)
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)

    def test_auto_names_unnamed_steps(self):
        plan = {
            "steps": [
                {"action": {"type": "command", "target": "echo hello"}, "layer": 1}
            ],
        }
        result = self.validator.validate(plan)
        self.assertTrue(result.valid)
        self.assertEqual(result.corrected_plan["steps"][0]["name"], "step_1")


class TestModelRouter(unittest.TestCase):
    """Test MoE-style model routing."""

    def setUp(self):
        from james.ai.router import ModelRouter
        self.router = ModelRouter()

    def test_greeting_routes_to_fast(self):
        decision = self.router.route("greeting", 0.9, "Hello!")
        self.assertEqual(decision.tier, "fast")
        self.assertEqual(decision.max_tokens, 512)
        self.assertEqual(decision.temperature, 0.2)

    def test_command_routes_to_balanced(self):
        decision = self.router.route("command", 0.8, "dir C:\\")
        self.assertEqual(decision.tier, "balanced")
        self.assertEqual(decision.max_tokens, 1024)

    def test_analysis_routes_to_smart(self):
        decision = self.router.route("analysis", 0.7, "Analyze performance")
        self.assertEqual(decision.tier, "smart")
        self.assertEqual(decision.max_tokens, 2048)
        self.assertEqual(decision.temperature, 0.4)

    def test_code_routes_to_code_tier(self):
        decision = self.router.route("code_generation", 0.8, "Write a function")
        self.assertEqual(decision.tier, "code")
        self.assertEqual(decision.temperature, 0.1)

    def test_unknown_routes_to_balanced(self):
        decision = self.router.route("unknown", 0.0, "something weird")
        self.assertEqual(decision.tier, "balanced")

    def test_long_message_escalates_from_fast(self):
        long_msg = "x " * 150  # 300 chars
        decision = self.router.route("greeting", 0.9, long_msg)
        self.assertEqual(decision.tier, "balanced")

    def test_low_confidence_escalates_from_fast(self):
        decision = self.router.route("greeting", 0.3, "hmm")
        self.assertEqual(decision.tier, "balanced")

    def test_tier_info(self):
        info = self.router.get_tier_info()
        self.assertIn("fast", info)
        self.assertIn("balanced", info)
        self.assertIn("smart", info)
        self.assertIn("code", info)

    def test_route_decision_fields(self):
        decision = self.router.route("memory_query", 0.85, "what's my name?")
        self.assertEqual(decision.intent, "memory_query")
        self.assertAlmostEqual(decision.confidence, 0.85)
        self.assertIsInstance(decision.max_tokens, int)
        self.assertIsInstance(decision.temperature, float)


class TestTaskScheduler(unittest.TestCase):
    """Test the cron-like task scheduler."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_scheduler.db")

        from james.scheduler import TaskScheduler
        self.scheduler = TaskScheduler(
            db_path=self.db_path,
            orchestrator=None,
            poll_interval=1,
        )

    def tearDown(self):
        self.scheduler.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_task(self):
        from james.scheduler import TaskSchedule
        task_id = self.scheduler.add_task(
            name="test_task",
            task="!echo hello",
            schedule=TaskSchedule(
                schedule_type="once",
                delay_seconds=60,
            )
        )
        self.assertTrue(task_id.startswith("sched_"))

    def test_list_tasks(self):
        from james.scheduler import TaskSchedule
        self.scheduler.add_task(name="t1", task="!echo 1", schedule=TaskSchedule(delay_seconds=60))
        self.scheduler.add_task(name="t2", task="!echo 2", schedule=TaskSchedule(delay_seconds=120))
        tasks = self.scheduler.list_tasks()
        self.assertEqual(len(tasks), 2)

    def test_cancel_task(self):
        from james.scheduler import TaskSchedule
        task_id = self.scheduler.add_task(name="cancel_me", task="!echo bye", schedule=TaskSchedule(delay_seconds=60))
        self.assertTrue(self.scheduler.cancel_task(task_id))
        tasks = self.scheduler.list_tasks(include_disabled=False)
        self.assertEqual(len(tasks), 0)

    def test_cancel_nonexistent(self):
        self.assertFalse(self.scheduler.cancel_task("nonexistent_id"))

    def test_get_task(self):
        from james.scheduler import TaskSchedule
        task_id = self.scheduler.add_task(name="find_me", task="!echo found", schedule=TaskSchedule(delay_seconds=60))
        task = self.scheduler.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.name, "find_me")
        self.assertEqual(task.task, "!echo found")
        self.assertTrue(task.enabled)

    def test_get_nonexistent_task(self):
        self.assertIsNone(self.scheduler.get_task("no_such_id"))

    def test_delete_task(self):
        from james.scheduler import TaskSchedule
        task_id = self.scheduler.add_task(name="delete_me", task="!echo gone", schedule=TaskSchedule(delay_seconds=60))
        self.assertTrue(self.scheduler.delete_task(task_id))
        self.assertIsNone(self.scheduler.get_task(task_id))

    def test_status(self):
        from james.scheduler import TaskSchedule
        self.scheduler.add_task(name="status_test", task="!echo status", schedule=TaskSchedule(delay_seconds=60))
        status = self.scheduler.status()
        self.assertIn("running", status)
        self.assertIn("total_tasks", status)
        self.assertIn("active_tasks", status)
        self.assertEqual(status["total_tasks"], 1)
        self.assertEqual(status["active_tasks"], 1)

    def test_task_to_dict(self):
        from james.scheduler import TaskSchedule
        task_id = self.scheduler.add_task(name="dict_test", task="!echo dict", schedule=TaskSchedule(delay_seconds=300))
        task = self.scheduler.get_task(task_id)
        d = task.to_dict()
        self.assertEqual(d["name"], "dict_test")
        self.assertIn("next_run_human", d)
        self.assertIn("interval_human", d)

    def test_interval_human_readable(self):
        from james.scheduler import ScheduledTask, TaskSchedule
        task = ScheduledTask(
            id="test", name="test", task="test", schedule_type="interval",
            interval_seconds=3600, next_run=0, last_run=None,
            last_result=None, enabled=True, created_at=0, run_count=0,
        )
        self.assertEqual(task.interval_human, "every 1.0h")

        task.interval_seconds = 300
        self.assertEqual(task.interval_human, "every 5m")

        task.interval_seconds = None
        self.assertEqual(task.interval_human, "one-shot")

    def test_start_stop(self):
        self.scheduler.start()
        self.assertTrue(self.scheduler.is_running)
        self.scheduler.stop()
        self.assertFalse(self.scheduler.is_running)

    def test_recurring_task_created(self):
        from james.scheduler import TaskSchedule
        task_id = self.scheduler.add_task(
            name="recurring",
            task="!echo recurring",
            schedule=TaskSchedule(
                schedule_type="interval",
                interval_seconds=120,
            )
        )
        task = self.scheduler.get_task(task_id)
        self.assertEqual(task.schedule_type, "interval")
        self.assertEqual(task.interval_seconds, 120)


class TestSchedulerTools(unittest.TestCase):
    """Test scheduler tool functions."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "tool_test.db")

        from james.scheduler import TaskScheduler
        from james.tools.registry import set_scheduler
        self.scheduler = TaskScheduler(db_path=self.db_path)
        set_scheduler(self.scheduler)

    def tearDown(self):
        from james.tools.registry import set_scheduler
        set_scheduler(None)
        self.scheduler.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tool_schedule_task(self):
        from james.tools.registry import _tool_schedule_task
        result = _tool_schedule_task(name="tool_test", task="!echo hi", delay_minutes=5)
        self.assertEqual(result["status"], "scheduled")
        self.assertIn("task_id", result)

    def test_tool_schedule_recurring(self):
        from james.tools.registry import _tool_schedule_task
        result = _tool_schedule_task(name="recurring", task="!echo rep", interval_minutes=10)
        self.assertEqual(result["type"], "recurring")

    def test_tool_list_scheduled(self):
        from james.tools.registry import _tool_schedule_task, _tool_list_scheduled
        _tool_schedule_task(name="list_test", task="!echo list", delay_minutes=5)
        result = _tool_list_scheduled()
        self.assertEqual(result["total_tasks"], 1)

    def test_tool_cancel_scheduled(self):
        from james.tools.registry import _tool_schedule_task, _tool_cancel_scheduled
        result = _tool_schedule_task(name="cancel_test", task="!echo bye", delay_minutes=5)
        task_id = result["task_id"]
        cancel_result = _tool_cancel_scheduled(task_id=task_id)
        self.assertEqual(cancel_result["status"], "cancelled")

    def test_tool_schedule_no_task(self):
        from james.tools.registry import _tool_schedule_task
        result = _tool_schedule_task(name="empty")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
