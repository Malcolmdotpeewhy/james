"""
JAMES Strategic Orchestrator

The brain of JAMES. Responsibilities:
  - Accept intent (task description or structured dict)
  - Decompose into a DAG of executable nodes
  - Select execution layer per node
  - Manage the full lifecycle:
    Plan → Validate → Execute → Verify → Learn → Improve → Repeat
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from james.ai.plan_validator import PlanValidator
from james.dag import ExecutionGraph, Node, NodeResult, NodeState
from james.failure import FailureTracker, FailureContext
from james.layers import LayerLevel, LayerRegistry
from james.layers.native import NativeLayer
from james.layers.application import ApplicationLayer
from james.layers.ui_cognitive import UICognitiveLayer
from james.layers.synthetic import SyntheticLayer
from james.layers.environmental import EnvironmentalLayer
from james.memory.store import MemoryStore, ExecutionMetric
from james.optimizer import Optimizer
from james.security import AuditEntry, AuditLog, OpClass, RestorePointManager, SecurityPolicy
from james.skills.skill import SkillStore
from james.verification import Condition, VerificationEngine

logger = logging.getLogger("james.orchestrator")


def _get_project_root() -> str:
    """Resolve project root from this file's location."""
    return str(Path(__file__).resolve().parent.parent)


class Orchestrator:
    """
    Central orchestration engine for JAMES.
    Deterministic execution with verification guarantees.
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        self._root = project_root or _get_project_root()
        self._james_dir = os.path.join(self._root, "james")

        # ── Initialize subsystems ────────────────────────────
        config = config_path or os.path.join(
            self._root, ".antigravity", "config.yaml"
        )

        # Security & Audit
        self.security = SecurityPolicy(config)
        self.audit = AuditLog(
            os.path.join(self._james_dir, "audit", "audit.jsonl")
        )
        self.restore = RestorePointManager(
            os.path.join(self._james_dir, "restore_points")
        )

        # Memory
        self.memory = MemoryStore(
            os.path.join(self._james_dir, "memory", "james.db")
        )

        # Skills
        self.skills = SkillStore(
            os.path.join(self._james_dir, "skills", "store")
        )

        # Verification
        self.verifier = VerificationEngine()

        # Failure tracking
        self.failures = FailureTracker()

        # Optimizer
        self.optimizer = Optimizer(self.memory, self.skills)

        # Authority layers
        self.layers = LayerRegistry()
        self._register_layers()

        # Active graphs
        self._active_graph: Optional[ExecutionGraph] = None

        # Tool registry
        from james.tools import get_registry
        self.tools = get_registry()
        self.tools.set_memory(self.memory)

        # Plan Validator
        self.plan_validator = PlanValidator(
            tool_registry=self.tools,
            security_policy=self.security,
        )

        # Task Scheduler
        from james.scheduler import TaskScheduler, TaskSchedule
        self.scheduler = TaskScheduler(
            db_path=os.path.join(self._james_dir, "memory", "scheduler.db"),
            orchestrator=self,
        )
        self.scheduler.start()

        # Inject scheduler into tool registry for AI access
        from james.tools.registry import set_scheduler
        set_scheduler(self.scheduler)

        # Vector Store (semantic memory search)
        from james.memory.vectors import VectorStore
        self.vectors = VectorStore(
            db_dir=os.path.join(self._james_dir, "memory"),
        )

        # RAG Pipeline (document retrieval)
        from james.rag.pipeline import RAGPipeline
        self.rag = RAGPipeline(
            db_dir=os.path.join(self._james_dir, "memory", "rag"),
        )

        # Capability Expander (autonomous self-healing)
        from james.evolution.expander import CapabilityExpander
        self.expander = CapabilityExpander(
            orchestrator=self,
            memory=self.memory,
        )

        # Inject RAG & vectors into tool registry
        from james.tools.registry import set_rag, set_vectors
        set_rag(self.rag)
        set_vectors(self.vectors)

        # File Watcher (watch mode)
        from james.watcher import FileWatcher
        self.watcher = FileWatcher(orchestrator=self)

        # Conversation Persistence
        from james.conversations import ConversationStore
        self.conversations = ConversationStore(
            db_path=os.path.join(self._james_dir, "memory", "conversations.db"),
        )

        # Skill Versioning
        from james.skill_versions import SkillVersionManager
        self.skill_versions = SkillVersionManager(
            versions_dir=os.path.join(self._james_dir, "skills", ".versions"),
        )

        # Inject Phase 4 into tool registry
        from james.tools.registry import set_watcher, set_conversations, set_skill_versions
        set_watcher(self.watcher)
        set_conversations(self.conversations)
        set_skill_versions(self.skill_versions)

        # ── Phase 5 ────────────────────────────────────────────────

        # Health Monitor
        from james.health import HealthMonitor
        self.health = HealthMonitor(orchestrator=self)
        self.health.start()

        # Plugin Architecture
        from james.plugins import PluginManager
        self.plugins = PluginManager(
            plugins_dir=os.path.join(self._james_dir, "plugins"),
            tool_registry=self.tools,
        )
        self.plugins.load_all()

        # Multi-Agent Coordination
        from james.agents import AgentCoordinator
        self.agents = AgentCoordinator(orchestrator=self)

        # Inject Phase 5 into tool registry
        from james.tools.registry import set_health, set_plugins, set_agents
        set_health(self.health)
        set_plugins(self.plugins)
        set_agents(self.agents)

        # ── Background Tasks ───────────────────────────────────────
        self.tools.register(
            "prune_evolved_tools",
            lambda **kwargs: self.expander.prune_tools(kwargs.get("days_old", 30)),
            "Prune old self-evolved tools older than N days."
        )

        # Schedule the prune_evolved_tools background task to run every 24 hours
        prune_task = {
            "name": "prune_tools",
            "steps": [
                {
                    "name": "prune",
                    "action": {
                        "type": "tool_call",
                        "target": "prune_evolved_tools",
                        "kwargs": {"days_old": 30}
                    }
                }
            ]
        }
        import json as _json
        self.scheduler.add_task(
            name="Auto-Prune Tools",
            task=_json.dumps(prune_task),
            schedule=TaskSchedule(
                schedule_type="interval",
                interval_seconds=86400
            )
        )

        # ── Phase 6 ────────────────────────────────────────────────
        
        # Streaming Event Bus
        from james.stream import EventBus
        self.streamer = EventBus()

        # AI (lazy — only active when API key or local model is present)
        self._ai_available: Optional[bool] = None

        logger.info(f"JAMES Orchestrator initialized at {self._root}")
        logger.info(f"  Layers: {self.layers.available_count}/{self.layers.registered_count} available")
        logger.info(f"  Skills: {self.skills.count}")
        logger.info(f"  Tools: {self.tools.count}")
        self.memory.lt_set("last_init", time.time(), category="system")

    def _register_layers(self) -> None:
        """Register all 5 authority layers."""
        self.layers.register(NativeLayer())
        self.layers.register(ApplicationLayer())
        self.layers.register(UICognitiveLayer())
        self.layers.register(SyntheticLayer())
        self.layers.register(EnvironmentalLayer())

    # ── Task Decomposition ───────────────────────────────────────

    def plan(self, task: dict | str) -> ExecutionGraph:
        """
        Decompose a task into an execution graph (DAG).

        Args:
            task: Either a string description or a structured dict:
                {
                    "name": "task name",
                    "steps": [
                        {"name": "step 1", "action": {...}, "layer": 1},
                        {"name": "step 2", "action": {...}, "depends_on": ["step_id"]},
                    ]
                }
        """
        if isinstance(task, str):
            return self._plan_from_string(task)
        return self._plan_from_dict(task)

    def _plan_from_string(self, description: str) -> ExecutionGraph:
        """
        Plan from a natural language description.
        Uses AI decomposition when available, falls back to heuristics.
        """
        # ── Direct commands (! or $) — skip AI ────────────
        if description.startswith("!") or description.startswith("$"):
            cmd = description.lstrip("!$").strip()
            graph = ExecutionGraph(name=f"exec: {cmd[:50]}")
            node = Node(
                name=f"exec: {cmd[:40]}",
                action={"type": "command", "target": cmd},
                layer=1,
            )
            graph.add_node(node)
            self._active_graph = graph
            self.memory.st_set("active_graph", graph.to_dict())
            return graph

        # ── HTTP URLs — skip AI ───────────────────────────
        if description.lower().startswith("http"):
            graph = ExecutionGraph(name=f"http: {description[:50]}")
            node = Node(
                name=f"http: {description[:40]}",
                action={"type": "http", "target": description},
                layer=2,
            )
            graph.add_node(node)
            self._active_graph = graph
            self.memory.st_set("active_graph", graph.to_dict())
            return graph

        # ── Try AI decomposition ──────────────────────────
        ai_plan = self._try_ai_decompose(description)
        if ai_plan:
            return ai_plan

        # ── Fallback: treat as PowerShell ─────────────────
        graph = ExecutionGraph(name=description[:60])
        node = Node(
            name=description[:60],
            action={"type": "powershell", "target": description},
            layer=1,
        )
        graph.add_node(node)
        self._active_graph = graph
        self.memory.st_set("active_graph", graph.to_dict())
        return graph

    def _try_ai_decompose(self, description: str) -> Optional[ExecutionGraph]:
        """Attempt AI-powered task decomposition. Returns None if unavailable."""
        try:
            from james import ai as james_ai
            if not james_ai.is_available():
                return None

            # ── Build rich context from skills + memory ──────
            context = self._build_ai_context(description)

            result = james_ai.decompose_task(description, context=context)

            if result.get("type") == "chat":
                # AI responded with chat — wrap as a no-op with message
                graph = ExecutionGraph(name=f"ai-chat: {description[:40]}")
                node = Node(
                    name="ai_response",
                    action={"type": "noop"},
                    layer=1,
                )
                node.state = NodeState.SUCCESS
                node.result = NodeResult(
                    success=True,
                    output={"message": result.get("message", ""), "ai": True},
                )
                graph.add_node(node)
                self._active_graph = graph
                return graph

            if result.get("steps"):
                # AI returned a structured plan
                plan = {
                    "name": result.get("intent", description[:40]),
                    "steps": result["steps"],
                }
                logger.info(
                    f"AI planned {len(plan['steps'])} steps: {result.get('reasoning', '')[:100]}"
                )
                self.audit.record(AuditEntry(
                    operation="ai_plan",
                    classification=OpClass.SAFE,
                    details=f"AI decomposed into {len(plan['steps'])} steps",
                ))
                # Store the original description for post-execution learning
                self.memory.st_set("_ai_task_description", description)
                return self._plan_from_dict(plan)

        except Exception as e:
            logger.warning(f"AI decomposition failed, falling back: {e}")
        return None

    def _build_ai_context(self, task_description: str) -> dict:
        """
        Build a rich context dict for the AI from skills, memory, and metrics.
        This gives the AI real knowledge about the system's capabilities.
        """
        context: dict = {
            "os": "Windows",
            "project_root": self._root,
            "available_layers": self.layers.available_count,
        }

        self._inject_tools_context(context)
        self._inject_skills_context(context, task_description)
        self._inject_system_map_context(context)
        self._inject_ltm_context(context)
        self._inject_execution_history_context(context)
        self._inject_recent_failures_context(context)
        self._inject_relevant_memories_context(context, task_description)
        self._inject_rag_context(context, task_description)

        return context

    def _inject_tools_context(self, context: dict) -> None:
        """Inject available tools (AI can use tool_call action type)."""
        try:
            tool_list = self.tools.list_tools()
            context["available_tools"] = [
                {"name": t["name"], "description": t["description"]}
                for t in tool_list
            ]
        except Exception:
            pass

    def _inject_skills_context(self, context: dict, task_description: str) -> None:
        """Inject relevant skills (the AI can reuse proven methods)."""
        try:
            # Search for skills matching the task description
            matching_skills = self.skills.search(task_description)
            all_skills = self.skills.list_all()

            # Include matching skills in full detail, others as summaries
            if matching_skills:
                context["matching_skills"] = [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "steps": s.steps,
                        "confidence": round(s.confidence_score, 2),
                        "success_rate": f"{s.success_rate:.0%}",
                        "methods": s.methods,
                    }
                    for s in matching_skills[:5]
                ]

            # Always include a skills summary so AI knows what's available
            context["available_skills"] = [
                {"id": s.id, "name": s.name, "confidence": round(s.confidence_score, 2)}
                for s in all_skills[:20]
            ]
        except Exception:
            pass

    def _inject_system_map_context(self, context: dict) -> None:
        """Inject system map (known tools and paths)."""
        try:
            system_tools = self.memory.map_list(category="tool")
            if system_tools:
                context["installed_tools"] = {
                    t["key"]: t["value"] for t in system_tools[:30]
                }
        except Exception:
            pass

    def _inject_ltm_context(self, context: dict) -> None:
        """Inject recent Long-Term Memories (context facts)."""
        try:
            # Fetch recent general or project context saved by the AI
            ltm_facts = self.memory.lt_list(limit=20)
            if ltm_facts:
                context["long_term_memory"] = [
                    {"key": f["key"], "value": f["value"], "category": f["category"]}
                    for f in ltm_facts if "value" in f
                ]
        except Exception:
            pass

    def _inject_execution_history_context(self, context: dict) -> None:
        """Inject recent execution history (learns from past)."""
        try:
            recent_metrics = self.memory.get_metrics(limit=10)
            if recent_metrics:
                context["recent_executions"] = [
                    {
                        "name": m.get("node_name", ""),
                        "success": bool(m.get("success")),
                        "duration_ms": round(m.get("duration_ms", 0)),
                        "error": m.get("error", ""),
                    }
                    for m in recent_metrics
                    if m.get("node_name")
                ]
        except Exception:
            pass

    def _inject_recent_failures_context(self, context: dict) -> None:
        """Inject recent failures (avoid repeating mistakes)."""
        try:
            failures = self.failures.get_history(limit=5)
            if failures:
                context["recent_failures"] = [
                    {
                        "task": f.get("node_name", ""),
                        "error": f.get("error_message", "")[:200],
                        "type": f.get("failure_type", ""),
                    }
                    for f in failures
                ]
        except Exception:
            pass

    def _inject_relevant_memories_context(self, context: dict, task_description: str) -> None:
        """Inject semantically relevant memories (vector search)."""
        try:
            if self.vectors.count > 0:
                vector_results = self.vectors.search(task_description, top_k=5)
                if vector_results:
                    relevant = {}
                    for key, score in vector_results:
                        if score > 0.15:  # relevance threshold
                            value = self.memory.lt_get(key)
                            if value is not None:
                                relevant[key] = {"value": value, "relevance": round(score, 2)}
                    if relevant:
                        context["relevant_memories"] = relevant
        except Exception:
            pass

        # Fallback: inject recent LTM if no vector results
        if "relevant_memories" not in context:
            try:
                lt_entries = self.memory.lt_list(limit=10)
                if lt_entries:
                    context["long_term_memory"] = {
                        e["key"]: e["value"]
                        for e in lt_entries
                        if e["key"] != "last_init"
                    }
            except Exception:
                pass

    def _inject_rag_context(self, context: dict, task_description: str) -> None:
        """Inject RAG document context."""
        try:
            if self.rag and self.rag._vector_store.count > 0:
                rag_results = self.rag.get_context(task_description, top_k=3)
                if rag_results:
                    context["relevant_documents"] = rag_results
        except Exception:
            pass

    def _plan_from_dict(self, task: dict) -> ExecutionGraph:
        """Plan from a structured task dictionary."""
        name = task.get("name", "unnamed_task")

        # ── Pre-flight plan validation ────────────────────
        if task.get("steps"):
            vr = self.plan_validator.validate(task)
            if not vr.valid:
                # Return an error graph instead of executing
                graph = ExecutionGraph(name=f"REJECTED: {name}")
                node = Node(
                    name="plan_rejected",
                    action={"type": "noop"},
                    layer=1,
                )
                node.state = NodeState.FAILED
                node.result = NodeResult(
                    success=False,
                    error=f"Plan validation failed: {'; '.join(vr.errors)}",
                )
                graph.add_node(node)
                self._active_graph = graph
                self.audit.record(AuditEntry(
                    operation="plan_rejected",
                    classification=OpClass.DANGEROUS,
                    details=f"Rejected '{name}': {'; '.join(vr.errors)[:300]}",
                ))
                return graph
            # Apply any auto-corrections from validation
            task = vr.corrected_plan
            if vr.warnings:
                self.audit.record(AuditEntry(
                    operation="plan_warnings",
                    classification=OpClass.SAFE,
                    details=f"{len(vr.warnings)} warnings: {'; '.join(vr.warnings)[:300]}",
                ))

        graph = ExecutionGraph(name=name)

        node_map: dict[str, str] = {}  # step name -> node id

        for step in task.get("steps", []):
            action = step.get("action", {})
            layer = step.get("layer")
            
            # Force NativeLayer for specific types to prevent AI layer hallucinations
            if isinstance(action, dict) and action.get("type", "") in ("tool_call", "noop"):
                layer = 1
                
            node = Node(
                name=step.get("name", "unnamed_step"),
                action=action,
                layer=layer,
                retry_limit=step.get("retry_limit", 3),
                metadata=step.get("metadata", {}),
            )
            graph.add_node(node)
            node_map[step.get("name", node.id)] = node.id

            # Resolve dependencies
            for dep_name in step.get("depends_on", []):
                dep_id = node_map.get(dep_name)
                if dep_id:
                    graph.add_dependency(dep_id, node.id)

        self._active_graph = graph
        self.memory.st_set("active_graph", graph.to_dict())
        return graph

    # ── Execution Loop ───────────────────────────────────────────

    def execute(self, graph: Optional[ExecutionGraph] = None) -> ExecutionGraph:
        """
        Execute a graph through the deterministic lifecycle.
        Returns the completed graph with results.
        """
        graph = graph or self._active_graph
        if not graph:
            raise ValueError("No execution graph to execute. Call plan() first.")

        logger.info(f"Executing graph: {graph.name} ({len(graph.nodes)} nodes)")
        self.streamer.emit("graph_start", {"id": graph.id, "name": graph.name, "nodes": len(graph.nodes)})
        self.audit.record(AuditEntry(operation="graph_start", classification=OpClass.SAFE, details=graph.name))

        # Concurrent execution of ready nodes
        try:
            graph._validate_no_cycles()
        except Exception as e:
            logger.error(f"Graph validation failed: {e}")
            self.audit.record(AuditEntry(operation="graph_error", classification=OpClass.SAFE, details=str(e)))
            raise

        import concurrent.futures
        from james.dag import NodeState
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures_map = {}
            while True:
                graph.update_skipped_nodes()
                ready_nodes = graph.get_ready_nodes()
                for node in ready_nodes:
                    node.state = NodeState.RUNNING  # Prevent picking it up again
                    future = executor.submit(self._execute_node, node, graph)
                    futures_map[future] = node
                    
                if not futures_map:
                    # No nodes are running and no nodes are ready. Deadlock or finished.
                    break
                    
                done, not_done = concurrent.futures.wait(
                    futures_map.keys(), return_when=concurrent.futures.FIRST_COMPLETED
                )
                
                for f in done:
                    node = futures_map.pop(f)
                    # Retrieve any thrown exceptions to prevent silent thread crashes
                    try:
                        f.result()
                    except Exception as e:
                        logger.error(f"Node execution thread crashed for node {node.id}: {e}")
                        node.state = NodeState.FAILED
                        node.result = NodeResult(
                            success=False,
                            error=f"Thread execution crashed: {e}"
                        )
                        self.streamer.emit("node_complete", {"node_id": node.id, "success": False, "error": f"Thread crashed: {e}"})

        graph.completed_at = time.time()
        self.memory.st_set("active_graph", graph.to_dict())

        # Summary
        done, total = graph.progress
        self.streamer.emit("graph_complete", {"id": graph.id, "success": not graph.has_failures, "done": done, "total": total})
        logger.info(f"Graph complete: {done}/{total} nodes, failures={graph.has_failures}")
        self.audit.record(AuditEntry(
            operation="graph_complete",
            classification=OpClass.SAFE,
            details=f"{done}/{total} nodes, failures={graph.has_failures}",
        ))

        # ── Post-execution learning ──────────────────────────
        self._post_execute_learn(graph)

        return graph

    def _post_execute_learn(self, graph: ExecutionGraph) -> None:
        """
        After execution completes, feed results back into memory and skills.
        If AI is available and the task succeeded, generate a reusable skill.
        """
        done, total = graph.progress

        # ── Store execution results in long-term memory ──────
        try:
            self.memory.lt_set(
                f"task_result:{graph.name[:60]}",
                {
                    "name": graph.name,
                    "completed": done,
                    "total": total,
                    "has_failures": graph.has_failures,
                    "timestamp": time.time(),
                    "node_count": len(graph.nodes),
                },
                category="execution_history",
            )
        except Exception:
            pass

        # ── AI-powered skill generation from successful runs ─
        # Check for dynamically generated tools that encountered warnings
        for nid, node in graph.nodes.items():
            if node.state == NodeState.SUCCESS and node.result and node.result.output:
                out_str = str(node.result.output).lower()
                action_type = node.action.get("type", "") if isinstance(node.action, dict) else ""
                if action_type == "tool_call" and ("warning" in out_str or "deprecated" in out_str):
                    target_tool = node.action.get("target", "")
                    # Check if it's a self-evolved plugin tool
                    plugin_name = f"self_evolved_{target_tool}"
                    if hasattr(self, "plugins") and self.plugins.get_plugin(plugin_name):
                        logger.info(f"Dynamically generated tool '{target_tool}' produced a warning. Triggering Code Agent reflexivity.")
                        self.audit.record(AuditEntry(
                            operation="code_agent_reflexivity_triggered",
                            classification=OpClass.SAFE,
                            details=f"Tool '{target_tool}' triggered reflexivity due to warning: {out_str[:100]}"
                        ))
                        # Delegate task to Code Agent to evolve the tool
                        task = {
                            "name": f"Evolve Tool {target_tool}",
                            "steps": [
                                {
                                    "name": "evolve_tool",
                                    "action": {
                                        "type": "tool_call",
                                        "target": "evolve_tool_code",
                                        "kwargs": {
                                            "tool_name": target_tool,
                                            "warning": str(node.result.output)
                                        }
                                    }
                                }
                            ]
                        }
                        try:
                            from james.agents import AgentRole
                            self.agents.delegate(task, role=AgentRole.CODE)
                        except Exception as e:
                            logger.error(f"Failed to delegate reflexivity task to Code Agent: {e}")

        if (
            not graph.has_failures
            and total >= 2  # multi-step tasks are worth learning
            and self.memory.st_get("_ai_task_description")  # was AI-planned
        ):
            task_description = self.memory.st_get("_ai_task_description")
            self.memory.st_delete("_ai_task_description")

            try:
                from james import ai as james_ai
                if not james_ai.is_available():
                    return

                # Build execution log for the AI
                execution_log = []
                for nid, node in graph.nodes.items():
                    entry = {
                        "name": node.name,
                        "action": node.action,
                        "state": node.state.value,
                    }
                    if node.result:
                        entry["output"] = str(node.result.output)[:300] if node.result.output else None
                        entry["duration_ms"] = node.result.duration_ms
                        entry["layer_used"] = node.result.layer_used
                    execution_log.append(entry)

                # Ask AI to generate a skill definition
                skill_def = james_ai.generate_skill_from_history(
                    task_name=task_description,
                    execution_log=execution_log,
                )

                if skill_def and skill_def.get("id"):
                    # Check if we already have this skill
                    existing = self.skills.get(skill_def["id"])
                    if existing:
                        # Update confidence (it was used successfully again)
                        existing.record_execution(success=True)
                        self.skills.update(existing)
                        logger.info(f"  Skill '{existing.id}' confidence updated to {existing.confidence_score:.2f}")
                    else:
                        # Create new skill from AI definition
                        from james.skills.skill import Skill
                        new_skill = Skill(
                            id=skill_def["id"],
                            name=skill_def.get("name", ""),
                            description=skill_def.get("description", ""),
                            methods=skill_def.get("methods", ["CLI"]),
                            steps=skill_def.get("steps", []),
                            preconditions=skill_def.get("preconditions", []),
                            postconditions=skill_def.get("postconditions", []),
                            tags=skill_def.get("tags", []),
                        )
                        new_skill.record_execution(success=True)
                        self.skills.create(new_skill)

                        logger.info(f"  AI learned new skill: '{new_skill.id}' from successful execution")
                        self.audit.record(AuditEntry(
                            operation="ai_skill_learned",
                            classification=OpClass.SAFE,
                            details=f"Skill '{new_skill.id}': {new_skill.description[:100]}",
                        ))

                        # Record in meta-memory
                        self.memory.record_optimization(
                            skill_id=new_skill.id,
                            optimization=f"AI-generated from: {task_description[:100]}",
                            before_score=0.0,
                            after_score=new_skill.confidence_score,
                        )

            except Exception as e:
                logger.debug(f"Post-execution learning skipped: {e}")

    def _execute_node(self, node: Node, graph: ExecutionGraph) -> None:
        """Execute a single node through the full verification pipeline."""
        logger.info(f"  Node [{node.id}] {node.name}")
        self.streamer.emit("node_start", {"node_id": node.id, "name": node.name})

        try:
            self._execute_node_inner(node, graph)
        except Exception as e:
            logger.error(f"  Node [{node.id}] crashed during execution: {e}")
            node.state = NodeState.FAILED
            node.result = NodeResult(
                success=False,
                error=str(e),
            )
            self.streamer.emit("node_complete", {"node_id": node.id, "success": False, "error": str(e)})

    def _execute_node_inner(self, node: Node, graph: ExecutionGraph) -> None:
        # ── Pre-validation ───────────────────────────────
        pre_conditions = [
            Condition(name=f"precond_{i}", check=pc)
            for i, pc in enumerate(node.preconditions)
        ]
        pre_result = self.verifier.verify_preconditions(pre_conditions)
        if not pre_result.success and pre_conditions:
            node.state = NodeState.FAILED
            node.result = NodeResult(
                success=False,
                error=f"Precondition failed: {pre_result.diagnostics}",
            )
            logger.warning(f"  Node [{node.id}] precondition failed: {pre_result.diagnostics}")
            self.streamer.emit("node_complete", {"node_id": node.id, "success": False, "error": f"Precondition failed: {pre_result.diagnostics}"})
            return

        # ── Security check ───────────────────────────────
        action = node.action or {}
        if isinstance(action, dict):
            cmd_str = action.get("target", "")
            op_class = self.security.classify_operation(str(cmd_str))
            if self.security.requires_confirmation(op_class):
                logger.warning(
                    f"  Node [{node.id}] requires confirmation (class={op_class.value}). "
                    "Skipping in autonomous mode."
                )
                self.audit.record(AuditEntry(
                    operation="node_blocked",
                    classification=op_class,
                    node_id=node.id,
                    details=f"Blocked: {cmd_str[:100]}",
                    approved=False,
                ))
                node.state = NodeState.SKIPPED
                node.result = NodeResult(
                    success=False,
                    error=f"Operation blocked by security policy: {op_class.value}",
                )
                self.streamer.emit("node_complete", {"node_id": node.id, "success": False, "error": f"Blocked by security policy: {op_class.value}"})
                return
        else:
            op_class = OpClass.SAFE

        # ── Layer selection ──────────────────────────────
        # ABSOLUTE ENFORCEMENT: tool_call and noop ALWAYS go to NativeLayer.
        # This prevents any layer selection ambiguity from routing these to
        # layers that lack tool_call dispatch (e.g., UICognitive, Synthetic).
        action_type = action.get("type", "") if isinstance(action, dict) else ""
        if action_type in ("tool_call", "noop"):
            layer = self.layers.get(LayerLevel.NATIVE)
            if not layer:
                layer = self.layers.select_best(LayerLevel.NATIVE)
        else:
            preferred_level = LayerLevel(node.layer) if node.layer else None
            layer = self.layers.select_best(preferred_level)
        if not layer:
            node.state = NodeState.FAILED
            node.result = NodeResult(success=False, error="No available execution layer")
            self.streamer.emit("node_complete", {"node_id": node.id, "success": False, "error": "No available execution layer"})
            return

        # ── Execute with retry ───────────────────────────
        node.state = NodeState.RUNNING
        self.audit.record(AuditEntry(
            operation="node_execute",
            classification=op_class,
            node_id=node.id,
            details=f"Layer={layer.level.value} Action={str(action)[:200]}",
        ))

        attempts = 0
        current_layer = layer

        while attempts < node.retry_limit:
            attempts += 1
            start = time.perf_counter()

            try:
                if isinstance(action, dict):
                    result = current_layer.execute(action)
                elif callable(action):
                    ok, output, error, dur = self.verifier.monitor_execution(action)
                    from james.layers import LayerResult
                    result = LayerResult(
                        success=ok, output=output, error=error, duration_ms=dur
                    )
                else:
                    # Treat as command string
                    result = current_layer.execute({
                        "type": "command",
                        "target": str(action),
                    })
            except Exception as e:
                from james.layers import LayerResult
                duration = (time.perf_counter() - start) * 1000
                result = LayerResult(success=False, error=str(e), duration_ms=duration)

            if not result.duration_ms:
                result.duration_ms = (time.perf_counter() - start) * 1000

            # Record metric
            self.memory.record_metric(
                ExecutionMetric(
                    node_id=node.id,
                    success=result.success,
                    duration_ms=result.duration_ms,
                    node_name=node.name,
                    layer=current_layer.level.value,
                    error=result.error,
                )
            )

            if result.success:
                node.state = NodeState.SUCCESS
                node.result = NodeResult(
                    success=True,
                    output=result.output,
                    duration_ms=result.duration_ms,
                    layer_used=current_layer.name,
                    attempts=attempts,
                )
                logger.info(
                    f"  Node [{node.id}] SUCCESS "
                    f"(layer={current_layer.level.value}, {result.duration_ms:.0f}ms, "
                    f"attempts={attempts})"
                )
                self.streamer.emit("node_complete", {
                    "node_id": node.id, "success": True, 
                    "output": str(result.output)[:1000] if result.output else None,
                    "duration_ms": result.duration_ms
                })
                return

            # ── Failure handling ─────────────────────────
            context = FailureContext(
                node_id=node.id,
                node_name=node.name,
                error_message=result.error or "",
                layer_attempted=current_layer.level.value,
            )
            failure = self.failures.record_failure(context)

            logger.warning(
                f"  Node [{node.id}] attempt {attempts}/{node.retry_limit} failed: "
                f"{failure.failure_type.value} — {result.error}"
            )

            # Try layer escalation on non-transient failures
            # NEVER escalate tool_call/noop — they only work on NativeLayer.
            from james.failure import RecoveryAction
            is_tool_action = action_type in ("tool_call", "noop")
            if not is_tool_action and RecoveryAction.ESCALATE_LAYER in failure.recovery_actions:
                next_layer = self.layers.escalate(current_layer.level)
                if next_layer:
                    logger.info(
                        f"  Escalating from Layer {current_layer.level.value} "
                        f"to Layer {next_layer.level.value}"
                    )
                    current_layer = next_layer
            elif is_tool_action:
                # tool_call failed on NativeLayer — no point retrying on other layers
                break

        # All attempts exhausted — try capability expansion
        final_error = result.error if result else "Max retries exhausted"
        recovery = None
        try:
            recovery = self.expander.attempt_recovery(
                task=node.name,
                error=final_error,
            )
            if recovery and recovery.get("recovered"):
                # Recovery succeeded (e.g. missing package installed) — retry once
                logger.info(f"  Auto-recovery succeeded ({recovery.get('action')}), retrying...")
                result = current_layer.execute(node.action)
                if result and result.success:
                    node.state = NodeState.SUCCESS
                    node.result = NodeResult(
                        success=True,
                        output=result.output,
                        duration_ms=result.duration_ms,
                        layer_used=current_layer.name,
                        attempts=attempts + 1,
                        metadata={"auto_recovered": True, "recovery_action": recovery.get("action")},
                    )
                    logger.info(f"  Node [{node.id}] SUCCESS after auto-recovery")
                    self.streamer.emit("node_complete", {
                        "node_id": node.id, "success": True, 
                        "output": str(result.output)[:1000] if result.output else None,
                        "duration_ms": result.duration_ms, "recovered": True
                    })
                    return
        except Exception as e:
            logger.debug(f"  Capability expansion failed: {e}")

        node.state = NodeState.FAILED
        node.result = NodeResult(
            success=False,
            output=result.output if result else None,
            error=final_error,
            duration_ms=result.duration_ms if result else 0,
            layer_used=current_layer.name,
            attempts=attempts,
            metadata={"recovery_attempted": recovery is not None},
        )
        logger.error(f"  Node [{node.id}] FAILED after {attempts} attempts")
        self.streamer.emit("node_complete", {"node_id": node.id, "success": False, "error": final_error})

    # ── Convenience Methods ──────────────────────────────────────

    def run(self, task: dict | str) -> ExecutionGraph:
        """Plan and execute a task in one call."""
        graph = self.plan(task)
        return self.execute(graph)

    def run_command(self, command: str, layer: int = 1) -> Any:
        """Quick-run a single command. Returns the output."""
        graph = ExecutionGraph(name=f"cmd: {command[:40]}")
        node = Node(
            name=f"exec: {command[:40]}",
            action={"type": "command" if layer == 1 else "powershell", "target": command},
            layer=layer,
        )
        graph.add_node(node)
        self.execute(graph)
        if node.result:
            return node.result.output
        return None

    def status(self) -> dict:
        """Get current system status."""
        mem_stats = self.memory.get_stats()

        # Check AI availability (cached)
        if self._ai_available is None:
            try:
                from james import ai as james_ai
                self._ai_available = james_ai.is_available()
            except Exception:
                self._ai_available = False

        # Get AI backend info
        ai_info = {"available": self._ai_available, "backend": None, "model": None}
        if self._ai_available:
            try:
                from james import ai as james_ai
                ai_info = james_ai.get_backend_info()
            except Exception:
                pass

        # Scheduler status
        sched_info = {"running": False, "active_tasks": 0}
        try:
            sched_status = self.scheduler.status()
            sched_info = {
                "running": sched_status["running"],
                "active_tasks": sched_status["active_tasks"],
                "total_tasks": sched_status["total_tasks"],
            }
        except Exception:
            pass

        return {
            "version": "2.3.0",
            "project_root": self._root,
            "layers": {
                "registered": self.layers.registered_count,
                "available": self.layers.available_count,
            },
            "skills": self.skills.count,
            "tools": self.tools.count,
            "memory": mem_stats,
            "failures": {
                "total": self.failures.total_failures,
                "unresolved": self.failures.unresolved_count,
            },
            "active_graph": self._active_graph.name if self._active_graph else None,
            "audit_entries": self.audit.entry_count,
            "ai": ai_info,
            "scheduler": sched_info,
            "vectors": self.vectors.status(),
            "rag": self.rag.status(),
            "evolution": self.expander.status(),
            "watcher": self.watcher.status(),
            "conversations": self.conversations.status(),
            "skill_versions": self.skill_versions.status(),
            "health": self.health.status(),
            "plugins": self.plugins.status(),
            "agents": self.agents.status(),
        }

    def improve(self) -> dict:
        """Run the autonomous improvement cycle."""
        return self.optimizer.run_improvement_cycle()

    def __repr__(self) -> str:
        status = self.status()
        return (
            f"<JAMES Orchestrator v{status['version']} "
            f"layers={status['layers']['available']}/{status['layers']['registered']} "
            f"skills={status['skills']}>"
        )
