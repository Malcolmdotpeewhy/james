import unittest
import os
import time
from unittest.mock import MagicMock, patch
from james.evolution.expander import CapabilityExpander, GapAnalysis
from james.orchestrator import Orchestrator
from james.dag import ExecutionGraph, Node, NodeResult, NodeState

class TestCapabilityExpanderEvolution(unittest.TestCase):

    def setUp(self):
        self.mock_orch = MagicMock()
        self.mock_orch.audit = MagicMock()
        self.expander = CapabilityExpander(orchestrator=self.mock_orch)

    def test_tool_generation_rate_limit(self):
        gap = GapAnalysis(task="test", error="unknown tool: test", gap_type="missing_tool", details={"missing_tool": "test"})

        # Manually fill the rate limit array
        now = time.time()
        self.expander._generation_timestamps = [now - 10] * self.expander.MAX_TOOLS_PER_HOUR

        # Next generation should fail due to rate limit
        res = self.expander._recover_missing_tool(gap)
        self.assertFalse(res["recovered"])
        self.assertEqual(res["action"], "rate_limit_exceeded")
        self.assertTrue(self.mock_orch.audit.record.called)

    def test_prune_tools_audit_logging(self):
        # We'll mock the os.listdir to pretend there is a self-evolved tool
        self.mock_orch._james_dir = "/tmp/james_fake"
        plugins_dir = os.path.join(self.mock_orch._james_dir, "plugins")

        with patch('os.path.exists', return_value=True), \
             patch('os.listdir', return_value=['self_evolved_oldtool']), \
             patch('os.path.isdir', return_value=True), \
             patch('os.path.getmtime', return_value=time.time() - 86400 * 40), \
             patch('shutil.rmtree') as mock_rmtree:

            res = self.expander.prune_tools(days_old=30)

            self.assertEqual(res["status"], "success")
            self.assertEqual(res["pruned_count"], 1)
            self.assertTrue(self.mock_orch.audit.record.called)

class TestOrchestratorReflexivity(unittest.TestCase):

    def setUp(self):
        self.orch = Orchestrator()
        self.orch.agents = MagicMock()
        self.orch.audit = MagicMock()
        self.orch.plugins = MagicMock()
        self.orch.plugins.get_plugin.return_value = True # Assume plugin exists

    def test_reflexivity_trigger_on_warning(self):
        graph = ExecutionGraph(name="test_graph")
        node = Node(name="test_node", action={"type": "tool_call", "target": "some_tool"}, layer=1)
        node.state = NodeState.SUCCESS
        node.result = NodeResult(success=True, output={"warning": "some deprecated feature used"})
        graph.add_node(node)
        # Using mock to bypass progress property error, we just need _post_execute_learn to iterate

        # This will test if delegate is called
        self.orch._post_execute_learn(graph)

        self.assertTrue(self.orch.agents.delegate.called)
        self.assertTrue(self.orch.audit.record.called)
        args, kwargs = self.orch.agents.delegate.call_args
        task = args[0]
        self.assertEqual(task["name"], "Evolve Tool some_tool")
        self.assertEqual(task["steps"][0]["action"]["target"], "evolve_tool_code")

if __name__ == '__main__':
    unittest.main()
