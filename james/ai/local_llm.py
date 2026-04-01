"""
JAMES AI Module — Local LLM via llama-server (OpenAI-compatible API)

Uses the llama-server.exe bundled with Intel AI Playground to serve
a local GGUF model with an OpenAI-compatible chat completions endpoint.

Features:
  - Auto-discovers models from AI Playground model directory
  - Manages llama-server process lifecycle (start/stop)
  - Provides the same AI interface as gemini.py (drop-in replacement)
  - Zero internet dependency — fully offline capable

Configuration priority:
  1. Environment: JAMES_LLM_MODEL_PATH, JAMES_LLM_SERVER_PORT
  2. Auto-discovery from AI Playground install at D:\\VMWare\\AI Playground
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib import request as urllib_request

logger = logging.getLogger("james.ai.local")

# ══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════

_AI_PLAYGROUND_ROOT = r"D:\VMWare\AI Playground"
_LLAMA_SERVER_EXE = os.path.join(
    _AI_PLAYGROUND_ROOT, "resources", "LlamaCPP", "llama-cpp", "llama-server.exe"
)
_GGUF_MODEL_DIR = os.path.join(
    _AI_PLAYGROUND_ROOT, "resources", "models", "llm", "ggufLLM"
)

# Server config
_DEFAULT_PORT = 8787
_DEFAULT_CTX = 8192
_DEFAULT_GPU_LAYERS = 99  # offload all layers to GPU

# Model preference order (best for instruction-following tasks)
_MODEL_PREFERENCE = [
    "Qwen3-4B-Q5_K_S.gguf",
    "Qwen3-4B-Instruct-2507-Q5_K_S.gguf",
    "Qwen3-4B-Claude-Sonnet-4-Reasoning-Distill-Safetensor.Q8_0.gguf",
    "DeepSeek-R1-Distill-Qwen-7B-Q8_0.gguf",
    "smollm2-1.7b-instruct-q4_k_m.gguf",
]

# ══════════════════════════════════════════════════════════════════
# STATE
# ══════════════════════════════════════════════════════════════════

_server_process: Optional[subprocess.Popen] = None
_server_port: int = _DEFAULT_PORT
_active_model: Optional[str] = None
_active_model_name: Optional[str] = None


# ══════════════════════════════════════════════════════════════════
# MODEL DISCOVERY
# ══════════════════════════════════════════════════════════════════

def discover_models() -> list[dict]:
    """
    Scan AI Playground model directory for available GGUF models.
    Returns list of {name, path, size_mb}.
    """
    models = []
    model_dir = os.environ.get("JAMES_LLM_MODEL_DIR", _GGUF_MODEL_DIR)

    if not os.path.isdir(model_dir):
        logger.warning(f"Model directory not found: {model_dir}")
        return models

    for root, dirs, files in os.walk(model_dir):
        for f in files:
            if f.endswith(".gguf") and not f.startswith("mmproj"):
                full_path = os.path.join(root, f)
                size_mb = os.path.getsize(full_path) / (1024 * 1024)
                models.append({
                    "name": f.replace(".gguf", ""),
                    "filename": f,
                    "path": full_path,
                    "size_mb": round(size_mb),
                    "directory": os.path.basename(root),
                })

    # Sort by preference
    def sort_key(m):
        try:
            return _MODEL_PREFERENCE.index(m["filename"])
        except ValueError:
            return 999
    models.sort(key=sort_key)

    return models


def get_best_model() -> Optional[str]:
    """Get the path to the best available model."""
    # Check env override
    env_path = os.environ.get("JAMES_LLM_MODEL_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    models = discover_models()
    if models:
        return models[0]["path"]
    return None


# ══════════════════════════════════════════════════════════════════
# SERVER LIFECYCLE
# ══════════════════════════════════════════════════════════════════

def _is_server_running() -> bool:
    """Check if llama-server is responding."""
    try:
        req = urllib_request.Request(
            f"http://127.0.0.1:{_server_port}/health",
            method="GET",
        )
        with urllib_request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


def start_server(model_path: Optional[str] = None, port: Optional[int] = None) -> bool:
    """
    Start llama-server with the specified model.
    Returns True if server started successfully.
    """
    global _server_process, _server_port, _active_model, _active_model_name

    if _is_server_running():
        logger.info("llama-server already running")
        return True

    model = model_path or get_best_model()
    if not model:
        logger.error("No GGUF model found. Cannot start llama-server.")
        return False

    server_exe = os.environ.get("JAMES_LLAMA_SERVER", _LLAMA_SERVER_EXE)
    if not os.path.isfile(server_exe):
        logger.error(f"llama-server not found at: {server_exe}")
        return False

    _server_port = port or int(os.environ.get("JAMES_LLM_SERVER_PORT", _DEFAULT_PORT))
    ctx_size = int(os.environ.get("JAMES_LLM_CTX_SIZE", _DEFAULT_CTX))
    gpu_layers = int(os.environ.get("JAMES_LLM_GPU_LAYERS", _DEFAULT_GPU_LAYERS))

    cmd = [
        server_exe,
        "--model", model,
        "--port", str(_server_port),
        "--ctx-size", str(ctx_size),
        "--n-gpu-layers", str(gpu_layers),
        "--host", "127.0.0.1",
        "--threads", str(max(4, os.cpu_count() // 2 if os.cpu_count() else 4)),
    ]

    logger.info(f"Starting llama-server on :{_server_port}")
    logger.info(f"  Model: {os.path.basename(model)}")
    logger.info(f"  Context: {ctx_size}, GPU layers: {gpu_layers}")

    try:
        _server_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        # Wait for server to be ready (up to 60 seconds for large models)
        for i in range(60):
            time.sleep(1)
            if _is_server_running():
                _active_model = model
                _active_model_name = Path(model).stem
                logger.info(f"llama-server ready after {i + 1}s")
                return True
            # Check if process died
            if _server_process.poll() is not None:
                stderr = _server_process.stderr.read().decode(errors="replace")
                logger.error(f"llama-server exited with code {_server_process.returncode}")
                logger.error(f"  stderr: {stderr[:500]}")
                _server_process = None
                return False

        logger.error("llama-server timed out (60s)")
        stop_server()
        return False

    except Exception as e:
        logger.error(f"Failed to start llama-server: {e}")
        return False


def stop_server() -> None:
    """Stop the llama-server process."""
    global _server_process, _active_model, _active_model_name
    if _server_process:
        logger.info("Stopping llama-server...")
        try:
            _server_process.terminate()
            _server_process.wait(timeout=5)
        except Exception:
            try:
                _server_process.kill()
            except Exception:
                pass
        _server_process = None
        _active_model = None
        _active_model_name = None


def get_status() -> dict:
    """Get current local LLM status."""
    running = _is_server_running()
    models = discover_models()
    return {
        "available": running or bool(models),
        "server_running": running,
        "active_model": _active_model_name,
        "port": _server_port,
        "models_found": len(models),
        "models": [{"name": m["name"], "size_mb": m["size_mb"]} for m in models[:10]],
        "server_exe_exists": os.path.isfile(_LLAMA_SERVER_EXE),
    }


# ══════════════════════════════════════════════════════════════════
# OPENAI-COMPATIBLE API CALLS
# ══════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """You are JAMES (Justified Autonomous Machine for Execution & Systems).
You are a deterministic, self-evolving autonomous system orchestrator on Windows.

CRITICAL MEMORY RULE:
Your context may include a "long_term_memory" field. ALWAYS check it first before doing any other action.
If the user asks about their preferences, projects, or any personal fact, and the answer is in "long_term_memory", respond immediately with a FORMAT 2 chat response including the answer.
NEVER say "I don't have access to personal information" — you DO have access via your memory system.

YOUR CAPABILITIES (55+ registered tools via tool_call):
- Execute commands (cmd.exe, PowerShell) via Layer 1
- File operations: file_read, file_write, file_list, file_copy, file_delete, file_search, file_info
- Manage processes, services, and system resources
- Browse the web: web_search, web_browse, web_read_article, web_crawl
- Memory tools: memory_save, memory_search, memory_get

MEMORY TOOL EXACT SIGNATURES (use these exactly):
  memory_save:   {"type": "tool_call", "target": "memory_save",   "kwargs": {"key": "name", "value": "data", "category": "tag"}}
  memory_search: {"type": "tool_call", "target": "memory_search", "kwargs": {"query": "your search term here"}}
  memory_get:    {"type": "tool_call", "target": "memory_get",    "kwargs": {"key": "exact_key_name"}}

RESPONSE FORMAT — respond with exactly ONE of these:

FORMAT 1 — For tasks, lookups, or tool usage (ALWAYS use layer 1 for tool_call):
{"intent": "what the user wants", "steps": [{"name": "step_name", "action": {"type": "tool_call", "target": "tool_name", "kwargs": {"param": "value"}}, "layer": 1, "description": "what this does"}], "reasoning": "why these steps"}

FORMAT 2 — Only for greetings or questions answerable from context:
{"type": "chat", "message": "your concise answer here"}

STRICT RULES:
- Always include "layer": 1 on every step that uses tool_call.
- NEVER omit "kwargs" — use {} if no args needed.
- NEVER return a bare {"type": "tool_call", ...} — ALWAYS wrap in steps array.
- Always respond with valid JSON only. No markdown, no code fences, no explanation outside JSON.

REASONING REQUIREMENT:
Before producing your JSON response, you MUST think through the problem step by step inside a <thinking> block.
This block will be stripped from the final output but helps you reason correctly.

Example:
<thinking>
The user asked about their favorite color. I see in long_term_memory that favorite_color = blue.
I can answer directly without a tool call.
</thinking>
{"type": "chat", "message": "Your favorite color is blue."}"""


def _call_api(messages: list[dict], temperature: float = 0.3,
              max_tokens: int = 2048) -> Optional[str]:
    """
    Call the local llama-server's OpenAI-compatible chat completions API.
    """
    if not _is_server_running():
        if not start_server():
            return None

    payload = json.dumps({
        "model": "local",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")

    req = urllib_request.Request(
        f"http://127.0.0.1:{_server_port}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"Local LLM API call failed: {e}")
    return None


def _parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling common issues."""
    if not text:
        return {"type": "error", "message": "Empty response from model"}

    text = text.strip()

    # Strip code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # Strip <think>...</think> blocks (DeepSeek-R1 style)
    if "<think>" in text:
        import re
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON within the text
    for start_char in ["{", "["]:
        idx = text.find(start_char)
        if idx >= 0:
            # Find matching end
            bracket_count = 0
            end_char = "}" if start_char == "{" else "]"
            for i in range(idx, len(text)):
                if text[i] == start_char:
                    bracket_count += 1
                elif text[i] == end_char:
                    bracket_count -= 1
                    if bracket_count == 0:
                        try:
                            return json.loads(text[idx:i + 1])
                        except json.JSONDecodeError:
                            break

    # Couldn't parse — return as chat message
    return {"type": "chat", "message": text}


# ══════════════════════════════════════════════════════════════════
# PUBLIC API (same interface as gemini.py)
# ══════════════════════════════════════════════════════════════════

def is_available() -> bool:
    """Check if local LLM is available (server running or models exist)."""
    if _is_server_running():
        return True
    return bool(get_best_model()) and os.path.isfile(
        os.environ.get("JAMES_LLAMA_SERVER", _LLAMA_SERVER_EXE)
    )


def decompose_task(user_input: str, context: Optional[dict] = None,
                    chat_history: Optional[list[dict]] = None) -> dict:
    """Decompose a natural language task into an execution plan."""
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

    if context:
        ctx_json = json.dumps(context, default=str)
        # Truncate context to prevent exceeding context window
        if len(ctx_json) > 8000:
            # Prioritize: keep tools, trim skills/memory
            trimmed = {k: v for k, v in context.items()
                       if k in ('os', 'project_root', 'available_layers',
                                'available_tools', '_detected_intent',
                                '_intent_hint')}
            ctx_json = json.dumps(trimmed, default=str)
            logger.debug(f"Context trimmed from {len(json.dumps(context, default=str))} to {len(ctx_json)} chars")
        messages.append({
            "role": "system",
            "content": f"System context: {ctx_json}",
        })

    # Inject conversation history for multi-turn awareness
    if chat_history:
        for msg in chat_history[-10:]:  # keep last 10 turns to stay within ctx
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content[:500]})

    messages.append({"role": "user", "content": user_input})

    # ── Model Router: select optimal tier ────────────────────
    route_tier = "balanced"
    route_tokens = 2048
    route_temp = 0.3
    try:
        from james.ai.router import ModelRouter
        detected_intent = ""
        detected_confidence = 0.0
        if context:
            detected_intent = context.get("_detected_intent", "")
            detected_confidence = context.get("_intent_confidence", 0.0)
        router = ModelRouter(available_models=discover_models())
        decision = router.route(detected_intent, detected_confidence, user_input)
        route_tier = decision.tier
        route_tokens = decision.max_tokens
        route_temp = decision.temperature
    except Exception:
        pass  # fallback to defaults

    start = time.time()
    response = _call_api(messages, temperature=route_temp, max_tokens=route_tokens)
    elapsed = (time.time() - start) * 1000

    if response is None:
        return {"type": "error", "message": "Local LLM unavailable"}

    # ── Chain-of-Thought extraction ─────────────────────────
    reasoning_chain = ""
    if "<thinking>" in response:
        import re
        match = re.search(r"<thinking>(.*?)</thinking>", response, re.DOTALL)
        if match:
            reasoning_chain = match.group(1).strip()
        response = re.sub(r"<thinking>.*?</thinking>", "", response, flags=re.DOTALL).strip()

    result = _parse_json_response(response)

    # Store reasoning chain for audit trail
    if reasoning_chain:
        result["_reasoning_chain"] = reasoning_chain

    # ── CoT self-verification ──────────────────────────────
    if reasoning_chain and result.get("type") == "chat":
        chain_lower = reasoning_chain.lower()
        uncertainty_markers = ["don't know", "not sure", "unsure", "need to search",
                               "need to look", "cannot find", "no information"]
        if any(marker in chain_lower for marker in uncertainty_markers):
            result["_confidence"] = "low"
            logger.info("CoT self-check: reasoning suggests uncertainty but answer is direct")

    # ── Normalize bare tool_call responses into proper plans ──
    if result.get("type") == "tool_call" and "steps" not in result:
        tool_target = result.get("target", "unknown_tool")
        tool_kwargs = result.get("kwargs", {})
        tool_desc = result.get("description", f"Call {tool_target}")
        result = {
            "intent": tool_desc,
            "steps": [{
                "name": f"call_{tool_target}",
                "action": {
                    "type": "tool_call",
                    "target": tool_target,
                    "kwargs": tool_kwargs,
                },
                "layer": 1,
                "description": tool_desc,
            }],
            "reasoning": f"AI autonomously selected tool '{tool_target}' to fulfill the request.",
        }
        # Preserve reasoning chain through normalization
        if reasoning_chain:
            result["_reasoning_chain"] = reasoning_chain

    # ── Apply output guardrails ────────────────────────────
    try:
        from james.ai.guardrails import OutputGuardrails
        guardrails = OutputGuardrails()
        gr = guardrails.check(result)
        if gr.violations:
            logger.warning(f"Guardrail violations: {gr.violations}")
            result = gr.filtered_output
            result["_guardrail_violations"] = gr.violations
    except ImportError:
        pass  # guardrails module not available

    result["_ai_duration_ms"] = elapsed
    result["_model"] = _active_model_name or "local"
    result["_route_tier"] = route_tier
    return result


def synthesize_results(intent: str, results: list) -> dict:
    """Synthesize execution results into a final answer for the user."""
    # If results are empty or trivial, return a canned response
    if not results:
        return {"text": "Task completed successfully.", "duration_ms": 0}

    prompt = f"""You are JAMES. The user asked: "{intent}"
Here are the execution results:

{json.dumps(results, indent=2, default=str)[:3500]}

Respond with a concise, direct answer to the user's question based on these results.
Do not include any meta-commentary about your thought process."""

    messages = [
        {"role": "system", "content": "You are a helpful assistant that summarizes data concisely."},
        {"role": "user", "content": prompt},
    ]

    start = time.time()
    try:
        response = _call_api(messages, temperature=0.2)
    except Exception:
        response = None
    elapsed = (time.time() - start) * 1000

    if not response:
        # Fallback: extract key data from results directly
        fallback_text = "Results:\n" + "\n".join(
            str(r)[:200] for r in results[:5]
        )
        return {"text": fallback_text, "duration_ms": elapsed}

    # Clean up reasoning blocks
    if "<thinking>" in response:
        import re
        response = re.sub(r"<thinking>.*?</thinking>", "", response, flags=re.DOTALL).strip()

    # Apply guardrails to synthesis output
    try:
        from james.ai.guardrails import OutputGuardrails
        response = OutputGuardrails().filter_synthesis(response)
    except ImportError:
        pass

    return {
        "text": response.strip(),
        "duration_ms": elapsed
    }


def analyze_error(
    error_message: str,
    command: str = "",
    layer: int = 1,
    context: Optional[dict] = None,
) -> dict:
    """Analyze an error and suggest recovery."""
    prompt = f"""Analyze this execution error and suggest recovery steps.

Error: {error_message}
Command: {command}
Execution Layer: {layer}

Respond with JSON:
{{
  "analysis": "Root cause analysis",
  "severity": "low|medium|high|critical",
  "suggestions": [
    {{"action": "command or step to fix", "description": "What this does", "risk": "low|medium|high"}}
  ],
  "prevent": "How to prevent this in the future"
}}"""

    messages = [
        {"role": "system", "content": "You are a system diagnostics expert. Always respond with valid JSON."},
        {"role": "user", "content": prompt},
    ]

    response = _call_api(messages)
    if response:
        return _parse_json_response(response)
    return {"analysis": "Local LLM unavailable", "suggestions": []}


def chat(message: str, history: Optional[list] = None) -> str:
    """Conversational chat with JAMES."""
    messages = [{
        "role": "system",
        "content": "You are JAMES, an autonomous system orchestrator. Be concise, helpful, and stay in character.",
    }]

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": message})

    response = _call_api(messages, temperature=0.7)
    return response or "Local LLM is not available."


def generate_skill_from_history(task_name: str, execution_log: list[dict]) -> Optional[dict]:
    """Generate a skill definition from execution history."""
    prompt = f"""Analyze this successful execution and generate a reusable skill definition.

Task: {task_name}
Log: {json.dumps(execution_log, indent=2, default=str)[:2000]}

Respond with JSON:
{{
  "id": "skill_id_snake_case",
  "name": "Human Name",
  "description": "What this skill does",
  "methods": ["CLI"],
  "steps": [{{"action": "...", "description": "..."}}],
  "preconditions": ["requirements"],
  "postconditions": ["outcomes"],
  "tags": ["tags"]
}}"""

    messages = [
        {"role": "system", "content": "You are a skill extraction engine. Always respond with valid JSON."},
        {"role": "user", "content": prompt},
    ]

    response = _call_api(messages)
    if response:
        result = _parse_json_response(response)
        if result.get("id"):
            return result
    return None


def smart_diagnose(system_status: dict, metrics: list, failures: list) -> dict:
    """AI-powered system diagnosis."""
    prompt = f"""Analyze this system orchestrator's health.

Status: {json.dumps(system_status, indent=2, default=str)[:1000]}
Metrics (last 20): {json.dumps(metrics[:20], indent=2, default=str)[:1000]}
Failures: {json.dumps(failures[:10], indent=2, default=str)[:1000]}

Respond with JSON:
{{
  "health_score": 0.0 to 1.0,
  "diagnosis": "Overall assessment",
  "issues": [{{"area": "...", "severity": "...", "description": "..."}}],
  "recommendations": [{{"priority": "high|medium|low", "action": "...", "description": "..."}}],
  "trends": "Observable patterns"
}}"""

    messages = [
        {"role": "system", "content": "You are a system health analyst. Always respond with valid JSON."},
        {"role": "user", "content": prompt},
    ]

    response = _call_api(messages)
    if response:
        return _parse_json_response(response)
    return {"diagnosis": "Local LLM unavailable", "recommendations": []}
