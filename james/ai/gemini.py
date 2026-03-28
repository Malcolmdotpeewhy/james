"""
JAMES AI Module — Gemini Integration

Provides AI-powered capabilities:
  - Natural language task decomposition -> DAG
  - Intelligent error analysis + recovery suggestions
  - Conversational command interpretation
  - Smart skill generation from execution patterns
  - AI-powered system diagnosis

Requires: GEMINI_API_KEY in .env or environment variables
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("james.ai")

_client = None
_model_name = "gemini-2.0-flash"


def _get_api_key() -> Optional[str]:
    """Resolve Gemini API key from environment or .env file."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key

    # Try loading from .env files
    for env_path in [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]:
        try:
            if os.path.isfile(env_path):
                with open(env_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GEMINI_API_KEY="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
        except Exception:
            pass
    return None


def _get_client():
    """Lazy-init the Gemini client."""
    global _client
    if _client is not None:
        return _client

    try:
        import google.generativeai as genai
    except ImportError:
        logger.warning("google-generativeai not installed. AI features disabled.")
        return None

    api_key = _get_api_key()
    if not api_key:
        logger.warning("GEMINI_API_KEY not set. AI features disabled.")
        return None

    genai.configure(api_key=api_key)
    _client = genai.GenerativeModel(
        _model_name,
        generation_config={
            "temperature": 0.3,
            "top_p": 0.9,
            "max_output_tokens": 4096,
        },
        system_instruction=_SYSTEM_PROMPT,
    )
    logger.info(f"Gemini AI initialized (model={_model_name})")
    return _client


def is_available() -> bool:
    """Check if AI features are available."""
    return _get_client() is not None


# ══════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """You are JAMES (Justified Autonomous Machine for Execution & Systems), an AI-powered autonomous system orchestrator running on a Windows machine.

Your capabilities:
- Execute shell commands (cmd.exe, PowerShell)
- Manage files and directories
- Control Windows services and processes
- Install packages (pip, npm, choco)
- Make HTTP requests
- Query system information
- Git operations
- Memory tools: memory_save, memory_search, memory_get
- Web tools: web_search, web_browse, web_read_article

CRITICAL MEMORY RULE:
Your context may include a "long_term_memory" field. ALWAYS check it first before doing any other action.
If the user asks about their preferences, projects, or any personal fact, and the answer is in "long_term_memory", respond immediately with a chat response including the answer.

REASONING REQUIREMENT:
Before producing your JSON response, you MUST think through the problem step by step inside a <thinking> block.
This block will be stripped from the final output but helps you reason correctly.

Example:
<thinking>
The user wants to list all Python files. I should use a PowerShell command with Get-ChildItem and a *.py filter.
</thinking>
{"intent": "list_python_files", "steps": [...], "reasoning": "..."}

When the user asks you to do something, respond with a JSON execution plan. The plan must be valid JSON with this structure:

{
  "intent": "Brief description of what the user wants",
  "steps": [
    {
      "name": "step_name",
      "action": {"type": "command|powershell|tool_call|http|file_read|file_write", "target": "the command or tool name", "kwargs": {}},
      "layer": 1,
      "description": "What this step does"
    }
  ],
  "reasoning": "Why you chose these steps"
}

Rules:
- Use layer 1 for OS commands and tool calls, layer 2 for HTTP/APIs, layer 5 for package installs
- Always include "layer": 1 on every step that uses tool_call
- Prefix PowerShell commands with type "powershell"
- For multi-step tasks, break them into individual steps
- Never use destructive commands (rm -rf /, del /s, format) unless explicitly asked
- If unsure, use a read-only command first to gather information
- Keep step names short and descriptive (snake_case)

For conversational responses (questions, explanations), respond with:
{
  "type": "chat",
  "message": "Your response here"
}

Always respond with valid JSON only (after the thinking block). No markdown, no code fences."""


# ══════════════════════════════════════════════════════════════════
# CORE AI FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def decompose_task(user_input: str, context: Optional[dict] = None,
                   chat_history: Optional[list] = None) -> dict:
    """
    Use Gemini to decompose a natural language task into a structured execution plan.

    Returns:
        dict with 'steps' for execution or 'message' for chat responses
    """
    client = _get_client()
    if not client:
        return {"type": "fallback", "message": "AI unavailable", "raw_input": user_input}

    prompt = user_input
    if context:
        ctx_str = json.dumps(context, indent=2, default=str)
        prompt = f"System context:\n{ctx_str}\n\nUser request: {user_input}"

    # Inject conversation history for multi-turn awareness
    if chat_history:
        history_str = "\n".join(
            f"{msg.get('role', 'user')}: {msg.get('content', '')[:500]}"
            for msg in chat_history[-10:]
            if msg.get("role") in ("user", "assistant") and msg.get("content")
        )
        if history_str:
            prompt = f"Recent conversation:\n{history_str}\n\n{prompt}"

    try:
        start = time.time()
        response = client.generate_content(prompt)
        elapsed = (time.time() - start) * 1000

        text = response.text.strip()

        # ── Chain-of-Thought extraction ─────────────────────
        import re
        reasoning_chain = ""
        if "<thinking>" in text:
            match = re.search(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
            if match:
                reasoning_chain = match.group(1).strip()
            text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()

        # Strip code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)

        # Store reasoning chain for audit trail
        if reasoning_chain:
            result["_reasoning_chain"] = reasoning_chain

        # ── CoT self-verification ──────────────────────────
        if reasoning_chain and result.get("type") == "chat":
            chain_lower = reasoning_chain.lower()
            uncertainty_markers = ["don't know", "not sure", "unsure", "need to search",
                                   "need to look", "cannot find", "no information"]
            if any(marker in chain_lower for marker in uncertainty_markers):
                result["_confidence"] = "low"
                logger.info("CoT self-check: reasoning suggests uncertainty")

        result["_ai_duration_ms"] = elapsed
        result["_model"] = _model_name
        logger.info(f"AI decomposition complete in {elapsed:.0f}ms")
        return result

    except json.JSONDecodeError:
        # AI returned non-JSON — treat as chat
        logger.warning("AI returned non-JSON response, wrapping as chat")
        return {
            "type": "chat",
            "message": response.text if 'response' in dir() else text,
            "_ai_duration_ms": elapsed if 'elapsed' in dir() else 0,
        }
    except Exception as e:
        logger.error(f"AI decomposition failed: {e}")
        return {"type": "error", "message": str(e)}


def analyze_error(
    error_message: str,
    command: str = "",
    layer: int = 1,
    context: Optional[dict] = None,
) -> dict:
    """
    Use Gemini to analyze an error and suggest recovery actions.
    """
    client = _get_client()
    if not client:
        return {"analysis": "AI unavailable", "suggestions": []}

    prompt = f"""Analyze this execution error and suggest recovery steps.

Error: {error_message}
Command: {command}
Execution Layer: {layer}
{f'Context: {json.dumps(context, default=str)}' if context else ''}

Respond with JSON:
{{
  "analysis": "Root cause analysis",
  "severity": "low|medium|high|critical",
  "suggestions": [
    {{"action": "command or step to fix", "description": "What this does", "risk": "low|medium|high"}}
  ],
  "prevent": "How to prevent this in the future"
}}"""

    try:
        response = client.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"AI error analysis failed: {e}")
        return {"analysis": str(e), "suggestions": []}


def chat(message: str, history: Optional[list] = None) -> str:
    """
    General conversation with JAMES AI.
    Returns the AI's text response.
    """
    client = _get_client()
    if not client:
        return "AI features are not available. Set GEMINI_API_KEY in your .env file."

    try:
        if history:
            chat_session = client.start_chat(history=history)
            response = chat_session.send_message(message)
        else:
            response = client.generate_content(
                f"The user is chatting with you. Respond naturally but stay in character as JAMES, "
                f"the autonomous system orchestrator. Be concise and helpful.\n\n"
                f"User: {message}"
            )
        return response.text
    except Exception as e:
        logger.error(f"AI chat failed: {e}")
        return f"AI error: {e}"


def generate_skill_from_history(
    task_name: str,
    execution_log: list[dict],
) -> Optional[dict]:
    """
    Use Gemini to analyze successful execution logs and generate
    a reusable skill definition.
    """
    client = _get_client()
    if not client:
        return None

    prompt = f"""Analyze this successful execution log and generate a reusable skill definition.

Task: {task_name}
Execution Log:
{json.dumps(execution_log, indent=2, default=str)}

Respond with JSON:
{{
  "id": "skill_id_snake_case",
  "name": "Human Readable Name",
  "description": "What this skill does",
  "methods": ["CLI"],
  "steps": [{{"action": "...", "description": "..."}}],
  "preconditions": ["list of requirements"],
  "postconditions": ["expected outcomes"],
  "tags": ["relevant", "tags"]
}}"""

    try:
        response = client.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"AI skill generation failed: {e}")
        return None


def smart_diagnose(system_status: dict, metrics: list, failures: list) -> dict:
    """
    Use Gemini to provide intelligent system diagnosis
    beyond pattern matching.
    """
    client = _get_client()
    if not client:
        return {"diagnosis": "AI unavailable", "recommendations": []}

    prompt = f"""You are analyzing a system orchestrator's health. Provide diagnosis and recommendations.

System Status:
{json.dumps(system_status, indent=2, default=str)}

Recent Metrics (last 20):
{json.dumps(metrics[:20], indent=2, default=str)}

Recent Failures:
{json.dumps(failures[:10], indent=2, default=str)}

Respond with JSON:
{{
  "health_score": 0.0 to 1.0,
  "diagnosis": "Overall assessment",
  "issues": [{{"area": "...", "severity": "...", "description": "..."}}],
  "recommendations": [{{"priority": "high|medium|low", "action": "...", "description": "..."}}],
  "trends": "Observable patterns"
}}"""

    try:
        response = client.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"AI smart diagnosis failed: {e}")
        return {"diagnosis": str(e), "recommendations": []}
