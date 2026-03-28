"""
JAMES Multi-Agent Orchestration — Agent-to-agent delegation framework.

Enables JAMES to spawn specialized sub-agents for domain-specific tasks.
Each agent has an isolated context, defined capabilities, and reports
results back to the coordinator.

Agent Types:
  - CodeAgent: Code analysis, refactoring, generation
  - ResearchAgent: Web search, document analysis
  - SystemAgent: OS operations, monitoring, maintenance
  - CustomAgent: User-defined with custom toolsets
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("james.agents")


class AgentRole(Enum):
    COORDINATOR = "coordinator"
    CODE = "code"
    RESEARCH = "research"
    SYSTEM = "system"
    CUSTOM = "custom"


class AgentState(Enum):
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentMessage:
    """Message passed between agents."""
    sender: str
    recipient: str
    content: Any
    message_type: str = "task"  # task, result, query, status
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "content": self.content,
            "type": self.message_type,
            "timestamp": self.timestamp,
        }


@dataclass
class AgentResult:
    """Result from an agent's work."""
    agent_id: str
    success: bool
    output: Any = None
    error: str = ""
    duration_ms: float = 0
    metadata: dict = field(default_factory=dict)


class Agent:
    """
    A specialized sub-agent with defined capabilities.

    Each agent has:
      - A role defining its domain
      - A set of allowed tools
      - An isolated message inbox
      - State tracking
    """

    def __init__(self, name: str, role: AgentRole,
                 tools: list[str] = None,
                 description: str = ""):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.role = role
        self.tools = tools or []
        self.description = description
        self.state = AgentState.IDLE
        self._inbox: list[AgentMessage] = []
        self._results: list[AgentResult] = []
        self._created_at = time.time()
        self._handler: Optional[Callable] = None

    def set_handler(self, handler: Callable) -> None:
        """Set the function that handles tasks for this agent."""
        self._handler = handler

    def receive(self, message: AgentMessage) -> None:
        """Receive a message from another agent."""
        self._inbox.append(message)

    def process(self, orchestrator=None) -> Optional[AgentResult]:
        """Process the next message in the inbox."""
        if not self._inbox:
            return None

        message = self._inbox.pop(0)
        self.state = AgentState.WORKING
        start = time.time()

        try:
            if self._handler:
                output = self._handler(message.content, orchestrator)
            else:
                output = self._default_handler(message.content, orchestrator)

            duration = (time.time() - start) * 1000
            result = AgentResult(
                agent_id=self.id,
                success=True,
                output=output,
                duration_ms=duration,
            )

        except Exception as e:
            duration = (time.time() - start) * 1000
            result = AgentResult(
                agent_id=self.id,
                success=False,
                error=str(e),
                duration_ms=duration,
            )

        self._results.append(result)
        self.state = AgentState.COMPLETED if result.success else AgentState.FAILED
        return result

    def _default_handler(self, task: Any, orchestrator=None) -> Any:
        """Default task handler — delegates to orchestrator.run()."""
        if orchestrator and isinstance(task, (str, dict)):
            graph = orchestrator.run(task)
            return {
                "graph": graph.name,
                "nodes": len(graph.nodes),
                "status": graph.status.value if hasattr(graph.status, 'value') else str(graph.status),
            }
        return {"echo": task}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role.value,
            "state": self.state.value,
            "tools": self.tools,
            "description": self.description,
            "pending_messages": len(self._inbox),
            "completed_tasks": len(self._results),
        }


class AgentCoordinator:
    """
    Coordinates multiple agents for complex multi-step tasks.

    The coordinator:
      1. Decomposes complex tasks into agent-appropriate subtasks
      2. Routes subtasks to specialized agents
      3. Collects and synthesizes results
      4. Handles inter-agent communication
    """

    def __init__(self, orchestrator=None):
        self.orch = orchestrator
        self._agents: dict[str, Agent] = {}
        self._message_log: list[dict] = []
        self._delegation_count = 0

        # Register built-in agent archetypes
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default agent archetypes."""
        self.register_agent(Agent(
            name="code_agent",
            role=AgentRole.CODE,
            tools=["file_read", "file_write", "file_list", "run_command",
                   "rag_search", "vector_search"],
            description="Handles code analysis, refactoring, and generation",
        ))

        self.register_agent(Agent(
            name="system_agent",
            role=AgentRole.SYSTEM,
            tools=["run_command", "system_info", "env_info", "process_list",
                   "network_info", "disk_info"],
            description="Handles OS operations, monitoring, and maintenance",
        ))

        self.register_agent(Agent(
            name="research_agent",
            role=AgentRole.RESEARCH,
            tools=["rag_search", "rag_ingest", "vector_search",
                   "memory_recall", "memory_save"],
            description="Handles information retrieval and document analysis",
        ))

    # ── Agent Management ─────────────────────────────────────────

    def register_agent(self, agent: Agent) -> str:
        """Register an agent."""
        self._agents[agent.name] = agent
        logger.debug(f"Agent registered: {agent.name} ({agent.role.value})")
        return agent.id

    def unregister_agent(self, name: str) -> bool:
        """Remove an agent."""
        return self._agents.pop(name, None) is not None

    def get_agent(self, name: str) -> Optional[Agent]:
        return self._agents.get(name)

    def list_agents(self) -> list[dict]:
        return [a.to_dict() for a in self._agents.values()]

    # ── Delegation ───────────────────────────────────────────────

    def delegate(self, task: Any, agent_name: str = None,
                 role: AgentRole = None) -> AgentResult:
        """
        Delegate a task to a specific agent or auto-route by role.

        Args:
            task: The task to delegate (string or dict).
            agent_name: Specific agent to use.
            role: Agent role to route to (if agent_name not specified).

        Returns:
            AgentResult from the handling agent.
        """
        # Find the right agent
        agent = None
        if agent_name:
            agent = self._agents.get(agent_name)
        elif role:
            for a in self._agents.values():
                if a.role == role and a.state == AgentState.IDLE:
                    agent = a
                    break

        if not agent:
            # Auto-route based on task content
            agent = self._auto_route(task)

        if not agent:
            return AgentResult(
                agent_id="coordinator",
                success=False,
                error="No suitable agent found for this task",
            )

        # Create and send message
        message = AgentMessage(
            sender="coordinator",
            recipient=agent.name,
            content=task,
            message_type="task",
        )
        agent.receive(message)
        self._message_log.append(message.to_dict())
        self._delegation_count += 1

        # Process immediately
        result = agent.process(orchestrator=self.orch)
        if result is None:
            result = AgentResult(
                agent_id=agent.id,
                success=False,
                error="Agent returned no result",
            )

        # Reset agent state
        agent.state = AgentState.IDLE

        logger.info(
            f"Delegation to {agent.name}: "
            f"{'success' if result.success else 'failed'} "
            f"({result.duration_ms:.0f}ms)"
        )
        return result

    def _auto_route(self, task: Any) -> Optional[Agent]:
        """Automatically route a task to the best agent."""
        task_str = str(task).lower()

        # Simple keyword-based routing
        code_keywords = {"code", "function", "class", "file", "refactor",
                         "debug", "import", "module", "script", "test"}
        system_keywords = {"system", "process", "disk", "network", "cpu",
                           "memory", "install", "service", "restart"}
        research_keywords = {"search", "find", "lookup", "document",
                             "analyze", "summarize", "information"}

        task_words = set(task_str.split())

        scores = {
            AgentRole.CODE: len(task_words & code_keywords),
            AgentRole.SYSTEM: len(task_words & system_keywords),
            AgentRole.RESEARCH: len(task_words & research_keywords),
        }

        best_role = max(scores, key=scores.get)
        if scores[best_role] == 0:
            # Default to system agent
            best_role = AgentRole.SYSTEM

        for agent in self._agents.values():
            if agent.role == best_role:
                return agent

        return None

    # ── Status ───────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "agents": len(self._agents),
            "total_delegations": self._delegation_count,
            "agents_list": self.list_agents(),
            "recent_messages": self._message_log[-10:],
        }
