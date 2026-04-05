import unittest
from unittest.mock import MagicMock
import sys

# Mock missing system constraints gracefully
# noqa: E402


from james.orchestrator import Orchestrator  # noqa: E402
from james.dag import ExecutionGraph, Node, NodeState  # noqa: E402
from james.layers import LayerResult, LayerLevel  # noqa: E402

class TestDAGRecovery(unittest.TestCase):
    def test_auto_recovery_execution(self):
        orch = Orchestrator()
        orch.memory = MagicMock()
        orch.audit = MagicMock()
        orch.streamer = MagicMock()
        orch.failures = MagicMock()
        orch.failures.record_failure = MagicMock(return_value=MagicMock(failure_type=MagicMock(value="runtime"), recovery_actions=[]))
        orch.expander = MagicMock()
        orch.expander.attempt_recovery.return_value = {"recovered": True, "action": "installed package"}

        node = Node(name="fail_node", action={"type": "command", "target": "fail_cmd"}, retry_limit=1, layer=1)

        mock_layer = MagicMock()
        mock_layer.level = LayerLevel.NATIVE
        mock_layer.name = "native"

        def execute_side_effect(action):
            if mock_layer.execute.call_count == 1:
                return LayerResult(success=False, error="command not found", duration_ms=10)
            return LayerResult(success=True, output="success after recovery", duration_ms=10)

        mock_layer.execute.side_effect = execute_side_effect

        orch.layers.select_best = MagicMock(return_value=mock_layer)
        orch.layers.get = MagicMock(return_value=mock_layer)

        graph = ExecutionGraph(name="test_recovery")
        graph.add_node(node)

        orch.execute(graph)

        self.assertEqual(node.state, NodeState.SUCCESS)
        self.assertEqual(node.result.attempts, 2)
        self.assertTrue(node.result.metadata.get("auto_recovered"))
        # Verify execute was called with node.action dict
        mock_layer.execute.assert_called_with(node.action)
