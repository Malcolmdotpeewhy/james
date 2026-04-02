import unittest
from unittest.mock import MagicMock
import sys
class SafeNumpyMock(MagicMock):
    def __gt__(self, other):
        return True
    def __lt__(self, other):
        return False
    def __bool__(self):
        return True
    def __array_ufunc__(self, *args, **kwargs):
        return MagicMock()

sys.modules['numpy'] = SafeNumpyMock()  # noqa: E402

from james.orchestrator import Orchestrator  # noqa: E402
from james.dag import ExecutionGraph, Node, NodeState  # noqa: E402

class TestDAGCrashRecovery(unittest.TestCase):
    def test_node_crash_recovery(self):
        orch = Orchestrator()
        orch.memory = MagicMock()
        orch.audit = MagicMock()
        orch.streamer = MagicMock()
        orch.verifier = MagicMock()

        # Force a crash in preconditions to simulate an unexpected exception in _execute_node
        orch.verifier.verify_preconditions.side_effect = Exception("Intentional thread crash")

        node = Node(name="crashing_node", action={"type": "command", "target": "echo"}, layer=1)
        graph = ExecutionGraph(name="test_crash")
        graph.add_node(node)

        orch.execute(graph)

        self.assertEqual(node.state, NodeState.FAILED)
        self.assertIn("Intentional thread crash", str(node.result.error))

    def test_thread_crash_deadlock_recovery(self):
        orch = Orchestrator()
        orch.memory = MagicMock()
        orch.audit = MagicMock()
        orch.streamer = MagicMock()
        orch.verifier = MagicMock()

        # A node that will crash the thread
        node1 = Node(name="crashing_node", action={"type": "command", "target": "echo"}, layer=1)
        # A node that depends on the crashing node
        node2 = Node(name="dependent_node", action={"type": "command", "target": "echo"}, layer=1)

        graph = ExecutionGraph(name="test_deadlock_recovery")
        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_dependency(from_id=node1.id, to_id=node2.id)

        # Mock the execute node method to throw an exception that bypasses the regular catch block
        def raise_exception(*args, **kwargs):
            raise Exception("Catastrophic thread failure")

        orch._execute_node = MagicMock(side_effect=raise_exception)

        orch.execute(graph)

        # The first node should be FAILED due to the thread crash
        self.assertEqual(node1.state, NodeState.FAILED)
        self.assertIn("Catastrophic thread failure", str(node1.result.error))

        # The dependent node should be SKIPPED instead of the orchestrator deadlocking
        self.assertEqual(node2.state, NodeState.SKIPPED)


if __name__ == "__main__":
    unittest.main()
