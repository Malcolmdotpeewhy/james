"""
JAMES Execution Graph Engine

Represents tasks as Directed Acyclic Graphs (DAGs):
  - Nodes = actions with preconditions/postconditions
  - Edges = dependencies
  - Supports parallel execution, dependency resolution,
    critical path compression, and serialization.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class NodeState(Enum):
    """Execution state of a DAG node."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


@dataclass
class NodeResult:
    """Result of executing a single DAG node."""
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    layer_used: Optional[str] = None
    attempts: int = 1


@dataclass
class Node:
    """
    A single action in the execution graph.

    Attributes:
        id:             Unique identifier
        name:           Human-readable action name
        action:         The callable or command string to execute
        layer:          Preferred authority layer (1-5), None = auto-select
        preconditions:  List of callables that must return True before execution
        postconditions: List of callables that must return True after execution
        dependencies:   IDs of nodes that must complete before this node
        state:          Current execution state
        result:         Execution result (populated after run)
        metadata:       Arbitrary key-value metadata
        retry_limit:    Max retry attempts on transient failure
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    action: Any = None  # Callable, command string, or structured dict
    layer: Optional[int] = None
    preconditions: list[Callable] = field(default_factory=list)
    postconditions: list[Callable] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    state: NodeState = NodeState.PENDING
    result: Optional[NodeResult] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    retry_limit: int = 3

    def is_terminal(self) -> bool:
        """Check if node has reached a terminal state."""
        return self.state in (
            NodeState.SUCCESS,
            NodeState.FAILED,
            NodeState.SKIPPED,
            NodeState.ROLLED_BACK,
        )

    def to_dict(self) -> dict:
        """Serialize node to dict (excluding callables)."""
        return {
            "id": self.id,
            "name": self.name,
            "layer": self.layer,
            "dependencies": self.dependencies,
            "state": self.state.value,
            "metadata": self.metadata,
            "retry_limit": self.retry_limit,
            "result": {
                "success": self.result.success,
                "output": str(self.result.output) if self.result.output else None,
                "error": self.result.error,
                "duration_ms": self.result.duration_ms,
                "layer_used": self.result.layer_used,
                "attempts": self.result.attempts,
            } if self.result else None,
        }


class CycleDetectedError(Exception):
    """Raised when a cycle is found in the DAG."""
    pass


class ExecutionGraph:
    """
    Directed Acyclic Graph for task execution.

    Manages nodes, edges, topological ordering,
    parallel scheduling, and critical path analysis.
    """

    def __init__(self, name: str = "unnamed"):
        self.name = name
        self.id = str(uuid.uuid4())[:12]
        self.nodes: dict[str, Node] = {}
        self.created_at = time.time()
        self.completed_at: Optional[float] = None

    # ── Node Management ──────────────────────────────────────────

    def add_node(self, node: Node) -> Node:
        """Add a node to the graph. Returns the node."""
        if node.id in self.nodes:
            raise ValueError(f"Duplicate node ID: {node.id}")
        self.nodes[node.id] = node
        return node

    def add_dependency(self, from_id: str, to_id: str) -> None:
        """Add a dependency: `to_id` depends on `from_id`."""
        if from_id not in self.nodes:
            raise KeyError(f"Source node not found: {from_id}")
        if to_id not in self.nodes:
            raise KeyError(f"Target node not found: {to_id}")
        if from_id not in self.nodes[to_id].dependencies:
            self.nodes[to_id].dependencies.append(from_id)

    def get_node(self, node_id: str) -> Node:
        """Get node by ID."""
        if node_id not in self.nodes:
            raise KeyError(f"Node not found: {node_id}")
        return self.nodes[node_id]

    # ── Graph Analysis ───────────────────────────────────────────

    def _validate_no_cycles(self) -> None:
        """Kahn's algorithm for cycle detection."""
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.dependencies:
                if dep in in_degree:
                    # dep -> node, so node has in_degree from dep
                    pass
            # Actually compute: for each node, its dependencies are incoming edges
        # Rebuild adjacency for Kahn's: edge from dep -> node
        adj: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        in_deg: dict[str, int] = {nid: 0 for nid in self.nodes}

        for node in self.nodes.values():
            for dep_id in node.dependencies:
                if dep_id in self.nodes:
                    adj[dep_id].append(node.id)
                    in_deg[node.id] += 1

        queue = deque([nid for nid, deg in in_deg.items() if deg == 0])
        visited = 0

        while queue:
            nid = queue.popleft()
            visited += 1
            for neighbor in adj[nid]:
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self.nodes):
            raise CycleDetectedError(
                f"Cycle detected in graph '{self.name}': "
                f"visited {visited}/{len(self.nodes)} nodes"
            )

    def topological_sort(self) -> list[str]:
        """
        Returns node IDs in topological order.
        Raises CycleDetectedError if graph contains cycles.
        """
        self._validate_no_cycles()

        adj: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        in_deg: dict[str, int] = {nid: 0 for nid in self.nodes}

        for node in self.nodes.values():
            for dep_id in node.dependencies:
                if dep_id in self.nodes:
                    adj[dep_id].append(node.id)
                    in_deg[node.id] += 1

        queue = deque([nid for nid, deg in in_deg.items() if deg == 0])
        order: list[str] = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for neighbor in adj[nid]:
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)

        return order

    def get_ready_nodes(self) -> list[Node]:
        """
        Get all nodes whose dependencies are satisfied
        and are not yet running or complete.
        These can be executed in parallel.
        """
        ready = []
        for node in self.nodes.values():
            if node.state != NodeState.PENDING:
                continue
            deps_met = all(
                self.nodes[dep_id].state == NodeState.SUCCESS
                for dep_id in node.dependencies
                if dep_id in self.nodes
            )
            if deps_met:
                ready.append(node)
        return ready

    def get_critical_path(self) -> list[str]:
        """
        Compute the critical path (longest path through the DAG).
        Uses estimated durations from metadata or defaults to 1.
        """
        order = self.topological_sort()
        dist: dict[str, float] = {nid: 0.0 for nid in self.nodes}
        parent: dict[str, Optional[str]] = {nid: None for nid in self.nodes}

        for nid in order:
            node = self.nodes[nid]
            node_cost = node.metadata.get("estimated_duration", 1.0)
            for dep_id in node.dependencies:
                if dep_id in self.nodes:
                    new_dist = dist[dep_id] + node_cost
                    if new_dist > dist[nid]:
                        dist[nid] = new_dist
                        parent[nid] = dep_id

        # Find the node with max distance
        if not dist:
            return []
        end_node = max(dist, key=dist.get)  # type: ignore[arg-type]
        path: list[str] = []
        current: Optional[str] = end_node
        while current is not None:
            path.append(current)
            current = parent[current]
        path.reverse()
        return path

    # ── State Management ─────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        """Check if all nodes have reached terminal state."""
        return all(n.is_terminal() for n in self.nodes.values())

    @property
    def has_failures(self) -> bool:
        """Check if any node has failed."""
        return any(n.state == NodeState.FAILED for n in self.nodes.values())

    @property
    def progress(self) -> tuple[int, int]:
        """Return (completed, total) node counts."""
        completed = sum(1 for n in self.nodes.values() if n.is_terminal())
        return completed, len(self.nodes)

    def reset(self) -> None:
        """Reset all nodes to PENDING state."""
        for node in self.nodes.values():
            node.state = NodeState.PENDING
            node.result = None
        self.completed_at = None

    # ── Serialization ────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize entire graph to dict."""
        return {
            "name": self.name,
            "id": self.id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionGraph":
        """Deserialize from dict (nodes restored without callables)."""
        graph = cls(name=data.get("name", "restored"))
        graph.id = data.get("id", graph.id)
        graph.created_at = data.get("created_at", graph.created_at)
        graph.completed_at = data.get("completed_at")

        for nid, ndata in data.get("nodes", {}).items():
            result = None
            if ndata.get("result"):
                r = ndata["result"]
                result = NodeResult(
                    success=r["success"],
                    output=r.get("output"),
                    error=r.get("error"),
                    duration_ms=r.get("duration_ms", 0),
                    layer_used=r.get("layer_used"),
                    attempts=r.get("attempts", 1),
                )
            node = Node(
                id=ndata["id"],
                name=ndata.get("name", ""),
                layer=ndata.get("layer"),
                dependencies=ndata.get("dependencies", []),
                state=NodeState(ndata.get("state", "pending")),
                result=result,
                metadata=ndata.get("metadata", {}),
                retry_limit=ndata.get("retry_limit", 3),
            )
            graph.nodes[node.id] = node

        return graph

    def __repr__(self) -> str:
        done, total = self.progress
        return f"<ExecutionGraph '{self.name}' [{done}/{total}] id={self.id}>"
