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

sys.modules['numpy'] = SafeNumpyMock()

from james.orchestrator import Orchestrator
from james.dag import ExecutionGraph, Node, NodeState

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

if __name__ == "__main__":
    unittest.main()
