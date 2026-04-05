import unittest
import os
import sys
from unittest.mock import MagicMock


sys.modules['flask'] = MagicMock()
sys.modules['requests'] = MagicMock()

from james.orchestrator import Orchestrator  # noqa: E402
from james.evolution.expander import GapAnalysis  # noqa: E402

class TestExpander(unittest.TestCase):
    def setUp(self):
        self.orch = Orchestrator()
        self.expander = self.orch.expander

    def test_recover_missing_tool(self):
        tool_name = "test_auto_generated_tool_99"

        # Override the AI generation to just return simple python code
        def mock_generate_tool(name, desc):
            return f"def _tool_{name}(**kwargs) -> dict:\n    return {{'success': True, 'msg': 'hello world'}}"

        self.expander.generate_tool = mock_generate_tool

        # Use sandbox safely validate
        # We need to make sure the tool code doesn't get rejected
        code = self.expander.generate_tool(tool_name, "do something cool")

        gap = GapAnalysis(
            task="do something cool",
            error=f"Unknown tool: {tool_name}",
            gap_type="missing_tool",
            details={"missing_tool": tool_name}
        )

        result = self.expander._recover_missing_tool(gap)
        self.assertTrue(result.get("recovered"), result)
        self.assertEqual(result.get("action"), "dynamic_tool_registered")
        self.assertEqual(result.get("tool"), tool_name)

        # Check that it generated a plugin
        plugin_name = result.get("plugin")
        self.assertIsNotNone(plugin_name)

        plugin_dir = os.path.join(self.orch._james_dir, "plugins", plugin_name)
        self.assertTrue(os.path.exists(plugin_dir))
        self.assertTrue(os.path.exists(os.path.join(plugin_dir, "main.py")))
        self.assertTrue(os.path.exists(os.path.join(plugin_dir, "manifest.json")))

        # Verify the tool is registered in the orchestrator
        tools = self.orch.tools.list_tools()
        tool_names = [t["name"] for t in tools]
        self.assertIn(tool_name, tool_names)

        # Test tool pruning
        prune_result = self.expander.prune_tools(days_old=0)
        self.assertEqual(prune_result.get("status"), "success")
        self.assertIn(plugin_name, prune_result.get("pruned_plugins"))

        # Verify it was deleted
        self.assertFalse(os.path.exists(plugin_dir))

if __name__ == "__main__":
    unittest.main()
