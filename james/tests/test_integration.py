"""
JAMES Unit Tests -- Integration (end-to-end)
"""
import gc
import os
import shutil
import tempfile

import pytest
from james.orchestrator import Orchestrator


@pytest.fixture
def orch():
    """Create an orchestrator with a temp project root to avoid polluting real state."""
    td = tempfile.mkdtemp(prefix="james_test_")
    james_dir = os.path.join(td, "james")
    os.makedirs(james_dir, exist_ok=True)
    o = Orchestrator(project_root=td)
    yield o
    # Explicitly release SQLite connections before cleanup
    del o
    gc.collect()
    try:
        shutil.rmtree(td, ignore_errors=True)
    except Exception:
        pass


class TestOrchestrator:
    def test_status(self, orch):
        status = orch.status()
        assert status["version"] == "2.3.0"
        assert status["layers"]["registered"] == 5
        assert "scheduler" in status
        assert "vectors" in status
        assert "rag" in status
        assert "evolution" in status
        assert "watcher" in status
        assert "conversations" in status
        assert "skill_versions" in status
        assert "health" in status
        assert "plugins" in status
        assert "agents" in status

    def test_plan_string_command(self, orch):
        graph = orch.plan("!echo hello")
        assert len(graph.nodes) == 1
        node = list(graph.nodes.values())[0]
        assert node.action["type"] == "command"
        assert "echo hello" in node.action["target"]

    def test_plan_dict_task(self, orch):
        task = {
            "name": "multi_step",
            "steps": [
                {"name": "step1", "action": {"type": "command", "target": "echo A"}, "layer": 1},
                {"name": "step2", "action": {"type": "command", "target": "echo B"}, "layer": 1, "depends_on": ["step1"]},
            ],
        }
        graph = orch.plan(task)
        assert len(graph.nodes) == 2

    def test_execute_simple_command(self, orch):
        graph = orch.run("!echo JAMES_TEST_OK")
        assert graph.is_complete
        node = list(graph.nodes.values())[0]
        assert node.result is not None
        assert node.result.success is True
        assert "JAMES_TEST_OK" in str(node.result.output)

    def test_execute_powershell(self, orch):
        import shutil
        if not shutil.which("powershell") and not shutil.which("pwsh"):
            pytest.skip("powershell not installed")
        graph = orch.run("!powershell -NoProfile -NonInteractive -Command \"Write-Output 'PowerShell OK'\"")
        assert graph.is_complete
        node = list(graph.nodes.values())[0]
        assert node.result is not None
        assert node.result.success is True

    def test_run_command_shortcut(self, orch):
        output = orch.run_command("echo shortcut_test")
        assert output is not None
        assert "shortcut_test" in str(output)

    def test_security_blocks_destructive(self, orch):
        graph = orch.run("!rm -rf /")
        node = list(graph.nodes.values())[0]
        # Should be SKIPPED by security policy
        from james.dag import NodeState
        assert node.state == NodeState.SKIPPED

    def test_memory_records_metrics(self, orch):
        orch.run("!echo metric_test")
        metrics = orch.memory.get_metrics(limit=5)
        assert len(metrics) >= 1

    def test_audit_records_operations(self, orch):
        orch.run("!echo audit_test")
        entries = orch.audit.read_recent(10)
        assert len(entries) >= 2  # graph_start + node_execute + graph_complete

    def test_improve_runs_clean(self, orch):
        result = orch.improve()
        assert "issues_found" in result
        assert "optimizations_applied" in result
