"""
JAMES Unit Tests -- Memory System
"""
import gc
import os
import shutil
import tempfile

import pytest
from james.memory.store import MemoryStore


@pytest.fixture
def memory():
    td = tempfile.mkdtemp(prefix="james_mem_test_")
    db_path = os.path.join(td, "test.db")
    store = MemoryStore(db_path)
    yield store
    del store
    gc.collect()
    shutil.rmtree(td, ignore_errors=True)


class TestShortTermMemory:
    def test_set_and_get(self, memory):
        memory.st_set("task", "running")
        assert memory.st_get("task") == "running"

    def test_get_default(self, memory):
        assert memory.st_get("missing", "fallback") == "fallback"

    def test_delete(self, memory):
        memory.st_set("k", "v")
        memory.st_delete("k")
        assert memory.st_get("k") is None

    def test_clear(self, memory):
        memory.st_set("a", 1)
        memory.st_set("b", 2)
        memory.st_clear()
        assert memory.st_dump() == {}

    def test_dump(self, memory):
        memory.st_set("x", 10)
        memory.st_set("y", 20)
        d = memory.st_dump()
        assert d == {"x": 10, "y": 20}


class TestLongTermMemory:
    def test_set_and_get(self, memory):
        memory.lt_set("config", {"key": "value"})
        result = memory.lt_get("config")
        assert result == {"key": "value"}

    def test_get_missing(self, memory):
        assert memory.lt_get("nope") is None

    def test_overwrite(self, memory):
        memory.lt_set("k", "v1")
        memory.lt_set("k", "v2")
        assert memory.lt_get("k") == "v2"

    def test_list_all(self, memory):
        memory.lt_set("a", 1, category="test")
        memory.lt_set("b", 2, category="test")
        memory.lt_set("c", 3, category="other")
        all_items = memory.lt_list()
        assert len(all_items) == 3

    def test_list_by_category(self, memory):
        memory.lt_set("a", 1, category="test")
        memory.lt_set("b", 2, category="other")
        filtered = memory.lt_list(category="test")
        assert len(filtered) == 1
        assert filtered[0]["key"] == "a"

    def test_delete(self, memory):
        memory.lt_set("k", "v")
        assert memory.lt_delete("k") is True
        assert memory.lt_get("k") is None

    def test_delete_missing(self, memory):
        assert memory.lt_delete("nope") is False


class TestMetrics:
    def test_record_and_retrieve(self, memory):
        memory.record_metric("n1", True, 42.0, node_name="test", layer=1)
        metrics = memory.get_metrics(node_id="n1")
        assert len(metrics) == 1
        assert metrics[0]["success"] == 1
        assert metrics[0]["duration_ms"] == 42.0

    def test_success_rate(self, memory):
        memory.record_metric("n1", True, 10)
        memory.record_metric("n1", True, 20)
        memory.record_metric("n1", False, 30)
        rate = memory.get_success_rate("n1")
        assert abs(rate - 0.6667) < 0.01

    def test_avg_duration(self, memory):
        memory.record_metric("n1", True, 100)
        memory.record_metric("n1", True, 200)
        avg = memory.get_avg_duration("n1")
        assert avg == 150.0

    def test_empty_success_rate(self, memory):
        assert memory.get_success_rate("nope") == 0.0


class TestMetaMemory:
    def test_record_and_retrieve(self, memory):
        memory.record_optimization("s1", "Added caching", 0.5, 0.7)
        history = memory.get_optimization_history(skill_id="s1")
        assert len(history) == 1
        assert history[0]["improvement"] == pytest.approx(0.2)

    def test_best_optimizations(self, memory):
        memory.record_optimization("s1", "Caching", 0.5, 0.8)
        memory.record_optimization("s2", "Worse change", 0.5, 0.4)
        memory.record_optimization("s3", "Small tweak", 0.5, 0.55)
        best = memory.get_best_optimizations(limit=2)
        assert len(best) == 2
        assert best[0]["improvement"] > best[1]["improvement"]


class TestSystemMap:
    def test_set_and_get(self, memory):
        memory.map_set("python", r"C:\Python312\python.exe")
        assert memory.map_get("python") == r"C:\Python312\python.exe"

    def test_list(self, memory):
        memory.map_set("python", "/usr/bin/python", category="tool")
        memory.map_set("node", "/usr/bin/node", category="tool")
        entries = memory.map_list(category="tool")
        assert len(entries) == 2


class TestStats:
    def test_stats(self, memory):
        memory.st_set("active", True)
        memory.lt_set("config", {})
        memory.record_metric("n1", True, 10)
        memory.record_optimization("s1", "test", 0.5, 0.6)
        memory.map_set("tool", "/path")

        stats = memory.get_stats()
        assert stats["short_term_entries"] == 1
        assert stats["long_term_entries"] == 1
        assert stats["metrics_recorded"] == 1
        assert stats["optimizations_logged"] == 1
        assert stats["system_map_entries"] == 1
