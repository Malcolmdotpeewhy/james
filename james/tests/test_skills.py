"""
JAMES Unit Tests — Skill System
"""
import tempfile

from james.skills.skill import Skill, SkillStore


class TestSkill:
    def test_defaults(self):
        skill = Skill(id="test", name="Test Skill")
        assert skill.confidence_score == 0.5
        assert skill.execution_count == 0
        assert skill.success_rate == 0.0

    def test_record_execution_success(self):
        skill = Skill(id="test")
        skill.record_execution(success=True, duration_ms=100)
        assert skill.execution_count == 1
        assert skill.success_count == 1
        assert skill.total_duration_ms == 100
        # Laplace smoothing: (1+1)/(1+2) = 0.6667
        assert abs(skill.confidence_score - 0.6667) < 0.01

    def test_record_execution_failure(self):
        skill = Skill(id="test")
        skill.record_execution(success=False, duration_ms=50)
        assert skill.execution_count == 1
        assert skill.success_count == 0
        # Laplace smoothing: (0+1)/(1+2) = 0.3333
        assert abs(skill.confidence_score - 0.3333) < 0.01

    def test_confidence_converges(self):
        skill = Skill(id="test")
        for _ in range(100):
            skill.record_execution(success=True)
        # After 100 successes: (100+1)/(100+2) ~= 0.99
        assert skill.confidence_score > 0.95

    def test_success_rate(self):
        skill = Skill(id="test")
        skill.record_execution(success=True)
        skill.record_execution(success=True)
        skill.record_execution(success=False)
        assert abs(skill.success_rate - 0.6667) < 0.01

    def test_avg_duration(self):
        skill = Skill(id="test")
        skill.record_execution(success=True, duration_ms=100)
        skill.record_execution(success=True, duration_ms=200)
        assert skill.avg_duration_ms == 150

    def test_serialization_roundtrip(self):
        skill = Skill(id="test", name="Test", description="A test skill",
                      methods=["CLI", "API"], tags=["test", "validation"])
        skill.record_execution(success=True, duration_ms=42)
        d = skill.to_dict()
        restored = Skill.from_dict(d)
        assert restored.id == "test"
        assert restored.name == "Test"
        assert restored.methods == ["CLI", "API"]
        assert restored.execution_count == 1
        assert restored.success_count == 1

    def test_log_optimization(self):
        skill = Skill(id="test")
        skill.log_optimization("Added caching", improvement=0.15)
        assert len(skill.optimization_log) == 1
        assert skill.optimization_log[0]["improvement"] == 0.15

    def test_preferred_method(self):
        skill = Skill(id="test", methods=["API", "CLI"])
        assert skill.preferred_method == "API"

    def test_preferred_method_empty(self):
        skill = Skill(id="test", methods=[])
        assert skill.preferred_method == "CLI"


class TestSkillStore:
    def test_create_and_get(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)
            skill = Skill(id="s1", name="Skill 1")
            store.create(skill)
            assert store.count == 1
            got = store.get("s1")
            assert got is not None
            assert got.name == "Skill 1"

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)
            store.create(Skill(id="s1", name="Skill 1"))
            # Reload from disk
            store2 = SkillStore(td)
            assert store2.count == 1
            assert store2.get("s1").name == "Skill 1"

    def test_update(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)
            skill = Skill(id="s1", name="Original")
            store.create(skill)
            skill.name = "Updated"
            store.update(skill)
            got = store.get("s1")
            assert got.name == "Updated"

    def test_delete(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)
            store.create(Skill(id="s1", name="Skill 1"))
            assert store.delete("s1") is True
            assert store.count == 0
            assert store.get("s1") is None

    def test_delete_nonexistent(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)
            assert store.delete("nope") is False

    def test_list_sorted_by_confidence(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)
            s1 = Skill(id="s1", name="Low", confidence_score=0.3)
            s2 = Skill(id="s2", name="High", confidence_score=0.9)
            store.create(s1)
            store.create(s2)
            listed = store.list_all()
            assert listed[0].id == "s2"
            assert listed[1].id == "s1"

    def test_search(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)
            store.create(Skill(id="s1", name="File Operations", tags=["filesystem"]))
            store.create(Skill(id="s2", name="Network Calls", tags=["http"]))
            results = store.search("file")
            assert len(results) == 1
            assert results[0].id == "s1"

    def test_search_by_tag(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)
            store.create(Skill(id="s1", name="Foo", tags=["http", "api"]))
            results = store.search("http")
            assert len(results) == 1

    def test_find_by_method(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)
            store.create(Skill(id="s1", methods=["CLI"]))
            store.create(Skill(id="s2", methods=["API"]))
            found = store.find_by_method("API")
            assert len(found) == 1
            assert found[0].id == "s2"
