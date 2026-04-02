import unittest
from unittest.mock import MagicMock
import sys

# Mock missing system constraints gracefully
class SafeNumpyMock(MagicMock):
    def __gt__(self, other):
        return True
    def __lt__(self, other):
        return False
    def __bool__(self):
        return True
    def __array_ufunc__(self, *args, **kwargs):
        return MagicMock()

sys.modules['numpy'] = SafeNumpyMock()

from james.orchestrator import Orchestrator  # noqa: E402
from james.dag import ExecutionGraph, Node, NodeState  # noqa: E402

class TestDAGDeadlock(unittest.TestCase):
    def test_thread_crash_recovery(self):
        orch = Orchestrator()
        orch.memory = MagicMock()
        orch.audit = MagicMock()
        orch.streamer = MagicMock()
        orch.failures = MagicMock()
        orch.expander = MagicMock()

        # Create a graph with two nodes. Node A will crash the thread. Node B depends on Node A.
        graph = ExecutionGraph(name="test_deadlock")
        node_a = Node(name="crash_node", action={"type": "command", "target": "crash"})
        node_b = Node(name="dependent_node", action={"type": "command", "target": "echo b"})
        graph.add_node(node_a)
        graph.add_node(node_b)
        graph.add_dependency(node_a.id, node_b.id)

        # Mock the execute_node method to raise an exception for node_a
        original_execute_node = orch._execute_node
        def mock_execute_node(node, graph):
            if node.id == node_a.id:
                raise RuntimeError("Simulated thread crash")
            original_execute_node(node, graph)
        orch._execute_node = mock_execute_node

        orch.execute(graph)

        # Node A should have failed
        self.assertEqual(node_a.state, NodeState.FAILED)
        self.assertIsNotNone(node_a.result)
        self.assertFalse(node_a.result.success)
        self.assertIn("Simulated thread crash", node_a.result.error)

        # Node B should have been skipped
        self.assertEqual(node_b.state, NodeState.SKIPPED)
        self.assertIsNotNone(node_b.result)
        self.assertFalse(node_b.result.success)
