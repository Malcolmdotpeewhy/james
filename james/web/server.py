"""
JAMES Web Server — Flask API + Dashboard

Provides:
  - REST API for all JAMES operations
  - Premium dark-mode web dashboard
  - Live command execution terminal
  - System monitoring panels

Usage:
    python -m james.web                     # Start on port 7700
    python -m james.web --port 8080         # Custom port
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

from flask import Flask, jsonify, request, render_template_string

# Add project root to path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from james.orchestrator import Orchestrator

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# Single orchestrator instance
_orch: Orchestrator | None = None


def _get_orch() -> Orchestrator:
    global _orch
    if _orch is None:
        _orch = Orchestrator(project_root=_PROJECT_ROOT)
    return _orch


# ══════════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════════

@app.route("/api/status")
def api_status():
    """Get system status."""
    try:
        return jsonify(_get_orch().status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/run", methods=["POST"])
def api_run():
    """Execute a task."""
    data = request.get_json(force=True)
    task = data.get("task", "")
    if not task:
        return jsonify({"error": "No task provided"}), 400

    try:
        orch = _get_orch()
        start = time.time()
        graph = orch.run(task)
        elapsed = (time.time() - start) * 1000

        nodes = []
        for nid, node in graph.nodes.items():
            node_data = {
                "id": nid,
                "name": node.name,
                "state": node.state.value,
                "result": None,
            }
            if node.result:
                node_data["result"] = {
                    "success": node.result.success,
                    "output": node.result.output,
                    "error": node.result.error,
                    "duration_ms": node.result.duration_ms,
                    "layer_used": node.result.layer_used,
                    "attempts": node.result.attempts,
                }
            nodes.append(node_data)

        done, total = graph.progress
        return jsonify({
            "graph": graph.name,
            "completed": done,
            "total": total,
            "has_failures": graph.has_failures,
            "duration_ms": elapsed,
            "nodes": nodes,
        })
    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/cmd", methods=["POST"])
def api_cmd():
    """Quick command execution."""
    data = request.get_json(force=True)
    command = data.get("command", "")
    layer = data.get("layer", 1)
    if not command:
        return jsonify({"error": "No command provided"}), 400

    try:
        result = _get_orch().run_command(command, layer=layer)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stream")
def api_stream():
    """Stream execution events via SSE."""
    from flask import Response
    from james.stream import SSEStreamer
    orch = _get_orch()
    
    # Check if streamer is initialized
    if not hasattr(orch, "streamer"):
        return jsonify({"error": "Streaming not available"}), 404
        
    return Response(
        SSEStreamer.generate(orch.streamer),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.route("/api/layers")
def api_layers():
    """Get authority layer status."""
    orch = _get_orch()
    available = orch.layers.get_available()
    layers = []
    for level in range(1, 6):
        from james.layers import LayerLevel
        ll = LayerLevel(level)
        layer = orch.layers.get(ll)
        if layer:
            layers.append({
                "level": level,
                "name": layer.name,
                "description": layer.description,
                "available": layer in available,
            })
    return jsonify(layers)


@app.route("/api/skills")
def api_skills():
    """List skills."""
    orch = _get_orch()
    skills = orch.skills.list_all()
    return jsonify([{
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "confidence": round(s.confidence_score, 3),
        "executions": s.execution_count,
        "success_rate": round(s.success_rate, 3),
        "methods": s.methods,
        "tags": s.tags,
    } for s in skills])


@app.route("/api/memory")
def api_memory():
    """Get memory stats."""
    return jsonify(_get_orch().memory.get_stats())


@app.route("/api/metrics")
def api_metrics():
    """Get recent metrics."""
    limit = request.args.get("limit", 30, type=int)
    return jsonify(_get_orch().memory.get_metrics(limit=limit))


@app.route("/api/audit")
def api_audit():
    """Get audit log."""
    count = request.args.get("count", 50, type=int)
    return jsonify(_get_orch().audit.read_recent(count))


@app.route("/api/diagnose")
def api_diagnose():
    """Run diagnostics."""
    report = _get_orch().optimizer.diagnose()
    return jsonify({
        "total_issues": report.total_issues,
        "bottlenecks": report.bottlenecks,
        "instability": report.instability,
        "inefficiencies": report.inefficiencies,
    })


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    """Run improvement cycle."""
    return jsonify(_get_orch().improve())


@app.route("/api/bootstrap", methods=["POST"])
def api_bootstrap():
    """Run system bootstrap."""
    from james.bootstrap import run_bootstrap
    orch = _get_orch()
    result = run_bootstrap(orch.memory, orch.skills)
    return jsonify(result)


@app.route("/api/tools")
def api_tools():
    """List all registered tools."""
    orch = _get_orch()
    tools = orch.tools.list_tools()
    return jsonify(tools)


@app.route("/api/tools/call", methods=["POST"])
def api_tools_call():
    """Call a registered tool directly."""
    data = request.get_json(force=True)
    name = data.get("name", "")
    kwargs = data.get("kwargs", {})
    if not name:
        return jsonify({"error": "No tool name provided"}), 400
    try:
        orch = _get_orch()
        result = orch.tools.call(name, **kwargs)
        return jsonify({"tool": name, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


_chat_history: list[dict] = []  # In-memory conversation history


@app.route("/api/ai/chat", methods=["POST"])
def api_ai_chat():
    """Chat with JAMES AI."""
    data = request.get_json(force=True)
    message = data.get("message", "")
    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        # ── Intent classification (<1ms) ──
        from james.ai.classifier import IntentClassifier
        classifier = IntentClassifier()
        intent, confidence = classifier.classify(message)

        # ── Short-circuit for trivial intents ──
        short_circuit = classifier.get_short_circuit_response(intent, confidence)
        if short_circuit:
            _chat_history.append({"role": "user", "content": message})
            _chat_history.append({"role": "assistant", "content": short_circuit})
            while len(_chat_history) > 20:
                _chat_history.pop(0)
            return jsonify({
                "type": "chat",
                "message": short_circuit,
                "duration_ms": 0,
                "model": "classifier",
                "intent": intent,
                "confidence": confidence,
            })

        from james import ai as james_ai
        if not james_ai.is_available():
            return jsonify({"error": "AI unavailable. Start local model or set GEMINI_API_KEY."}), 503

        # ── Inject LTM + orchestrator context + intent hint ──
        orch = _get_orch()
        context = orch._build_ai_context(message)
        intent_hint = classifier.get_intent_hint(intent, confidence)
        if intent_hint:
            context["_intent_hint"] = intent_hint
            context["_detected_intent"] = intent

        # ── Pass conversation history for multi-turn ──
        result = james_ai.decompose_task(
            message,
            context=context,
            chat_history=_chat_history,
        )

        # ── Store in conversation history (memory + persistent) ──
        _chat_history.append({"role": "user", "content": message})
        try:
            orch.conversations.save_message("web_default", "user", message)
        except Exception:
            pass

        if result.get("type") == "chat":
            _chat_history.append({"role": "assistant", "content": result.get("message", "")})
            try:
                orch.conversations.save_message(
                    "web_default", "assistant", result.get("message", ""),
                    metadata={"intent": intent, "model": result.get("_model", "")},
                )
            except Exception:
                pass
        elif result.get("intent"):
            _chat_history.append({"role": "assistant", "content": f"[Executed plan: {result.get('intent', '')}]"})
        # Trim history to last 20 turns
        while len(_chat_history) > 20:
            _chat_history.pop(0)

        if result.get("type") == "chat":
            return jsonify({
                "type": "chat",
                "message": result.get("message", ""),
                "duration_ms": result.get("_ai_duration_ms", 0),
                "model": result.get("_model", ""),
                "intent": intent,
                "confidence": confidence,
            })
        elif result.get("steps"):
            return jsonify({
                "type": "plan",
                "intent": result.get("intent", ""),
                "reasoning": result.get("reasoning", ""),
                "steps": result.get("steps", []),
                "duration_ms": result.get("_ai_duration_ms", 0),
                "model": result.get("_model", ""),
            })
        else:
            return jsonify({
                "type": "chat",
                "message": str(result),
                "duration_ms": result.get("_ai_duration_ms", 0),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/chat/clear", methods=["POST"])
def api_ai_chat_clear():
    """Clear the conversation history."""
    global _chat_history
    _chat_history = []
    return jsonify({"status": "cleared"})


@app.route("/api/ai/execute", methods=["POST"])
def api_ai_execute():
    """Execute an AI-generated plan."""
    data = request.get_json(force=True)
    plan = data.get("plan", {})
    if not plan or not plan.get("steps"):
        return jsonify({"error": "No plan provided"}), 400

    try:
        orch = _get_orch()
        task = {
            "name": plan.get("intent", "ai_task"),
            "steps": plan["steps"],
        }
        start = time.time()
        graph = orch.run(task)
        elapsed = (time.time() - start) * 1000

        nodes = []
        for nid, node in graph.nodes.items():
            nd = {"id": nid, "name": node.name, "state": node.state.value, "result": None}
            if node.result:
                nd["result"] = {
                    "success": node.result.success,
                    "output": node.result.output,
                    "error": node.result.error,
                    "duration_ms": node.result.duration_ms,
                }
            nodes.append(nd)

        done, total = graph.progress
        return jsonify({
            "completed": done, "total": total,
            "has_failures": graph.has_failures,
            "duration_ms": elapsed, "nodes": nodes,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/synthesize", methods=["POST"])
def api_ai_synthesize():
    """Synthesize execution results into a chat response."""
    data = request.get_json(force=True)
    intent = data.get("intent", "task")
    nodes = data.get("nodes", [])

    try:
        from james import ai as james_ai
        if not james_ai.is_available():
            return jsonify({"error": "AI unavailable"}), 503

        # Pluck outputs for synthesis
        results = []
        for n in nodes:
            name = n.get("name", "")
            output = n.get("result", {}).get("output", "")
            if output:
                results.append(f"Output for step '{name}':\n{str(output)[:1000]}")

        if not results:
            return jsonify({"text": "The plan was executed successfully, but no notable output was returned."})

        synth = james_ai.synthesize_results(intent=intent, results=results)
        return jsonify(synth)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/analyze", methods=["POST"])
def api_ai_analyze():
    """AI error analysis."""
    data = request.get_json(force=True)
    try:
        from james import ai as james_ai
        result = james_ai.analyze_error(
            error_message=data.get("error", ""),
            command=data.get("command", ""),
            layer=data.get("layer", 1),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/diagnose", methods=["POST"])
def api_ai_diagnose():
    """AI-powered system diagnosis."""
    try:
        from james import ai as james_ai
        orch = _get_orch()
        status = orch.status()
        metrics = orch.memory.get_metrics(limit=20)
        failures = orch.failures.get_history()
        result = james_ai.smart_diagnose(status, metrics, failures)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/models")
def api_ai_models():
    """List available local GGUF models."""
    try:
        from james import ai as james_ai
        models = james_ai.discover_local_models()
        return jsonify(models)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/start", methods=["POST"])
def api_ai_start():
    """Start local llama-server with a specific model."""
    data = request.get_json(force=True) if request.data else {}
    model_path = data.get("model_path")
    try:
        from james import ai as james_ai
        success = james_ai.start_local_server(model_path=model_path)
        # Reset cached AI availability
        orch = _get_orch()
        orch._ai_available = None

        if success:
            info = james_ai.get_backend_info()
            return jsonify({"status": "started", **info})
        else:
            return jsonify({"error": "Failed to start llama-server. Check logs."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/stop", methods=["POST"])
def api_ai_stop():
    """Stop local llama-server."""
    try:
        from james import ai as james_ai
        james_ai.stop_local_server()
        orch = _get_orch()
        orch._ai_available = None
        return jsonify({"status": "stopped"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/status")
def api_ai_status():
    """Get AI backend status."""
    try:
        from james import ai as james_ai
        return jsonify(james_ai.get_backend_info())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════

@app.route("/")
def dashboard():
    """Serve the JAMES dashboard."""
    return render_template_string(DASHBOARD_HTML)


# ══════════════════════════════════════════════════════════════════
# DASHBOARD HTML (inline for zero-dependency deployment)
# ══════════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JAMES - Autonomous System Orchestrator</title>
<meta name="description" content="JAMES Control Dashboard - Justified Autonomous Machine for Execution & Systems">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg-primary:#0a0e17;
  --bg-secondary:#111827;
  --bg-card:#1a1f2e;
  --bg-card-hover:#222840;
  --bg-glass:rgba(26,31,46,0.7);
  --border:#2a3148;
  --border-glow:rgba(99,179,237,0.15);
  --text-primary:#e2e8f0;
  --text-secondary:#94a3b8;
  --text-muted:#64748b;
  --accent:#63b3ed;
  --accent-glow:rgba(99,179,237,0.3);
  --success:#48bb78;
  --warning:#ecc94b;
  --danger:#fc8181;
  --purple:#b794f6;
  --cyan:#76e4f7;
  --gradient-primary:linear-gradient(135deg,#63b3ed 0%,#b794f6 100%);
  --gradient-dark:linear-gradient(180deg,#0a0e17 0%,#111827 100%);
  --radius:12px;
  --radius-sm:8px;
  --shadow:0 4px 24px rgba(0,0,0,0.4);
  --shadow-glow:0 0 30px rgba(99,179,237,0.08);
}
body{
  font-family:'Inter',system-ui,-apple-system,sans-serif;
  background:var(--gradient-dark);
  color:var(--text-primary);
  min-height:100vh;
  overflow-x:hidden;
}
/* Ambient glow */
body::before{
  content:'';position:fixed;top:-40%;left:-20%;width:80%;height:80%;
  background:radial-gradient(circle,rgba(99,179,237,0.04) 0%,transparent 70%);
  pointer-events:none;z-index:0;
}
body::after{
  content:'';position:fixed;bottom:-30%;right:-10%;width:60%;height:60%;
  background:radial-gradient(circle,rgba(183,148,246,0.03) 0%,transparent 70%);
  pointer-events:none;z-index:0;
}

/* ── Header ─────────────────── */
.header{
  position:sticky;top:0;z-index:100;
  backdrop-filter:blur(20px);
  background:rgba(10,14,23,0.85);
  border-bottom:1px solid var(--border);
  padding:16px 32px;
  display:flex;align-items:center;justify-content:space-between;
}
.header-left{display:flex;align-items:center;gap:16px}
.logo{
  font-size:28px;font-weight:700;
  background:var(--gradient-primary);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  letter-spacing:2px;
}
.logo-sub{font-size:11px;color:var(--text-muted);letter-spacing:1px;text-transform:uppercase;margin-top:2px}
.status-pill{
  display:inline-flex;align-items:center;gap:6px;
  padding:6px 14px;border-radius:20px;font-size:12px;font-weight:500;
  background:rgba(72,187,120,0.12);color:var(--success);border:1px solid rgba(72,187,120,0.2);
}
.status-pill::before{content:'';width:7px;height:7px;border-radius:50%;background:var(--success);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* ── Nav Tabs ───────────────── */
.nav{
  display:flex;gap:4px;padding:0 32px 0;margin-top:4px;
  border-bottom:1px solid var(--border);
  background:rgba(10,14,23,0.5);
}
.nav-tab{
  padding:12px 20px;font-size:13px;font-weight:500;color:var(--text-muted);
  cursor:pointer;border-bottom:2px solid transparent;transition:all .2s;
  background:none;border-top:none;border-left:none;border-right:none;
}
.nav-tab:hover{color:var(--text-secondary)}
.nav-tab.active{color:var(--accent);border-bottom-color:var(--accent)}

/* ── Main Layout ────────────── */
.main{padding:24px 32px;position:relative;z-index:1;max-width:1600px;margin:0 auto}
.panel{display:none}
.panel.active{display:block;animation:fadeIn .3s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

/* ── Cards ──────────────────── */
.card{
  background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);
  padding:20px 24px;margin-bottom:16px;
  transition:border-color .2s,box-shadow .2s;
}
.card:hover{border-color:var(--border-glow);box-shadow:var(--shadow-glow)}
.card-title{font-size:14px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:1px;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.card-title .icon{font-size:16px}

/* ── Grid ───────────────────── */
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.grid-2{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
@media(max-width:1200px){.grid-4{grid-template-columns:repeat(2,1fr)}}
@media(max-width:800px){.grid-4,.grid-3,.grid-2{grid-template-columns:1fr}}

/* ── Stat Cards ─────────────── */
.stat{text-align:center;padding:24px 16px}
.stat-value{font-size:32px;font-weight:700;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat-label{font-size:12px;color:var(--text-muted);margin-top:4px;text-transform:uppercase;letter-spacing:1px}

/* ── AI Quick-Action Chips ──── */
.ai-chip{
  padding:6px 14px;border-radius:20px;font-size:12px;
  background:rgba(183,148,246,0.08);border:1px solid rgba(183,148,246,0.2);
  color:var(--purple);cursor:pointer;transition:all .2s;font-family:Inter,sans-serif;
}
.ai-chip:hover{background:rgba(183,148,246,0.18);border-color:rgba(183,148,246,0.4);transform:translateY(-1px)}

/* ── Markdown in Chat ────────── */
.ai-md h1,.ai-md h2,.ai-md h3{color:var(--text-primary);margin:8px 0 4px}
.ai-md h1{font-size:16px} .ai-md h2{font-size:14px} .ai-md h3{font-size:13px}
.ai-md p{margin:4px 0}
.ai-md ul,.ai-md ol{margin:4px 0 4px 16px;padding-left:8px}
.ai-md li{margin:2px 0}
.ai-md code{background:rgba(99,179,237,0.1);padding:2px 6px;border-radius:4px;font-size:12px;font-family:'JetBrains Mono',monospace}
.ai-md pre{background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin:6px 0;overflow-x:auto;font-size:12px}
.ai-md pre code{background:none;padding:0;font-size:12px}
.ai-md blockquote{border-left:3px solid var(--accent);padding-left:12px;margin:6px 0;color:var(--text-muted)}
.ai-md a{color:var(--accent);text-decoration:none}
.ai-md a:hover{text-decoration:underline}
.ai-md table{border-collapse:collapse;margin:6px 0;width:100%}
.ai-md th,.ai-md td{border:1px solid var(--border);padding:4px 8px;font-size:12px}
.ai-md th{background:var(--bg-secondary);color:var(--text-primary);font-weight:600}
.ai-md strong{color:var(--text-primary)}
.ai-md em{color:var(--accent)}

/* ── Chat Animations ─────────── */
@keyframes msgSlide{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
@keyframes dotBlink{0%,20%{opacity:0}40%{opacity:1}60%{opacity:0}80%,100%{opacity:0}}
.ai-msg{animation:msgSlide .3s ease}
.dots::after{content:'...';letter-spacing:2px}
.dots span:nth-child(1){animation:dotBlink 1.4s infinite 0s}
.dots span:nth-child(2){animation:dotBlink 1.4s infinite .2s}
.dots span:nth-child(3){animation:dotBlink 1.4s infinite .4s}

/* ── Copy / Action Buttons ───── */
.msg-actions{display:flex;gap:4px;margin-top:6px;opacity:0;transition:opacity .2s}
.ai-bubble:hover .msg-actions{opacity:1}
.msg-action-btn{
  padding:2px 8px;font-size:10px;border-radius:4px;cursor:pointer;
  background:rgba(99,179,237,0.06);border:1px solid rgba(99,179,237,0.15);
  color:var(--text-muted);transition:all .15s;font-family:Inter,sans-serif;
}
.msg-action-btn:hover{background:rgba(99,179,237,0.15);color:var(--accent);border-color:rgba(99,179,237,0.3)}

/* ── Collapsible Details ──────── */
.exec-details{max-height:0;overflow:hidden;transition:max-height .3s ease}
.exec-details.open{max-height:600px;overflow-y:auto}
.exec-toggle{
  cursor:pointer;font-size:11px;color:var(--accent);
  display:inline-flex;align-items:center;gap:4px;margin-top:6px;
  background:none;border:none;font-family:Inter,sans-serif;padding:2px 0;
}
.exec-toggle:hover{color:var(--text-primary)}
.exec-toggle .arrow{transition:transform .2s;display:inline-block}
.exec-toggle.open .arrow{transform:rotate(90deg)}

/* ── Status Info Bar ─────────── */
.ai-status-bar{
  display:flex;align-items:center;gap:12px;padding:6px 16px;
  border-bottom:1px solid var(--border);font-size:11px;color:var(--text-muted);
  background:rgba(10,14,23,0.4);
}
.ai-status-bar .dot{width:6px;height:6px;border-radius:50%;display:inline-block}
.ai-status-bar .dot.on{background:var(--success);box-shadow:0 0 6px rgba(72,187,120,0.4)}
.ai-status-bar .dot.off{background:var(--danger)}

/* ── Progress Bar ────────────── */
.exec-progress{
  height:3px;background:var(--border);border-radius:2px;margin:8px 0;overflow:hidden;
}
.exec-progress-fill{
  height:100%;background:var(--gradient-primary);border-radius:2px;
  transition:width .5s ease;
}

/* ── Chat Scrollbar ──────────── */
#aiChatMessages::-webkit-scrollbar{width:5px}
#aiChatMessages::-webkit-scrollbar-track{background:transparent}
#aiChatMessages::-webkit-scrollbar-thumb{background:rgba(148,163,184,0.2);border-radius:3px}
#aiChatMessages::-webkit-scrollbar-thumb:hover{background:rgba(148,163,184,0.4)}

/* ── Terminal ───────────────── */
.terminal{
  background:#0d1117;border:1px solid #21262d;border-radius:var(--radius);
  font-family:'JetBrains Mono',monospace;overflow:hidden;
}
.terminal-header{
  display:flex;align-items:center;gap:8px;padding:10px 16px;
  background:#161b22;border-bottom:1px solid #21262d;
}
.terminal-dot{width:12px;height:12px;border-radius:50%}
.terminal-dot.red{background:#ff5f57}.terminal-dot.yellow{background:#febc2e}.terminal-dot.green{background:#28c840}
.terminal-title{font-size:12px;color:var(--text-muted);margin-left:8px}
.terminal-body{
  padding:16px;min-height:300px;max-height:500px;overflow-y:auto;
  font-size:13px;line-height:1.7;
}
.terminal-body::-webkit-scrollbar{width:6px}
.terminal-body::-webkit-scrollbar-thumb{background:#333;border-radius:3px}
.terminal-line{margin-bottom:2px;white-space:pre-wrap;word-break:break-all}
.terminal-line.output{color:#8b949e}
.terminal-line.success{color:var(--success)}
.terminal-line.error{color:var(--danger)}
.terminal-line.info{color:var(--accent)}
.terminal-line.system{color:var(--purple);font-style:italic}
.terminal-input-row{
  display:flex;align-items:center;gap:8px;padding:12px 16px;
  border-top:1px solid #21262d;background:#0d1117;
}
.terminal-prompt{color:var(--accent);font-family:'JetBrains Mono',monospace;font-size:13px;white-space:nowrap}
#cmdInput{
  flex:1;background:transparent;border:none;outline:none;
  color:var(--text-primary);font-family:'JetBrains Mono',monospace;font-size:13px;
}

/* ── Layer Bars ─────────────── */
.layer-item{
  display:flex;align-items:center;gap:16px;padding:14px 20px;
  border-bottom:1px solid var(--border);transition:background .2s;
}
.layer-item:last-child{border-bottom:none}
.layer-item:hover{background:var(--bg-card-hover)}
.layer-num{
  width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;
  font-weight:700;font-size:14px;
}
.layer-num.ok{background:rgba(72,187,120,0.15);color:var(--success);border:1px solid rgba(72,187,120,0.3)}
.layer-num.off{background:rgba(100,116,139,0.15);color:var(--text-muted);border:1px solid rgba(100,116,139,0.3)}
.layer-info{flex:1}
.layer-name{font-weight:600;font-size:14px}
.layer-desc{font-size:12px;color:var(--text-muted);margin-top:2px}
.badge{
  padding:4px 10px;border-radius:12px;font-size:11px;font-weight:600;
}
.badge.ok{background:rgba(72,187,120,0.12);color:var(--success)}
.badge.off{background:rgba(100,116,139,0.12);color:var(--text-muted)}

/* ── Skill Cards ────────────── */
.skill-card{padding:16px 20px}
.skill-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.skill-id{font-weight:600;font-size:14px;color:var(--accent)}
.skill-conf{font-size:24px;font-weight:700}
.skill-desc{font-size:12px;color:var(--text-muted);margin-bottom:10px}
.skill-tags{display:flex;gap:6px;flex-wrap:wrap}
.skill-tag{
  padding:3px 8px;border-radius:6px;font-size:10px;font-weight:500;
  background:rgba(99,179,237,0.08);color:var(--accent);border:1px solid rgba(99,179,237,0.15);
}
.skill-bar{height:4px;border-radius:2px;background:rgba(255,255,255,0.06);margin-top:10px;overflow:hidden}
.skill-bar-fill{height:100%;border-radius:2px;background:var(--gradient-primary);transition:width .6s ease}

/* ── Audit Table ────────────── */
.audit-table{width:100%;border-collapse:collapse;font-size:13px}
.audit-table th{
  text-align:left;padding:10px 14px;color:var(--text-muted);font-weight:500;font-size:11px;
  text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid var(--border);
}
.audit-table td{padding:10px 14px;border-bottom:1px solid rgba(42,49,72,0.5);color:var(--text-secondary)}
.audit-table tr:hover td{background:var(--bg-card-hover)}

/* ── Buttons ────────────────── */
.btn{
  padding:8px 18px;border-radius:var(--radius-sm);font-size:13px;font-weight:500;
  cursor:pointer;border:1px solid var(--border);
  transition:all .2s;display:inline-flex;align-items:center;gap:6px;
}
.btn-primary{background:var(--accent);color:#0a0e17;border-color:var(--accent)}
.btn-primary:hover{background:#4da3dd;box-shadow:0 0 20px rgba(99,179,237,0.3)}
.btn-ghost{background:transparent;color:var(--text-secondary)}
.btn-ghost:hover{background:var(--bg-card-hover);color:var(--text-primary)}
.btn-danger{background:rgba(252,129,129,0.1);color:var(--danger);border-color:rgba(252,129,129,0.3)}

/* ── Animations ─────────────── */
.loading{display:inline-block;width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.fade-up{animation:fadeIn .4s ease}

/* ── Memory bars ────────────── */
.mem-row{display:flex;align-items:center;gap:12px;padding:8px 0}
.mem-label{width:120px;font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px}
.mem-val{font-weight:600;font-size:14px;min-width:60px;text-align:right}

/* ── Empty state ────────────── */
.empty{text-align:center;padding:40px 20px;color:var(--text-muted);font-size:14px}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="header-left">
    <div>
      <div class="logo">JAMES</div>
      <div class="logo-sub">Autonomous System Orchestrator</div>
    </div>
  </div>
  <div class="status-pill" id="statusPill">Initializing...</div>
</div>

<!-- Navigation -->
<div class="nav">
  <button class="nav-tab active" data-panel="dashboard">Dashboard</button>
  <button class="nav-tab" data-panel="ai">AI Chat</button>
  <button class="nav-tab" data-panel="terminal">Terminal</button>
  <button class="nav-tab" data-panel="layers">Layers</button>
  <button class="nav-tab" data-panel="skills">Skills</button>
  <button class="nav-tab" data-panel="audit">Audit Log</button>
  <button class="nav-tab" data-panel="memory">Memory</button>
</div>

<div class="main">

<!-- ═══ DASHBOARD PANEL ═══ -->
<div class="panel active" id="panel-dashboard">
  <div class="grid-4" id="statsGrid" style="grid-template-columns:repeat(5,1fr)">
    <div class="card stat"><div class="stat-value" id="sLayers">-</div><div class="stat-label">Layers Online</div></div>
    <div class="card stat"><div class="stat-value" id="sSkills">-</div><div class="stat-label">Skills Loaded</div></div>
    <div class="card stat"><div class="stat-value" id="sTools">-</div><div class="stat-label">Tools Ready</div></div>
    <div class="card stat"><div class="stat-value" id="sAudit">-</div><div class="stat-label">Audit Events</div></div>
    <div class="card stat"><div class="stat-value" id="sAI">-</div><div class="stat-label">AI Engine</div><div id="aiModelLabel" style="font-size:11px;color:var(--text-muted);margin-top:4px"></div></div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">Quick Execute</div>
      <div style="display:flex;gap:8px">
        <input type="text" id="quickCmd" placeholder="Type a command... (prefix with ! for shell)"
          style="flex:1;padding:10px 14px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text-primary);font-size:13px;outline:none;font-family:'JetBrains Mono',monospace">
        <button class="btn btn-primary" onclick="quickRun()">Execute</button>
      </div>
      <div id="quickResult" style="margin-top:12px;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-secondary);max-height:200px;overflow-y:auto;white-space:pre-wrap"></div>
    </div>

    <div class="card">
      <div class="card-title">System Actions</div>
      <div style="display:flex;flex-wrap:wrap;gap:8px">
        <button class="btn btn-ghost" onclick="runAction('bootstrap')">Bootstrap</button>
        <button class="btn btn-ghost" onclick="runAction('optimize')">Optimize</button>
        <button class="btn btn-ghost" onclick="runAction('diagnose')">Diagnose</button>
        <button class="btn btn-ghost" onclick="refreshAll()">Refresh All</button>
      </div>
      <div id="actionResult" style="margin-top:12px;font-size:12px;color:var(--text-muted)"></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Recent Activity</div>
    <div id="recentActivity"><div class="empty">Loading...</div></div>
  </div>
</div>

<!-- AI CHAT PANEL -->
<div class="panel" id="panel-ai">
  <!-- Model Controls -->
  <div class="card" style="margin-bottom:12px;padding:16px 24px">
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
      <div style="flex:1;min-width:200px">
        <div class="card-title" style="margin-bottom:6px">AI Engine</div>
        <div style="display:flex;gap:8px;align-items:center">
          <select id="aiModelSelect" style="flex:1;padding:8px 10px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text-primary);font-size:12px;outline:none">
            <option value="">Loading models...</option>
          </select>
          <button class="btn btn-primary" style="font-size:12px;padding:6px 14px" onclick="startAI()">Start</button>
          <button class="btn btn-danger" style="font-size:12px;padding:6px 14px" onclick="stopAI()">Stop</button>
        </div>
      </div>
      <div style="text-align:right;min-width:180px">
        <div style="font-size:11px;color:var(--text-muted)" id="aiModelLabel">No model loaded</div>
        <div id="aiStatus" class="badge off" style="margin-top:4px">Offline</div>
      </div>
    </div>
  </div>

  <!-- Chat Window -->
  <div class="card" style="padding:0;overflow:hidden;display:flex;flex-direction:column;min-height:500px">
    <div style="padding:8px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between">
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:12px;color:var(--text-muted);font-weight:500;letter-spacing:0.5px">CONVERSATION</span>
        <span id="aiMsgCount" style="font-size:10px;color:var(--text-muted);background:var(--bg-primary);padding:1px 7px;border-radius:10px;border:1px solid var(--border)">0 messages</span>
      </div>
      <div style="display:flex;gap:6px">
        <button class="btn btn-ghost" onclick="aiExportChat()" style="font-size:11px;padding:4px 10px;border-radius:6px">&#128196; Export</button>
        <button class="btn btn-ghost" onclick="aiClearChat()" style="font-size:11px;padding:4px 10px;border-radius:6px">&#128465; Clear</button>
      </div>
    </div>
    <div class="ai-status-bar" id="aiInfoBar">
      <span class="dot off" id="aiInfoDot"></span>
      <span id="aiInfoModel">No model</span>
      <span style="color:var(--border)">|</span>
      <span id="aiInfoMemory">&#128200; 0 memories</span>
      <span style="color:var(--border)">|</span>
      <span id="aiInfoTools">&#9881; 0 tools</span>
      <span style="flex:1"></span>
      <span id="aiInfoSession" style="font-style:italic">Session: new</span>
    </div>
    <div id="aiChatMessages" style="flex:1;overflow-y:auto;padding:16px 24px;display:flex;flex-direction:column;gap:12px">
      <div class="ai-msg" style="align-self:flex-start;background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px 12px 12px 4px;padding:12px 16px;max-width:80%;font-size:13px;color:var(--text-secondary)">
        I'm JAMES, your autonomous system orchestrator powered by a local LLM. Select a model above and click Start, then ask me anything or describe a task you want done.
      </div>
      <!-- Quick-action suggestions -->
      <div id="aiSuggestions" style="display:flex;flex-wrap:wrap;gap:8px;padding:4px 0">
        <button class="ai-chip" onclick="aiSuggest(this)" data-msg="What time is it?">&#128336; What time is it?</button>
        <button class="ai-chip" onclick="aiSuggest(this)" data-msg="Show me system info">&#128187; System info</button>
        <button class="ai-chip" onclick="aiSuggest(this)" data-msg="What is my favorite color?">&#127912; My favorite color?</button>
        <button class="ai-chip" onclick="aiSuggest(this)" data-msg="List running processes">&#9881; List processes</button>
        <button class="ai-chip" onclick="aiSuggest(this)" data-msg="Save a note: JAMES is awesome">&#128190; Save a memory</button>
      </div>
    </div>
    <div style="padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:8px;align-items:center">
      <input type="text" id="aiInput" placeholder="Ask JAMES anything... (Enter to send, Ctrl+L to clear)" style="flex:1;padding:10px 14px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text-primary);font-size:13px;outline:none;transition:border-color 0.2s" onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'">
      <button class="btn btn-primary" id="aiSendBtn" onclick="aiSend()" style="min-width:60px">Send</button>
    </div>
  </div>
</div>

<!-- ═══ TERMINAL PANEL ═══ -->
<div class="panel" id="panel-terminal">
  <div class="terminal">
    <div class="terminal-header">
      <div class="terminal-dot red"></div>
      <div class="terminal-dot yellow"></div>
      <div class="terminal-dot green"></div>
      <span class="terminal-title">JAMES Terminal - Layer 1 (Native System)</span>
    </div>
    <div class="terminal-body" id="termOutput">
      <div class="terminal-line system">JAMES v1.0.0 - Justified Autonomous Machine for Execution & Systems</div>
      <div class="terminal-line system">Type a command to execute through the orchestrator. Prefix with ! for direct shell.</div>
      <div class="terminal-line system">Type 'help' for available commands.</div>
      <div class="terminal-line">&nbsp;</div>
    </div>
    <div class="terminal-input-row">
      <span class="terminal-prompt">JAMES &gt;</span>
      <input type="text" id="cmdInput" placeholder="Enter command..." autocomplete="off" spellcheck="false">
    </div>
  </div>
</div>

<!-- ═══ LAYERS PANEL ═══ -->
<div class="panel" id="panel-layers">
  <div class="card" style="padding:0;overflow:hidden">
    <div style="padding:20px 24px;border-bottom:1px solid var(--border)">
      <div class="card-title" style="margin-bottom:0">5-Layer Authority Stack</div>
    </div>
    <div id="layersList"><div class="empty">Loading...</div></div>
  </div>
</div>

<!-- ═══ SKILLS PANEL ═══ -->
<div class="panel" id="panel-skills">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
    <div style="font-size:18px;font-weight:600">Skill Registry</div>
    <button class="btn btn-ghost" onclick="loadSkills()">Refresh</button>
  </div>
  <div class="grid-3" id="skillsGrid"><div class="empty">Loading...</div></div>
</div>

<!-- ═══ AUDIT PANEL ═══ -->
<div class="panel" id="panel-audit">
  <div class="card" style="padding:0;overflow:hidden">
    <div style="padding:16px 24px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
      <div class="card-title" style="margin-bottom:0">Security Audit Log</div>
      <button class="btn btn-ghost" onclick="loadAudit()">Refresh</button>
    </div>
    <div style="overflow-x:auto">
      <table class="audit-table">
        <thead><tr><th>Time</th><th>Operation</th><th>Class</th><th>Approved</th><th>Details</th></tr></thead>
        <tbody id="auditBody"><tr><td colspan="5" class="empty">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ═══ MEMORY PANEL ═══ -->
<div class="panel" id="panel-memory">
  <div class="grid-2">
    <div class="card">
      <div class="card-title">Memory Statistics</div>
      <div id="memStats"><div class="empty">Loading...</div></div>
    </div>
    <div class="card">
      <div class="card-title">Diagnostics</div>
      <div id="diagResults"><div class="empty">Loading...</div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Recent Metrics</div>
    <div id="metricsTable"><div class="empty">Loading...</div></div>
  </div>
</div>

</div><!-- /main -->

<script>
// ══════════════════════════════════════════════════════════
// NAVIGATION
// ══════════════════════════════════════════════════════════
document.querySelectorAll('.nav-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    const panel = document.getElementById('panel-' + tab.dataset.panel);
    if (panel) panel.classList.add('active');
  });
});

// ══════════════════════════════════════════════════════════
// API HELPERS
// ══════════════════════════════════════════════════════════
async function api(path, opts = {}) {
  try {
    const res = await fetch('/api/' + path, opts);
    return await res.json();
  } catch (e) {
    console.error('API error:', e);
    return { error: e.message };
  }
}

async function apiPost(path, body) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// ══════════════════════════════════════════════════════════
// DASHBOARD
// ══════════════════════════════════════════════════════════
async function loadDashboard() {
  const status = await api('status');
  if (status.error) return;

  document.getElementById('sLayers').textContent = status.layers?.available + '/' + status.layers?.registered;
  document.getElementById('sSkills').textContent = status.skills ?? 0;
  document.getElementById('sTools').textContent = status.tools ?? 0;
  document.getElementById('sAudit').textContent = status.audit_entries ?? 0;

  // AI status
  const aiEl = document.getElementById('sAI');
  const aiStatusBadge = document.getElementById('aiStatus');
  const aiModelLabel = document.getElementById('aiModelLabel');
  if (status.ai?.available) {
    const backend = status.ai.backend || 'AI';
    const model = status.ai.model || status.ai.active_model || '';
    aiEl.textContent = backend.toUpperCase();
    aiEl.style.cssText = '-webkit-background-clip:text;-webkit-text-fill-color:transparent;background:var(--gradient-primary);font-size:24px';
    if (aiStatusBadge) { aiStatusBadge.textContent = 'Online'; aiStatusBadge.className = 'badge ok'; }
    if (aiModelLabel) { aiModelLabel.textContent = model ? `Model: ${model}` : `Backend: ${backend}`; }
  } else {
    aiEl.textContent = 'OFF';
    aiEl.style.cssText = 'color:var(--text-muted)';
    if (aiStatusBadge) { aiStatusBadge.textContent = 'Offline'; aiStatusBadge.className = 'badge off'; }
    if (aiModelLabel) { aiModelLabel.textContent = 'No model loaded'; }
  }

  const pill = document.getElementById('statusPill');
  pill.textContent = 'Online — v' + (status.version || '1.0.0');

  // Recent audit
  const audit = await api('audit?count=5');
  const container = document.getElementById('recentActivity');
  if (Array.isArray(audit) && audit.length > 0) {
    container.innerHTML = audit.map(e => {
      const ts = new Date(e.ts * 1000).toLocaleTimeString();
      const cls = e.class === 'safe' ? 'success' : e.class === 'destructive' ? 'danger' : 'accent';
      return `<div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px">
        <span style="color:var(--text-muted);min-width:70px">${ts}</span>
        <span style="padding:2px 8px;border-radius:6px;font-size:11px;background:rgba(99,179,237,0.08);color:var(--${cls})">${e.class}</span>
        <span style="color:var(--text-secondary)">${e.op}</span>
        <span style="color:var(--text-muted);flex:1;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${(e.details||'').substring(0,60)}</span>
      </div>`;
    }).join('');
  } else {
    container.innerHTML = '<div class="empty">No activity yet. Run a command to get started.</div>';
  }
}

async function quickRun() {
  const input = document.getElementById('quickCmd');
  const result = document.getElementById('quickResult');
  const cmd = input.value.trim();
  if (!cmd) return;

  result.textContent = 'Executing...';
  result.style.color = 'var(--accent)';

  const data = await apiPost('run', { task: cmd });
  if (data.error) {
    result.textContent = 'Error: ' + data.error;
    result.style.color = 'var(--danger)';
  } else {
    let output = '';
    for (const node of (data.nodes || [])) {
      const icon = node.state === 'success' ? '[OK]' : '[FAIL]';
      output += `${icon} ${node.name}\n`;
      if (node.result?.output) {
        const o = node.result.output;
        if (typeof o === 'object' && o.stdout) output += o.stdout + '\n';
        else if (typeof o === 'string') output += o + '\n';
      }
      if (node.result?.error) output += `ERROR: ${node.result.error}\n`;
    }
    output += `\n-- ${data.duration_ms?.toFixed(0)}ms, ${data.completed}/${data.total} nodes --`;
    result.textContent = output;
    result.style.color = data.has_failures ? 'var(--danger)' : 'var(--success)';
  }
  loadDashboard();
}

document.getElementById('quickCmd')?.addEventListener('keydown', e => { if (e.key === 'Enter') quickRun(); });

async function runAction(action) {
  const el = document.getElementById('actionResult');
  el.innerHTML = '<span class="loading"></span> Running ' + action + '...';

  const data = await apiPost(action, {});
  if (data.error) {
    el.innerHTML = '<span style="color:var(--danger)">Error: ' + data.error + '</span>';
  } else {
    const summary = JSON.stringify(data, null, 0).substring(0, 200);
    el.innerHTML = '<span style="color:var(--success)">Done!</span> ' + summary;
  }
  loadDashboard();
}

// ══════════════════════════════════════════════════════════
// TERMINAL
// ══════════════════════════════════════════════════════════
const termHistory = [];
let histIdx = -1;

document.getElementById('cmdInput')?.addEventListener('keydown', async (e) => {
  if (e.key === 'Enter') {
    const input = e.target;
    const cmd = input.value.trim();
    if (!cmd) return;

    termHistory.unshift(cmd);
    histIdx = -1;
    input.value = '';

    appendTerm('JAMES > ' + cmd, 'info');

    if (cmd === 'help') {
      appendTerm('Available commands:', 'system');
      appendTerm('  !<cmd>        Execute shell command', 'output');
      appendTerm('  <ps cmd>      Execute PowerShell command', 'output');
      appendTerm('  status        Show system status', 'output');
      appendTerm('  layers        Show layer status', 'output');
      appendTerm('  skills        List skills', 'output');
      appendTerm('  clear         Clear terminal', 'output');
      return;
    }

    if (cmd === 'clear') {
      document.getElementById('termOutput').innerHTML = '';
      return;
    }

    if (cmd === 'status') {
      const s = await api('status');
      appendTerm(JSON.stringify(s, null, 2), 'output');
      return;
    }
    if (cmd === 'layers') {
      const l = await api('layers');
      for (const layer of l) {
        const icon = layer.available ? '[OK]' : '[--]';
        appendTerm(`${icon} Layer ${layer.level}: ${layer.name} - ${layer.description}`, layer.available ? 'success' : 'output');
      }
      return;
    }
    if (cmd === 'skills') {
      const s = await api('skills');
      for (const sk of s) {
        appendTerm(`[${sk.confidence.toFixed(2)}] ${sk.id} (${sk.executions} runs, ${(sk.success_rate*100).toFixed(0)}%)`, 'output');
      }
      return;
    }

    appendTerm('Executing...', 'system');
    const data = await apiPost('run', { task: cmd });

    if (data.error) {
      appendTerm('ERROR: ' + data.error, 'error');
    } else {
      for (const node of (data.nodes || [])) {
        const icon = node.state === 'success' ? '[OK]' : '[FAIL]';
        const cls = node.state === 'success' ? 'success' : 'error';
        appendTerm(`${icon} ${node.name}`, cls);
        if (node.result?.output) {
          const o = node.result.output;
          if (typeof o === 'object' && o.stdout) appendTerm(o.stdout, 'output');
          else if (typeof o === 'string') appendTerm(o, 'output');
        }
        if (node.result?.error) appendTerm('ERROR: ' + node.result.error, 'error');
      }
      appendTerm(`-- ${data.duration_ms?.toFixed(0)}ms --`, 'system');
    }
    appendTerm('', 'output');
  }

  if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (histIdx < termHistory.length - 1) { histIdx++; e.target.value = termHistory[histIdx]; }
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (histIdx > 0) { histIdx--; e.target.value = termHistory[histIdx]; }
    else { histIdx = -1; e.target.value = ''; }
  }
});

function appendTerm(text, cls = 'output') {
  const out = document.getElementById('termOutput');
  const div = document.createElement('div');
  div.className = 'terminal-line ' + cls;
  div.textContent = text;
  out.appendChild(div);
  out.scrollTop = out.scrollHeight;
}

// ══════════════════════════════════════════════════════════
// LAYERS
// ══════════════════════════════════════════════════════════
async function loadLayers() {
  const layers = await api('layers');
  const container = document.getElementById('layersList');
  if (!Array.isArray(layers)) { container.innerHTML = '<div class="empty">Failed to load</div>'; return; }

  container.innerHTML = layers.map(l => `
    <div class="layer-item">
      <div class="layer-num ${l.available ? 'ok' : 'off'}">L${l.level}</div>
      <div class="layer-info">
        <div class="layer-name">${l.name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</div>
        <div class="layer-desc">${l.description}</div>
      </div>
      <div class="badge ${l.available ? 'ok' : 'off'}">${l.available ? 'ONLINE' : 'OFFLINE'}</div>
    </div>
  `).join('');
}

// ══════════════════════════════════════════════════════════
// SKILLS
// ══════════════════════════════════════════════════════════
async function loadSkills() {
  const skills = await api('skills');
  const container = document.getElementById('skillsGrid');
  if (!Array.isArray(skills) || skills.length === 0) {
    container.innerHTML = '<div class="empty" style="grid-column:1/-1">No skills yet. Run "bootstrap" to seed core skills.</div>';
    return;
  }

  container.innerHTML = skills.map(s => `
    <div class="card skill-card">
      <div class="skill-header">
        <div class="skill-id">${s.id}</div>
        <div class="skill-conf" style="color:${s.confidence > 0.7 ? 'var(--success)' : s.confidence > 0.4 ? 'var(--warning)' : 'var(--danger)'}">${(s.confidence * 100).toFixed(0)}%</div>
      </div>
      <div class="skill-desc">${s.description || s.name}</div>
      <div class="skill-tags">${(s.tags || []).map(t => `<span class="skill-tag">${t}</span>`).join('')}</div>
      <div class="skill-bar"><div class="skill-bar-fill" style="width:${s.confidence * 100}%"></div></div>
      <div style="display:flex;justify-content:space-between;margin-top:8px;font-size:11px;color:var(--text-muted)">
        <span>${s.executions} runs</span>
        <span>${(s.success_rate * 100).toFixed(0)}% success</span>
        <span>${s.methods?.join(', ')}</span>
      </div>
    </div>
  `).join('');
}

// ══════════════════════════════════════════════════════════
// AUDIT
// ══════════════════════════════════════════════════════════
async function loadAudit() {
  const entries = await api('audit?count=50');
  const tbody = document.getElementById('auditBody');
  if (!Array.isArray(entries) || entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">No audit entries</td></tr>';
    return;
  }

  tbody.innerHTML = entries.reverse().map(e => {
    const ts = new Date(e.ts * 1000).toLocaleTimeString();
    const clsColor = e.class === 'safe' ? 'var(--success)' : e.class === 'destructive' ? 'var(--danger)' : 'var(--warning)';
    return `<tr>
      <td style="white-space:nowrap">${ts}</td>
      <td>${e.op}</td>
      <td><span style="color:${clsColor}">${e.class}</span></td>
      <td>${e.approved ? 'Yes' : 'No'}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.details || '-'}</td>
    </tr>`;
  }).join('');
}

// ══════════════════════════════════════════════════════════
// MEMORY
// ══════════════════════════════════════════════════════════
async function loadMemory() {
  const stats = await api('memory');
  const container = document.getElementById('memStats');
  if (stats.error) { container.innerHTML = '<div class="empty">Failed to load</div>'; return; }

  container.innerHTML = `
    <div class="mem-row"><span class="mem-label">Short-term</span><span class="mem-val">${stats.short_term_entries}</span></div>
    <div class="mem-row"><span class="mem-label">Long-term</span><span class="mem-val">${stats.long_term_entries}</span></div>
    <div class="mem-row"><span class="mem-label">Metrics</span><span class="mem-val">${stats.metrics_recorded}</span></div>
    <div class="mem-row"><span class="mem-label">Optimizations</span><span class="mem-val">${stats.optimizations_logged}</span></div>
    <div class="mem-row"><span class="mem-label">System Map</span><span class="mem-val">${stats.system_map_entries}</span></div>
    <div class="mem-row"><span class="mem-label">DB Path</span><span style="font-size:11px;color:var(--text-muted)">${stats.db_path}</span></div>
  `;

  // Diagnostics
  const diag = await api('diagnose');
  const diagEl = document.getElementById('diagResults');
  if (diag.total_issues === 0) {
    diagEl.innerHTML = '<div style="color:var(--success);font-weight:500;padding:20px 0;text-align:center">All Systems Nominal</div>';
  } else {
    let html = `<div style="margin-bottom:8px;font-weight:600">${diag.total_issues} issues found</div>`;
    for (const b of (diag.bottlenecks || [])) html += `<div style="color:var(--warning);font-size:12px;padding:4px 0">[!] Bottleneck: ${b.skill_name} (${b.avg_duration_ms}ms)</div>`;
    for (const u of (diag.instability || [])) html += `<div style="color:var(--danger);font-size:12px;padding:4px 0">[!] Unstable: ${u.skill_name} (${(u.success_rate*100).toFixed(0)}%)</div>`;
    diagEl.innerHTML = html;
  }

  // Recent metrics
  const metrics = await api('metrics?limit=10');
  const mEl = document.getElementById('metricsTable');
  if (!Array.isArray(metrics) || metrics.length === 0) {
    mEl.innerHTML = '<div class="empty">No metrics recorded yet</div>';
    return;
  }

  mEl.innerHTML = `<table class="audit-table">
    <thead><tr><th>Node</th><th>Layer</th><th>Status</th><th>Duration</th><th>Error</th></tr></thead>
    <tbody>${metrics.map(m => `<tr>
      <td>${m.node_name || m.node_id}</td>
      <td>L${m.layer || '?'}</td>
      <td style="color:${m.success ? 'var(--success)' : 'var(--danger)'}">${m.success ? 'OK' : 'FAIL'}</td>
      <td>${m.duration_ms?.toFixed(0)}ms</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-muted)">${m.error || '-'}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

// ══════════════════════════════════════════════════════════
// AI MODEL MANAGEMENT
// ══════════════════════════════════════════════════════════
async function loadModels() {
  const models = await api('ai/models');
  const sel = document.getElementById('aiModelSelect');
  if (!sel || !Array.isArray(models)) return;

  sel.innerHTML = '';
  if (models.length === 0) {
    sel.innerHTML = '<option value="">No models found</option>';
    return;
  }

  // Add "auto" option
  sel.innerHTML = '<option value="">Auto (best available)</option>';
  for (const m of models) {
    const opt = document.createElement('option');
    opt.value = m.path;
    opt.textContent = `${m.name} (${m.size_mb} MB)`;
    sel.appendChild(opt);
  }
}

async function startAI() {
  const sel = document.getElementById('aiModelSelect');
  const modelPath = sel?.value || null;

  const label = document.getElementById('aiModelLabel');
  const badge = document.getElementById('aiStatus');
  if (label) label.textContent = 'Starting model...';
  if (badge) { badge.textContent = 'Loading'; badge.className = 'badge off'; }

  aiAddMsg('<span class="loading"></span> <span style="color:var(--purple);margin-left:8px">Starting local LLM server... (this may take up to 60 seconds for large models)</span>');

  const body = modelPath ? { model_path: modelPath } : {};
  const data = await apiPost('ai/start', body);

  if (data.error) {
    aiAddMsg(`<span style="color:var(--danger)">Failed to start: ${data.error}</span>`);
    if (label) label.textContent = 'Failed to start';
  } else {
    const model = data.active_model || data.model || 'local';
    aiAddMsg(`<span style="color:var(--success)">LLM server started! Model: <strong>${model}</strong></span>`);
    if (label) label.textContent = `Model: ${model}`;
    if (badge) { badge.textContent = 'Online'; badge.className = 'badge ok'; }
  }
  loadDashboard();
}

async function stopAI() {
  const data = await apiPost('ai/stop', {});
  const label = document.getElementById('aiModelLabel');
  const badge = document.getElementById('aiStatus');
  if (data.status === 'stopped') {
    aiAddMsg('<span style="color:var(--text-muted)">LLM server stopped.</span>');
    if (label) label.textContent = 'No model loaded';
    if (badge) { badge.textContent = 'Offline'; badge.className = 'badge off'; }
  } else {
    aiAddMsg(`<span style="color:var(--danger)">Error: ${data.error || 'unknown'}</span>`);
  }
  loadDashboard();
}

// ══════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════
async function refreshAll() {
  await Promise.all([loadDashboard(), loadLayers(), loadSkills(), loadAudit(), loadMemory(), loadModels()]);
}

refreshAll();
// Auto-refresh every 15 seconds
setInterval(loadDashboard, 15000);

// ══════════════════════════════════════════════════════════
// AI CHAT (Enhanced)
// ══════════════════════════════════════════════════════════
let pendingPlan = null;
let pendingIntent = null;
let aiMsgCounter = 0;
const aiSessionStart = new Date();

// Keyboard shortcuts
document.getElementById('aiInput')?.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) aiSend();
  if (e.key === 'l' && e.ctrlKey) { e.preventDefault(); aiClearChat(); }
  if (e.key === 'Escape') e.target.blur();
});

// Markdown renderer (uses marked.js CDN)
function renderMd(text) {
  try {
    if (typeof marked !== 'undefined') {
      marked.setOptions({ breaks: true, gfm: true });
      return '<div class="ai-md">' + marked.parse(text) + '</div>';
    }
  } catch(e) {}
  return text.replace(/\n/g, '<br>').replace(/`([^`]+)`/g, '<code style="background:rgba(99,179,237,0.1);padding:2px 6px;border-radius:4px;font-size:12px">$1</code>');
}

function updateMsgCount() {
  aiMsgCounter++;
  const el = document.getElementById('aiMsgCount');
  if (el) el.textContent = aiMsgCounter + ' message' + (aiMsgCounter !== 1 ? 's' : '');
}

function aiAddMsg(html, sender = 'ai', opts = {}) {
  const container = document.getElementById('aiChatMessages');
  const div = document.createElement('div');
  const isUser = sender === 'user';
  const now = new Date();
  const ts = now.toLocaleTimeString('en-US', { hour12: true, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  div.className = 'ai-msg ai-bubble';
  div.style.cssText = `align-self:${isUser ? 'flex-end' : 'flex-start'};background:${isUser ? 'rgba(99,179,237,0.12)' : 'var(--bg-secondary)'};border:1px solid ${isUser ? 'rgba(99,179,237,0.2)' : 'var(--border)'};border-radius:12px 12px ${isUser ? '4px 12px' : '12px 4px'};padding:12px 16px;max-width:85%;font-size:13px;color:${isUser ? 'var(--text-primary)' : 'var(--text-secondary)'};line-height:1.6;word-break:break-word;position:relative;`;

  // Build footer with timestamp + actions
  let footer = `<div style="margin-top:4px;display:flex;align-items:center;justify-content:space-between">`;
  footer += `<span style="font-size:10px;color:var(--text-muted);opacity:0.6">${ts}</span>`;
  if (!isUser && !opts.isLoader) {
    footer += `<div class="msg-actions">`;
    footer += `<button class="msg-action-btn" onclick="aiCopyMsg(this)" title="Copy to clipboard">&#128203; Copy</button>`;
    if (opts.showSave) footer += `<button class="msg-action-btn" onclick="aiSaveToMemory(this)" title="Save to memory">&#128190; Save</button>`;
    footer += `</div>`;
  }
  footer += `</div>`;

  div.innerHTML = html + footer;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  if (!opts.isLoader) updateMsgCount();
  return div;
}

function aiAddLoading() {
  return aiAddMsg('<span class="loading"></span> <span style="color:var(--purple);margin-left:8px">Thinking<span class="dots"></span></span>', 'ai', { isLoader: true });
}

function aiCopyMsg(btn) {
  const bubble = btn.closest('.ai-bubble');
  if (!bubble) return;
  const text = bubble.innerText.replace(/Copy|Save|📋|💾/g, '').trim();
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = '✓ Copied';
    btn.style.color = 'var(--success)';
    setTimeout(() => { btn.innerHTML = '&#128203; Copy'; btn.style.color = ''; }, 1500);
  });
}

function aiSaveToMemory(btn) {
  const bubble = btn.closest('.ai-bubble');
  if (!bubble) return;
  const text = bubble.innerText.replace(/Copy|Save|📋|💾/g, '').trim();
  const key = 'chat_note_' + Date.now();
  apiPost('tools/call', { name: 'memory_save', kwargs: { key, value: text.substring(0, 500) } }).then(() => {
    btn.textContent = '✓ Saved';
    btn.style.color = 'var(--success)';
    setTimeout(() => { btn.innerHTML = '&#128190; Save'; btn.style.color = ''; }, 1500);
    refreshAiInfoBar();
  });
}

function aiSuggest(btn) {
  const msg = btn.dataset.msg;
  if (!msg) return;
  document.getElementById('aiInput').value = msg;
  const suggestions = document.getElementById('aiSuggestions');
  if (suggestions) suggestions.style.display = 'none';
  aiSend();
}

async function aiExportChat() {
  const container = document.getElementById('aiChatMessages');
  const msgs = container.querySelectorAll('.ai-bubble');
  let text = '=== JAMES Chat Export ===\n' + new Date().toLocaleString() + '\n\n';
  msgs.forEach(m => {
    const isUser = m.style.alignSelf === 'flex-end';
    text += (isUser ? 'YOU: ' : 'JAMES: ') + m.innerText.replace(/Copy|Save|📋|💾/g, '').trim() + '\n\n';
  });
  try {
    await navigator.clipboard.writeText(text);
    aiAddMsg('<span style="color:var(--success)">&#10003; Chat exported to clipboard!</span>', 'ai', { isLoader: false });
  } catch(e) {
    // Fallback: download as file
    const blob = new Blob([text], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'james_chat_' + Date.now() + '.txt';
    a.click();
  }
}

async function aiClearChat() {
  const container = document.getElementById('aiChatMessages');
  container.innerHTML = `<div class="ai-msg" style="align-self:flex-start;background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px 12px 12px 4px;padding:12px 16px;max-width:80%;font-size:13px;color:var(--text-secondary)">
    Chat cleared. Ask me anything to get started.
  </div>
  <div id="aiSuggestions" style="display:flex;flex-wrap:wrap;gap:8px;padding:4px 0">
    <button class="ai-chip" onclick="aiSuggest(this)" data-msg="What time is it?">&#128336; What time is it?</button>
    <button class="ai-chip" onclick="aiSuggest(this)" data-msg="Show me system info">&#128187; System info</button>
    <button class="ai-chip" onclick="aiSuggest(this)" data-msg="What is my favorite color?">&#127912; My favorite color?</button>
    <button class="ai-chip" onclick="aiSuggest(this)" data-msg="List running processes">&#9881; List processes</button>
    <button class="ai-chip" onclick="aiSuggest(this)" data-msg="Save a note: JAMES is awesome">&#128190; Save a memory</button>
  </div>`;
  pendingPlan = null;
  pendingIntent = null;
  aiMsgCounter = 0;
  const el = document.getElementById('aiMsgCount');
  if (el) el.textContent = '0 messages';
  await apiPost('ai/chat/clear', {});
}

// Status info bar refresh
async function refreshAiInfoBar() {
  try {
    const [status, memData, toolData] = await Promise.all([
      api('ai/status'),
      api('memory'),
      api('tools'),
    ]);
    const dot = document.getElementById('aiInfoDot');
    const model = document.getElementById('aiInfoModel');
    const mem = document.getElementById('aiInfoMemory');
    const tools = document.getElementById('aiInfoTools');
    const session = document.getElementById('aiInfoSession');

    if (status && !status.error && status.available) {
      if (dot) { dot.className = 'dot on'; }
      if (model) model.textContent = '🤖 ' + (status.active_model || status.backend || 'Online');
    } else {
      if (dot) { dot.className = 'dot off'; }
      if (model) model.textContent = 'Offline';
    }
    if (mem && memData) {
      const count = memData.long_term?.entries || memData.entries || 0;
      mem.innerHTML = `&#128200; ${count} memories`;
    }
    if (tools && Array.isArray(toolData)) {
      tools.innerHTML = `&#9881; ${toolData.length} tools`;
    }
    if (session) {
      const mins = Math.floor((Date.now() - aiSessionStart.getTime()) / 60000);
      session.textContent = mins < 1 ? 'Session: <1m' : `Session: ${mins}m`;
    }
  } catch(e) {}
}
refreshAiInfoBar();
setInterval(refreshAiInfoBar, 10000);

async function aiSend() {
  const input = document.getElementById('aiInput');
  const msg = input.value.trim();
  if (!msg) return;

  // Disable send during processing
  const sendBtn = document.getElementById('aiSendBtn');
  sendBtn.disabled = true;
  sendBtn.textContent = '...';

  const suggestions = document.getElementById('aiSuggestions');
  if (suggestions) suggestions.style.display = 'none';

  input.value = '';
  aiAddMsg(msg.replace(/</g, '&lt;'), 'user');
  const loader = aiAddLoading();

  try {
    const data = await apiPost('ai/chat', { message: msg });
    loader.remove();

    if (data.error) {
      aiAddMsg(`<span style="color:var(--danger)">&#9888; ${data.error}</span>`);
      return;
    }

    if (data.type === 'chat') {
      const rendered = renderMd(data.message);
      aiAddMsg(rendered + `<div style="margin-top:6px;font-size:10px;color:var(--text-muted)">${data.duration_ms?.toFixed(0)}ms · ${data.model || 'local'}</div>`, 'ai', { showSave: true });
    }
    else if (data.type === 'plan') {
      pendingPlan = data;
      pendingIntent = data.intent;
      let html = `<div style="font-weight:600;color:var(--accent);margin-bottom:8px">&#9654; Executing: ${data.intent}</div>`;
      if (data.reasoning) html += `<div style="font-size:12px;color:var(--text-muted);margin-bottom:10px">${data.reasoning}</div>`;
      // Progress bar placeholder
      html += `<div class="exec-progress"><div class="exec-progress-fill" style="width:0%" id="execProgress"></div></div>`;
      html += '<div style="border:1px solid var(--border);border-radius:8px;overflow:hidden">';
      for (const [i, step] of data.steps.entries()) {
        html += `<div style="padding:8px 12px;border-bottom:1px solid var(--border);font-size:12px;display:flex;gap:8px;align-items:center">
          <span style="color:var(--purple);font-weight:600;min-width:24px">#${i + 1}</span>
          <span style="color:var(--text-primary)">${step.name || step.description || 'step'}</span>
          <span style="color:var(--text-muted);flex:1;text-align:right;font-family:'JetBrains Mono',monospace;font-size:11px">${step.action?.target?.substring(0, 50) || ''}</span>
        </div>`;
      }
      html += '</div>';
      html += `<div style="margin-top:6px;font-size:10px;color:var(--text-muted)">${data.duration_ms?.toFixed(0)}ms · ${data.steps.length} steps · ${data.model || 'local'}</div>`;
      aiAddMsg(html);

      // Animate progress bar
      const progEl = document.getElementById('execProgress');
      if (progEl) { progEl.style.width = '30%'; }

      setTimeout(aiExecutePlan, 100);
    }
  } catch(e) {
    loader.remove();
    aiAddMsg(`<span style="color:var(--danger)">&#9888; Network error: ${e.message}</span>`);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = 'Send';
    refreshAiInfoBar();
  }
}

async function aiExecutePlan() {
  if (!pendingPlan) { aiAddMsg('No pending plan to execute.'); return; }

  // Update progress
  const progEl = document.getElementById('execProgress');
  if (progEl) progEl.style.width = '60%';

  const loader = aiAddLoading();
  const data = await apiPost('ai/execute', { plan: pendingPlan });
  loader.remove();
  pendingPlan = null;

  if (progEl) progEl.style.width = '100%';

  if (data.error) {
    aiAddMsg(`<span style="color:var(--danger)">&#9888; Execution error: ${data.error}</span>`);
    return;
  }

  // Build collapsible execution results
  const uid = 'exec_' + Date.now();
  let html = `<div style="font-weight:600;margin-bottom:4px;color:${data.has_failures ? 'var(--danger)' : 'var(--success)'}">
    ${data.has_failures ? '&#10007; Completed with failures' : '&#10003; All steps succeeded'} (${data.completed}/${data.total})
  </div>`;
  html += `<div style="font-size:10px;color:var(--text-muted);margin-bottom:4px">${data.duration_ms?.toFixed(0)}ms total</div>`;

  // Summary line for each node (always visible)
  for (const node of (data.nodes || [])) {
    const icon = node.state === 'success' ? '&#10003;' : '&#10007;';
    const c = node.state === 'success' ? 'var(--success)' : 'var(--danger)';
    const dur = node.result?.duration_ms ? ` (${node.result.duration_ms}ms)` : '';
    html += `<div style="font-size:12px;padding:2px 0;color:${c}">${icon} ${node.name}${dur}</div>`;
  }

  // Collapsible raw details
  let hasDetails = (data.nodes || []).some(n => n.result?.output || n.result?.error);
  if (hasDetails) {
    html += `<button class="exec-toggle" onclick="this.classList.toggle('open');document.getElementById('${uid}').classList.toggle('open')">
      <span class="arrow">&#9654;</span> Show details
    </button>`;
    html += `<div class="exec-details" id="${uid}">`;
    for (const node of (data.nodes || [])) {
      if (node.result?.output) {
        const o = node.result.output;
        let text = '';
        if (typeof o === 'object' && o.stdout) text = o.stdout;
        else if (typeof o === 'string') text = o;
        else if (typeof o === 'object') text = JSON.stringify(o, null, 2);
        if (text) html += `<div style="margin:4px 0;font-size:11px;color:var(--text-muted)">${node.name}:</div><pre style="margin:0 0 8px 0;padding:6px 10px;background:var(--bg-primary);border-radius:6px;font-size:11px;color:var(--text-muted);max-height:150px;overflow-y:auto;white-space:pre-wrap">${String(text).substring(0, 1000).replace(/</g, '&lt;')}</pre>`;
      }
      if (node.result?.error) html += `<div style="color:var(--danger);font-size:11px;margin:4px 0">${node.name}: ${node.result.error}</div>`;
    }
    html += '</div>';
  }

  aiAddMsg(html, 'ai', { showSave: true });
  loadDashboard();

  // Synthesize
  if (!data.has_failures && pendingIntent) {
    const synthLoader = aiAddLoading();
    const synthData = await apiPost('ai/synthesize', { intent: pendingIntent, nodes: data.nodes });
    synthLoader.remove();
    if (synthData && !synthData.error && synthData.text) {
      const rendered = renderMd(synthData.text);
      aiAddMsg(rendered + `<div style="margin-top:6px;font-size:10px;color:var(--text-muted)">Synthesis: ${synthData.duration_ms?.toFixed(0) || '?'}ms</div>`, 'ai', { showSave: true });
    }
    pendingIntent = null;
  }
  refreshAiInfoBar();
}
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="JAMES Web Dashboard")
    parser.add_argument("--port", type=int, default=7700, help="Port to run on (default: 7700)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    print()
    print("  +-------------------------------------------------------+")
    print("  |   JAMES Web Dashboard                                  |")
    print("  |   Justified Autonomous Machine for Execution & Systems |")
    print("  +-------------------------------------------------------+")
    print()
    print(f"  Dashboard:  http://{args.host}:{args.port}")
    print(f"  API Base:   http://{args.host}:{args.port}/api/")
    print()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
