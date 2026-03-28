"""
Tests for Phase 4: File Watcher, Conversation Persistence, and Skill Versioning.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── File Watcher Tests ──────────────────────────────────────────

class TestFileWatcher(unittest.TestCase):
    """Test the file system watcher."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from james.watcher import FileWatcher
        self.watcher = FileWatcher(poll_interval=0.5)

    def tearDown(self):
        self.watcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_watch_rule(self):
        rule_id = self.watcher.watch(self.tmpdir, task="!echo changed")
        self.assertTrue(rule_id.startswith("watch_"))

    def test_list_rules(self):
        self.watcher.watch(self.tmpdir, task="!echo test")
        rules = self.watcher.list_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["directory"], self.tmpdir)

    def test_unwatch(self):
        rule_id = self.watcher.watch(self.tmpdir, task="!echo test")
        self.assertTrue(self.watcher.unwatch(rule_id))
        self.assertEqual(len(self.watcher.list_rules()), 0)

    def test_unwatch_nonexistent(self):
        self.assertFalse(self.watcher.unwatch("nonexistent"))

    def test_start_stop(self):
        self.watcher.start()
        self.assertTrue(self.watcher.is_running)
        self.watcher.stop()
        self.assertFalse(self.watcher.is_running)

    def test_glob_pattern(self):
        rule_id = self.watcher.watch(
            self.tmpdir, task="!echo py changed", patterns=["*.py"]
        )
        rules = self.watcher.list_rules()
        self.assertEqual(rules[0]["patterns"], ["*.py"])

    def test_invalid_directory(self):
        with self.assertRaises(ValueError):
            self.watcher.watch("/nonexistent/path", task="!echo")

    def test_status(self):
        self.watcher.watch(self.tmpdir, task="!echo test")
        status = self.watcher.status()
        self.assertEqual(status["rules"], 1)
        self.assertFalse(status["running"])
        self.watcher.start()
        status = self.watcher.status()
        self.assertTrue(status["running"])

    def test_debounce_setting(self):
        rule_id = self.watcher.watch(
            self.tmpdir, task="!echo", debounce=5.0)
        rules = self.watcher.list_rules()
        self.assertEqual(rules[0]["debounce_seconds"], 5.0)

    def test_multiple_rules(self):
        d1 = tempfile.mkdtemp()
        d2 = tempfile.mkdtemp()
        id1 = self.watcher.watch(d1, task="!echo 1")
        id2 = self.watcher.watch(d2, task="!echo 2")
        self.assertEqual(len(self.watcher.list_rules()), 2)
        self.assertNotEqual(id1, id2)
        import shutil
        shutil.rmtree(d1, ignore_errors=True)
        shutil.rmtree(d2, ignore_errors=True)


# ── Conversation Persistence Tests ──────────────────────────────

class TestConversationStore(unittest.TestCase):
    """Test SQLite conversation persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "convos.db")
        from james.conversations import ConversationStore
        self.store = ConversationStore(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_get(self):
        self.store.save_message("test", "user", "Hello!")
        self.store.save_message("test", "assistant", "Hi there!")
        history = self.store.get_history("test")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "Hello!")
        self.assertEqual(history[1]["role"], "assistant")

    def test_message_limit(self):
        for i in range(30):
            self.store.save_message("test", "user", f"Message {i}")
        history = self.store.get_history("test", limit=10)
        self.assertEqual(len(history), 10)

    def test_metadata(self):
        self.store.save_message("test", "user", "Hi", metadata={"intent": "greeting"})
        history = self.store.get_history("test")
        self.assertIn("metadata", history[0])
        self.assertEqual(history[0]["metadata"]["intent"], "greeting")

    def test_list_conversations(self):
        self.store.save_message("conv1", "user", "Hello")
        self.store.save_message("conv2", "user", "Hi")
        convs = self.store.list_conversations()
        self.assertEqual(len(convs), 2)

    def test_delete_conversation(self):
        self.store.save_message("delete_me", "user", "test")
        self.assertTrue(self.store.delete_conversation("delete_me"))
        convs = self.store.list_conversations()
        self.assertEqual(len(convs), 0)

    def test_delete_nonexistent(self):
        self.assertFalse(self.store.delete_conversation("nope"))

    def test_clear_all(self):
        self.store.save_message("c1", "user", "test1")
        self.store.save_message("c2", "user", "test2")
        deleted = self.store.clear_all()
        self.assertEqual(deleted, 2)

    def test_conversation_info(self):
        self.store.save_message("info_test", "user", "Hello")
        self.store.save_message("info_test", "assistant", "Hi")
        info = self.store.get_conversation_info("info_test")
        self.assertEqual(info["name"], "info_test")
        self.assertEqual(info["message_count"], 2)

    def test_info_nonexistent(self):
        info = self.store.get_conversation_info("nope")
        self.assertIsNone(info)

    def test_chronological_order(self):
        self.store.save_message("order", "user", "First")
        time.sleep(0.01)
        self.store.save_message("order", "user", "Second")
        history = self.store.get_history("order")
        self.assertEqual(history[0]["content"], "First")
        self.assertEqual(history[1]["content"], "Second")

    def test_status(self):
        self.store.save_message("s", "user", "test")
        status = self.store.status()
        self.assertEqual(status["conversations"], 1)
        self.assertEqual(status["total_messages"], 1)

    def test_persistence(self):
        self.store.save_message("persist", "user", "saved")
        # Create new instance pointing at same DB
        from james.conversations import ConversationStore
        store2 = ConversationStore(db_path=self.db_path)
        history = store2.get_history("persist")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "saved")


# ── Skill Versioning Tests ──────────────────────────────────────

class TestSkillVersionManager(unittest.TestCase):
    """Test skill versioning with rollback."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from james.skill_versions import SkillVersionManager
        self.svm = SkillVersionManager(versions_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_version(self):
        v = self.svm.save_version("test_skill", {"name": "test", "steps": []})
        self.assertEqual(v, 1)

    def test_incremental_versions(self):
        self.svm.save_version("s1", {"v": 1})
        self.svm.save_version("s1", {"v": 2})
        self.svm.save_version("s1", {"v": 3})
        self.assertEqual(self.svm.get_current_version("s1"), 3)

    def test_get_version(self):
        self.svm.save_version("s1", {"data": "v1"}, description="first")
        sv = self.svm.get_version("s1", 1)
        self.assertIsNotNone(sv)
        self.assertEqual(sv.skill_data["data"], "v1")
        self.assertEqual(sv.description, "first")

    def test_get_latest(self):
        self.svm.save_version("s1", {"data": "old"})
        self.svm.save_version("s1", {"data": "new"})
        sv = self.svm.get_version("s1")  # no version = latest
        self.assertEqual(sv.skill_data["data"], "new")

    def test_rollback(self):
        self.svm.save_version("s1", {"data": "v1"}, description="original")
        self.svm.save_version("s1", {"data": "v2"}, description="updated")
        restored = self.svm.rollback("s1", 1)
        self.assertEqual(restored["data"], "v1")
        # Should be saved as v3
        self.assertEqual(self.svm.get_current_version("s1"), 3)

    def test_rollback_nonexistent(self):
        result = self.svm.rollback("nonexistent", 1)
        self.assertIsNone(result)

    def test_get_history(self):
        self.svm.save_version("s1", {"d": 1}, "first")
        self.svm.save_version("s1", {"d": 2}, "second")
        history = self.svm.get_history("s1")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["version"], 1)
        self.assertEqual(history[1]["version"], 2)

    def test_list_versioned_skills(self):
        self.svm.save_version("alpha", {"x": 1})
        self.svm.save_version("beta", {"y": 2})
        skills = self.svm.list_versioned_skills()
        names = [s["name"] for s in skills]
        self.assertIn("alpha", names)
        self.assertIn("beta", names)

    def test_delete_versions(self):
        self.svm.save_version("delete_me", {"x": 1})
        self.svm.save_version("delete_me", {"x": 2})
        deleted = self.svm.delete_versions("delete_me")
        self.assertEqual(deleted, 2)
        self.assertEqual(self.svm.get_current_version("delete_me"), 0)

    def test_persistence(self):
        self.svm.save_version("persist", {"data": "keep"})
        from james.skill_versions import SkillVersionManager
        svm2 = SkillVersionManager(versions_dir=self.tmpdir)
        sv = svm2.get_version("persist", 1)
        self.assertIsNotNone(sv)
        self.assertEqual(sv.skill_data["data"], "keep")

    def test_status(self):
        self.svm.save_version("s1", {"x": 1})
        self.svm.save_version("s1", {"x": 2})
        self.svm.save_version("s2", {"y": 1})
        status = self.svm.status()
        self.assertEqual(status["versioned_skills"], 2)
        self.assertEqual(status["total_versions"], 3)


# ── Phase 4 Tool Tests ──────────────────────────────────────────

class TestPhase4Tools(unittest.TestCase):
    """Test Phase 4 tool functions."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from james.watcher import FileWatcher
        from james.conversations import ConversationStore
        from james.skill_versions import SkillVersionManager
        from james.tools.registry import set_watcher, set_conversations, set_skill_versions

        self.watcher = FileWatcher()
        self.convos = ConversationStore(
            db_path=os.path.join(self.tmpdir, "conv.db"))
        self.svm = SkillVersionManager(
            versions_dir=os.path.join(self.tmpdir, "versions"))

        set_watcher(self.watcher)
        set_conversations(self.convos)
        set_skill_versions(self.svm)

    def tearDown(self):
        self.watcher.stop()
        from james.tools.registry import set_watcher, set_conversations, set_skill_versions
        set_watcher(None)
        set_conversations(None)
        set_skill_versions(None)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tool_watch_directory(self):
        from james.tools.registry import _tool_watch_directory
        d = tempfile.mkdtemp()
        result = _tool_watch_directory(directory=d, task="!echo changed")
        self.assertEqual(result["status"], "watching")
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_tool_list_watches(self):
        from james.tools.registry import _tool_list_watches
        result = _tool_list_watches()
        self.assertIn("rules", result)

    def test_tool_conversation_history(self):
        from james.tools.registry import _tool_conversation_history
        self.convos.save_message("web_default", "user", "hello")
        result = _tool_conversation_history(conversation="web_default")
        self.assertEqual(result["count"], 1)

    def test_tool_list_conversations(self):
        from james.tools.registry import _tool_list_conversations
        self.convos.save_message("test", "user", "hi")
        result = _tool_list_conversations()
        self.assertEqual(result["count"], 1)

    def test_tool_skill_history(self):
        from james.tools.registry import _tool_skill_history
        self.svm.save_version("test_skill", {"x": 1}, "initial")
        result = _tool_skill_history(skill_name="test_skill")
        self.assertEqual(result["current"], 1)

    def test_tool_skill_rollback(self):
        from james.tools.registry import _tool_skill_rollback
        self.svm.save_version("rb_skill", {"v": 1}, "v1")
        self.svm.save_version("rb_skill", {"v": 2}, "v2")
        result = _tool_skill_rollback(skill_name="rb_skill", version=1)
        self.assertEqual(result["status"], "rolled_back")


if __name__ == "__main__":
    unittest.main()
