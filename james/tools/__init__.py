"""
JAMES Tools Module — Direct callable utilities for the AI agent.

These functions are registered as native tools that the AI orchestrator
can invoke directly (without subprocess overhead) for premium-grade
operations: web requests, system profiling, compression, hashing, etc.
"""

from james.tools.registry import ToolRegistry, get_registry

__all__ = ["ToolRegistry", "get_registry"]
