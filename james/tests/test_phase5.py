"""
Tests for Phase 5: Health Monitor, Plugin Architecture, Multi-Agent Orchestration.
"""

import os
import sys
import tempfile
import time
import unittest
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ── Health Monitor Tests ────────────────────────────────────────

class TestHealthMonitor(unittest.TestCase):
    def setUp(self):
        from james.health import HealthMonitor
        self.health = HealthMonitor()
        
    def test_record_metric(self):
        self.health.record("test_metric", 42.0, "ms")
        metrics = self.health.get_metric("test_metric")
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["value"], 42.0)
        self.assertEqual(metrics[0]["unit"], "ms")
        
    def test_counters(self):
        self.health.increment("my_error", 1)
        self. स्वास्थ्यsnapshot = self.health.snapshot()
        self.assertEqual(self. स्वास्थ्यsnapshot["custom_counters"].get("my_error"), 1)
        
    def test_record_requests(self):
        self.health.record_request()
        self.health.record_error()
        self.health.record_tool_call("ping", 10.0, True)
        self.health.record_tool_call("fail", 5.0, False)
        self.health.record_ai_call("claude", 100.0)
        
        snap = self.health.snapshot()
        self.assertEqual(snap["counters"]["total_requests"], 1)
        self.assertEqual(snap["counters"]["total_errors"], 1)
        self.assertEqual(snap["counters"]["total_tool_calls"], 2)
        self.assertEqual(snap["counters"]["total_ai_calls"], 1)
        self.assertEqual(snap["custom_counters"].get("tool_errors"), 1)
        
    def test_rolling_window(self):
        for i in range(600):  # max history is 500
            self.health.record("window", float(i))
        
        metrics = self.health.get_metric("window", limit=1000)
        self.assertEqual(len(metrics), 500)
        self.assertEqual(metrics[-1]["value"], 599.0)

# ── Plugin Manager Tests ────────────────────────────────────────

class TestPluginManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from james.plugins import PluginManager
        from james.tools.registry import ToolRegistry
        self.registry = ToolRegistry()
        self.plugins = PluginManager(plugins_dir=self.tmpdir, tool_registry=self.registry)
        
    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_dummy_plugin(self, name, valid=True, missing_dep=False):
        plugin_dir = os.path.join(self.tmpdir, name)
        os.makedirs(plugin_dir)
        
        manifest = {
            "name": name,
            "version": "1.0",
            "entry": "main.py",
            "dependencies": ["nonexistent_dep_123"] if missing_dep else []
        }
        
        with open(os.path.join(plugin_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f)
            
        if valid:
            with open(os.path.join(plugin_dir, "main.py"), "w") as f:
                f.write(
"""def register(registry):
    registry.register("dummy_tool", lambda: "ok", "desc")
    return 1
def unregister(registry):
    pass
"""
                )
                
    def test_discover_plugins(self):
        self._create_dummy_plugin("plugin1")
        self._create_dummy_plugin("plugin2")
        discovered = self.plugins.discover()
        self.assertEqual(len(discovered), 2)
        
    def test_load_plugin(self):
        self._create_dummy_plugin("test_plugin")
        self.plugins.discover()
        res = self.plugins.load("test_plugin")
        self.assertEqual(res["status"], "loaded")
        self.assertEqual(res["tools_registered"], 1)
        self.assertIn("dummy_tool", [t["name"] for t in self.registry.list_tools()])
        
    def test_load_missing_dep(self):
        self._create_dummy_plugin("bad_plugin", missing_dep=True)
        self.plugins.discover()
        res = self.plugins.load("bad_plugin")
        self.assertEqual(res["status"], "error")
        self.assertIn("nonexistent_dep_123", res.get("missing", []))
        
    def test_unload_plugin(self):
        self._create_dummy_plugin("test_plugin2")
        self.plugins.discover()
        self.plugins.load("test_plugin2")
        res = self.plugins.unload("test_plugin2")
        self.assertEqual(res["status"], "unloaded")

# ── Multi-Agent Orchestration Tests ─────────────────────────────

class TestMultiAgent(unittest.TestCase):
    def setUp(self):
        from james.agents import AgentCoordinator, Agent, AgentRole, AgentResult
        self.coord = AgentCoordinator()
        
    def test_agent_registration(self):
        agents = self.coord.list_agents()
        self.assertEqual(len(agents), 3) # code, system, research
        
        from james.agents import Agent, AgentRole
        custom = Agent(name="test_worker", role=AgentRole.CUSTOM)
        self.coord.register_agent(custom)
        self.assertEqual(len(self.coord.list_agents()), 4)
        
    def test_auto_route_code(self):
        agent = self.coord._auto_route("Write a python function to bubble sort")
        self.assertEqual(agent.role.value, "code")
        
    def test_auto_route_system(self):
        agent = self.coord._auto_route("Check the local disk space and cpu usage")
        self.assertEqual(agent.role.value, "system")
        
    def test_delegate_explicit(self):
        # By default handler just echoes or sends to orchestrator. Without orch, it echoes.
        res = self.coord.delegate("hello world", agent_name="code_agent")
        self.assertTrue(res.success)
        self.assertEqual(res.agent_id, self.coord.get_agent("code_agent").id)
        self.assertEqual(res.output, {"echo": "hello world"})
        
    def test_custom_handler(self):
        from james.agents import Agent, AgentRole
        custom = Agent(name="custom", role=AgentRole.CUSTOM)
        
        def my_handler(task, orch):
            return f"Handled: {task}"
            
        custom.set_handler(my_handler)
        self.coord.register_agent(custom)
        
        res = self.coord.delegate("foo", agent_name="custom")
        self.assertEqual(res.output, "Handled: foo")


if __name__ == "__main__":
    unittest.main()
