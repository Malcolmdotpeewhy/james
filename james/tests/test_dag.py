"""
JAMES Unit Tests — DAG Engine
"""
import pytest
from james.dag import ExecutionGraph, Node, NodeState, NodeResult, CycleDetectedError


class TestNode:
    def test_default_state(self):
        node = Node(name="test")
        assert node.state == NodeState.PENDING
        assert node.result is None
        assert not node.is_terminal()

    def test_terminal_states(self):
        for state in (NodeState.SUCCESS, NodeState.FAILED, NodeState.SKIPPED, NodeState.ROLLED_BACK):
            node = Node(name="test")
            node.state = state
            assert node.is_terminal()

    def test_non_terminal_states(self):
        for state in (NodeState.PENDING, NodeState.READY, NodeState.RUNNING):
            node = Node(name="test")
            node.state = state
            assert not node.is_terminal()

    def test_to_dict_no_result(self):
        node = Node(id="abc", name="test_node", layer=1)
        d = node.to_dict()
        assert d["id"] == "abc"
        assert d["name"] == "test_node"
        assert d["layer"] == 1
        assert d["result"] is None

    def test_to_dict_with_result(self):
        node = Node(id="abc", name="test_node")
        node.result = NodeResult(success=True, output="hello", duration_ms=42.0, attempts=2)
        d = node.to_dict()
        assert d["result"]["success"] is True
        assert d["result"]["duration_ms"] == 42.0
        assert d["result"]["attempts"] == 2


class TestExecutionGraph:
    def test_add_node(self):
        graph = ExecutionGraph(name="test")
        node = Node(id="n1", name="step 1")
        graph.add_node(node)
        assert "n1" in graph.nodes
        assert graph.get_node("n1") is node

    def test_duplicate_node_raises(self):
        graph = ExecutionGraph(name="test")
        graph.add_node(Node(id="n1", name="step 1"))
        with pytest.raises(ValueError, match="Duplicate"):
            graph.add_node(Node(id="n1", name="step 1 again"))

    def test_add_dependency(self):
        graph = ExecutionGraph(name="test")
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        graph.add_dependency("a", "b")
        assert "a" in graph.nodes["b"].dependencies

    def test_topological_sort_linear(self):
        graph = ExecutionGraph(name="linear")
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        graph.add_node(Node(id="c", name="C"))
        graph.add_dependency("a", "b")
        graph.add_dependency("b", "c")
        order = graph.topological_sort()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_topological_sort_diamond(self):
        graph = ExecutionGraph(name="diamond")
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        graph.add_node(Node(id="c", name="C"))
        graph.add_node(Node(id="d", name="D"))
        graph.add_dependency("a", "b")
        graph.add_dependency("a", "c")
        graph.add_dependency("b", "d")
        graph.add_dependency("c", "d")
        order = graph.topological_sort()
        assert order[0] == "a"
        assert order[-1] == "d"

    def test_cycle_detection(self):
        graph = ExecutionGraph(name="cyclic")
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        graph.add_node(Node(id="c", name="C"))
        graph.add_dependency("a", "b")
        graph.add_dependency("b", "c")
        graph.add_dependency("c", "a")
        with pytest.raises(CycleDetectedError):
            graph.topological_sort()

    def test_get_ready_nodes(self):
        graph = ExecutionGraph(name="ready")
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        graph.add_dependency("a", "b")
        ready = graph.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "a"

    def test_get_ready_nodes_after_completion(self):
        graph = ExecutionGraph(name="ready2")
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        graph.add_dependency("a", "b")
        graph.nodes["a"].state = NodeState.SUCCESS
        ready = graph.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "b"

    def test_parallel_ready_nodes(self):
        graph = ExecutionGraph(name="parallel")
        graph.add_node(Node(id="root", name="Root"))
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        graph.add_node(Node(id="c", name="C"))
        graph.add_dependency("root", "a")
        graph.add_dependency("root", "b")
        graph.add_dependency("root", "c")
        graph.nodes["root"].state = NodeState.SUCCESS
        ready = graph.get_ready_nodes()
        assert len(ready) == 3

    def test_progress(self):
        graph = ExecutionGraph(name="progress")
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        graph.nodes["a"].state = NodeState.SUCCESS
        done, total = graph.progress
        assert done == 1
        assert total == 2

    def test_is_complete(self):
        graph = ExecutionGraph(name="complete")
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        assert not graph.is_complete
        graph.nodes["a"].state = NodeState.SUCCESS
        graph.nodes["b"].state = NodeState.FAILED
        assert graph.is_complete

    def test_has_failures(self):
        graph = ExecutionGraph(name="fail")
        graph.add_node(Node(id="a", name="A"))
        graph.nodes["a"].state = NodeState.FAILED
        assert graph.has_failures

    def test_serialization_roundtrip(self):
        graph = ExecutionGraph(name="serial")
        graph.add_node(Node(id="a", name="A", layer=1, metadata={"key": "val"}))
        graph.add_node(Node(id="b", name="B"))
        graph.add_dependency("a", "b")
        graph.nodes["a"].state = NodeState.SUCCESS
        graph.nodes["a"].result = NodeResult(success=True, output="ok", duration_ms=10)

        d = graph.to_dict()
        restored = ExecutionGraph.from_dict(d)
        assert restored.name == "serial"
        assert "a" in restored.nodes
        assert restored.nodes["a"].state == NodeState.SUCCESS
        assert restored.nodes["a"].result.output == "ok"
        assert "a" in restored.nodes["b"].dependencies

    def test_reset(self):
        graph = ExecutionGraph(name="reset")
        graph.add_node(Node(id="a", name="A"))
        graph.nodes["a"].state = NodeState.SUCCESS
        graph.nodes["a"].result = NodeResult(success=True)
        graph.reset()
        assert graph.nodes["a"].state == NodeState.PENDING
        assert graph.nodes["a"].result is None

    def test_critical_path(self):
        graph = ExecutionGraph(name="crit")
        graph.add_node(Node(id="a", name="A", metadata={"estimated_duration": 5}))
        graph.add_node(Node(id="b", name="B", metadata={"estimated_duration": 10}))
        graph.add_node(Node(id="c", name="C", metadata={"estimated_duration": 2}))
        graph.add_dependency("a", "b")
        graph.add_dependency("a", "c")
        path = graph.get_critical_path()
        assert "a" in path
        assert "b" in path  # b is slower than c


    def test_critical_path_correctness(self):
        graph = ExecutionGraph(name="critical_path")
        n1 = Node(id="a", name="A")
        n1.metadata["estimated_duration"] = 5.0

        n2 = Node(id="b", name="B")
        n2.metadata["estimated_duration"] = 10.0

        graph.add_node(n1)
        graph.add_node(n2)

        # With no dependencies, the critical path is just the node with the longest duration
        path = graph.get_critical_path()
        assert path == ["b"]

        # If A depends on B, path is [B, A]
        graph.add_dependency("a", "b")
        path = graph.get_critical_path()
        assert path == ["a", "b"] or path == ["b", "a"] # Topological sort may vary, but critical path is both

    def test_update_skipped_nodes(self):
        graph = ExecutionGraph(name="skipped_test")
        graph.add_node(Node(id="a", name="A"))
        graph.add_node(Node(id="b", name="B"))
        graph.add_node(Node(id="c", name="C"))

        graph.add_dependency("a", "b")
        graph.add_dependency("b", "c")

        graph.nodes["a"].state = NodeState.FAILED
        graph.update_skipped_nodes()

        assert graph.nodes["b"].state == NodeState.SKIPPED
        assert graph.nodes["b"].result.success is False
        assert graph.nodes["c"].state == NodeState.SKIPPED
        assert graph.nodes["c"].result.success is False
