import time
import unittest

from james.dag import ExecutionGraph, Node
from james.orchestrator import Orchestrator


class TestDAGParallelExecution(unittest.TestCase):
    def test_parallel_execution(self):
        """
        Verify that nodes without dependencies run in parallel.
        Three nodes sleeping for 1 second should finish in ~1 second, not 3 seconds.
        """
        orch = Orchestrator()
        graph = ExecutionGraph(name="test_parallel")

        # We use Python functions as actions to be fast and cross-platform
        # instead of bash sleep which can fail on some test environments.
        def sleep_action():
            time.sleep(1)
            return True

        n1 = Node(name="n1", action=sleep_action, layer=1)
        n2 = Node(name="n2", action=sleep_action, layer=1)
        n3 = Node(name="n3", action=sleep_action, layer=1)

        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_node(n3)

        start = time.time()
        orch.execute(graph)
        duration = time.time() - start

        # If running sequentially, this would take ~3 seconds
        # If running in parallel, it should take ~1 second.
        self.assertLess(duration, 2.5, "Execution took too long, nodes likely did not run in parallel.")

        # Ensure all completed successfully
        self.assertTrue(n1.result and n1.result.success)
        self.assertTrue(n2.result and n2.result.success)
        self.assertTrue(n3.result and n3.result.success)
