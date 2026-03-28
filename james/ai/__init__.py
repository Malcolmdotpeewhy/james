"""
JAMES AI Module — Unified AI Interface

Backend priority:
  1. Local LLM (llama-server from AI Playground) — preferred, zero latency, fully offline
  2. Gemini API — fallback when local is unavailable

The active backend is selected automatically based on availability.
Override with JAMES_AI_BACKEND=local|gemini environment variable.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("james.ai")

# ── Backend selection ─────────────────────────────────────────

_backend = None  # "local" | "gemini" | None


def _resolve_backend() -> Optional[str]:
    """Determine which AI backend to use."""
    global _backend
    if _backend is not None:
        return _backend

    # Environment override
    forced = os.environ.get("JAMES_AI_BACKEND", "").lower()
    if forced in ("local", "gemini"):
        _backend = forced
        logger.info(f"AI backend forced to: {_backend}")
        return _backend

    # Try local first (preferred — no API key needed)
    try:
        from james.ai import local_llm
        if local_llm.is_available():
            _backend = "local"
            logger.info("AI backend: local (llama-server)")
            return _backend
    except Exception as e:
        logger.debug(f"Local LLM not available: {e}")

    # Fall back to Gemini
    try:
        from james.ai import gemini
        if gemini.is_available():
            _backend = "gemini"
            logger.info("AI backend: gemini")
            return _backend
    except Exception as e:
        logger.debug(f"Gemini not available: {e}")

    _backend = None
    return None


def _get_module():
    """Get the active backend module."""
    backend = _resolve_backend()
    if backend == "local":
        from james.ai import local_llm
        return local_llm
    elif backend == "gemini":
        from james.ai import gemini
        return gemini
    return None


# ── Public API ────────────────────────────────────────────────

def is_available() -> bool:
    """Check if any AI backend is available."""
    return _resolve_backend() is not None


def get_backend_info() -> dict:
    """Get info about the current AI backend."""
    backend = _resolve_backend()
    info = {"backend": backend, "available": backend is not None}

    if backend == "local":
        from james.ai import local_llm
        info.update(local_llm.get_status())
        info["model"] = info.get("active_model") or "local (auto)"
    elif backend == "gemini":
        info["model"] = "gemini-2.0-flash"

    return info


def decompose_task(user_input: str, context: Optional[dict] = None,
                   chat_history: Optional[list] = None) -> dict:
    """Decompose a task using the active AI backend."""
    mod = _get_module()
    if mod:
        return mod.decompose_task(user_input, context=context, chat_history=chat_history)
    return {"type": "fallback", "message": "No AI backend available", "raw_input": user_input}


def analyze_error(error_message: str, command: str = "", layer: int = 1, context=None) -> dict:
    """Analyze an error using AI."""
    mod = _get_module()
    if mod:
        return mod.analyze_error(error_message, command=command, layer=layer, context=context)
    return {"analysis": "No AI backend available", "suggestions": []}


def chat(message: str, history: Optional[list] = None) -> str:
    """Chat with JAMES AI."""
    mod = _get_module()
    if mod:
        return mod.chat(message, history=history)
    return "No AI backend available. Install models or set GEMINI_API_KEY."


def generate_skill_from_history(task_name: str, execution_log: list) -> Optional[dict]:
    """Generate a skill from execution history."""
    mod = _get_module()
    if mod:
        return mod.generate_skill_from_history(task_name, execution_log)
    return None


def smart_diagnose(system_status: dict, metrics: list, failures: list) -> dict:
    """AI-powered system diagnosis."""
    mod = _get_module()
    if mod:
        return mod.smart_diagnose(system_status, metrics, failures)
    return {"diagnosis": "No AI backend available", "recommendations": []}


# Re-export local_llm management functions for direct access
def start_local_server(model_path=None, port=None):
    """Start the local llama-server."""
    from james.ai import local_llm
    return local_llm.start_server(model_path=model_path, port=port)


def stop_local_server():
    """Stop the local llama-server."""
    from james.ai import local_llm
    return local_llm.stop_server()


def discover_local_models():
    """Discover available GGUF models."""
    from james.ai import local_llm
    return local_llm.discover_models()


__all__ = [
    "is_available",
    "get_backend_info",
    "decompose_task",
    "analyze_error",
    "chat",
    "generate_skill_from_history",
    "smart_diagnose",
    "start_local_server",
    "stop_local_server",
    "discover_local_models",
]
