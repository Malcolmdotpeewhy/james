"""
JAMES CLI -- Command-Line Interface

Usage:
    python -m james status              Show system status
    python -m james run <task>          Execute a task
    python -m james cmd <command>       Run a single command
    python -m james skills              List learned skills
    python -m james memory              Query memory stats
    python -m james optimize            Run improvement cycle
    python -m james audit [count]       View audit log
    python -m james diagnose            Run system diagnostics
    python -m james layers              Show authority layer status
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from typing import Optional

# Force UTF-8 stdout on Windows to prevent charmap errors
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )
    except Exception:
        pass


def _print_header():
    """Print JAMES banner."""
    print()
    print("  +-------------------------------------------------------+")
    print("  |   JAMES -- Justified Autonomous Machine for           |")
    print("  |              Execution & Systems  v1.0.0              |")
    print("  +-------------------------------------------------------+")
    print()


def _print_json(data: dict | list, indent: int = 2):
    """Pretty-print JSON data."""
    print(json.dumps(data, indent=indent, default=str))


def _get_orchestrator():
    """Lazy-init the orchestrator."""
    from james.orchestrator import Orchestrator
    return Orchestrator()


def cmd_status():
    """Show system status."""
    orch = _get_orchestrator()
    status = orch.status()

    print("  System Status")
    print("  " + "-" * 40)
    print(f"  Version:        {status['version']}")
    print(f"  Project Root:   {status['project_root']}")
    print(f"  Layers:         {status['layers']['available']}/{status['layers']['registered']} available")
    print(f"  Skills:         {status['skills']}")
    print(f"  Audit Entries:  {status['audit_entries']}")
    print(f"  Active Graph:   {status['active_graph'] or '(none)'}")
    print()
    print("  Memory")
    print("  " + "-" * 40)
    mem = status['memory']
    print(f"  Short-term:     {mem['short_term_entries']} entries")
    print(f"  Long-term:      {mem['long_term_entries']} entries")
    print(f"  Metrics:        {mem['metrics_recorded']} recorded")
    print(f"  Optimizations:  {mem['optimizations_logged']} logged")
    print(f"  System Map:     {mem['system_map_entries']} entries")
    print()
    print("  Failures")
    print("  " + "-" * 40)
    print(f"  Total:          {status['failures']['total']}")
    print(f"  Unresolved:     {status['failures']['unresolved']}")
    print()


def cmd_run(args: list[str]):
    """Execute a task."""
    if not args:
        print("  Error: No task specified.")
        print("  Usage: python -m james run <task description>")
        return

    task = " ".join(args)
    print(f"  Planning task: {task}")
    print()

    orch = _get_orchestrator()
    start = time.time()
    graph = orch.run(task)
    elapsed = (time.time() - start) * 1000

    done, total = graph.progress
    print()
    print("  Execution Complete")
    print("  " + "-" * 40)
    print(f"  Graph:      {graph.name}")
    print(f"  Nodes:      {done}/{total} completed")
    print(f"  Failures:   {'yes' if graph.has_failures else 'none'}")
    print(f"  Duration:   {elapsed:.0f}ms")
    print()

    for nid, node in graph.nodes.items():
        if node.state == NodeState.SUCCESS:
            status_icon = "[OK]"
        elif node.state == NodeState.FAILED:
            status_icon = "[FAIL]"
        else:
            status_icon = "[SKIP]"
        print(f"  {status_icon} [{nid}] {node.name}")
        if node.result:
            if node.result.output:
                output = node.result.output
                if isinstance(output, dict):
                    stdout = output.get("stdout", "")
                    if stdout:
                        for line in stdout.splitlines()[:10]:
                            print(f"      {line}")
                elif isinstance(output, str):
                    for line in output.splitlines()[:10]:
                        print(f"      {line}")
            if node.result.error:
                print(f"      ERROR: {node.result.error[:200]}")
    print()


def cmd_command(args: list[str]):
    """Run a single command."""
    if not args:
        print("  Error: No command specified.")
        return

    command = " ".join(args)
    orch = _get_orchestrator()
    result = orch.run_command(command)

    if result:
        if isinstance(result, dict):
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            if stdout:
                print(stdout)
            if stderr:
                print(stderr, file=sys.stderr)
        else:
            print(result)


def cmd_skills():
    """List learned skills."""
    orch = _get_orchestrator()
    skills = orch.skills.list_all()

    if not skills:
        print("  No skills learned yet.")
        print("  Skills are created automatically as JAMES executes tasks.")
        return

    print(f"  Skills ({len(skills)})")
    print("  " + "-" * 40)
    for skill in skills:
        print(
            f"  [{skill.confidence_score:.2f}] {skill.id}"
            f"  ({skill.execution_count} runs, {skill.success_rate:.0%} success)"
        )
        if skill.description:
            print(f"         {skill.description[:80]}")
    print()


def cmd_memory():
    """Query memory stats."""
    orch = _get_orchestrator()
    stats = orch.memory.get_stats()

    print("  Memory System Statistics")
    print("  " + "-" * 40)
    _print_json(stats)
    print()

    # Show recent metrics
    metrics = orch.memory.get_metrics(limit=5)
    if metrics:
        print("  Recent Metrics")
        print("  " + "-" * 40)
        for m in metrics:
            success = "[OK]" if m.get("success") else "[FAIL]"
            print(
                f"  {success} {m.get('node_name', m.get('node_id', '?'))}"
                f"  L{m.get('layer', '?')} {m.get('duration_ms', 0):.0f}ms"
            )
        print()


def cmd_optimize():
    """Run improvement cycle."""
    print("  Running improvement cycle...")
    print()

    orch = _get_orchestrator()
    result = orch.improve()

    print("  Improvement Cycle Results")
    print("  " + "-" * 40)
    print(f"  Issues Found:          {result['issues_found']}")
    print(f"  Proposals Generated:   {result['proposals_generated']}")
    print(f"  Optimizations Applied: {result['optimizations_applied']}")
    print(f"  Duration:              {result['duration_ms']:.0f}ms")
    print()


def cmd_audit(args: list[str]):
    """View audit log."""
    count = int(args[0]) if args else 20
    orch = _get_orchestrator()
    entries = orch.audit.read_recent(count)

    if not entries:
        print("  Audit log is empty.")
        return

    print(f"  Audit Log (last {len(entries)} entries)")
    print("  " + "-" * 40)
    for entry in entries:
        ts = time.strftime("%H:%M:%S", time.localtime(entry.get("ts", 0)))
        op = entry.get("op", "?")
        cls = entry.get("class", "?")
        details = entry.get("details", "")[:60]
        approved = "[Y]" if entry.get("approved") else "[N]"
        print(f"  {ts} [{cls:12s}] {approved} {op}: {details}")
    print()


def cmd_diagnose():
    """Run system diagnostics."""
    print("  Running diagnostics...")
    print()

    orch = _get_orchestrator()
    report = orch.optimizer.diagnose()

    print("  Diagnostic Report")
    print("  " + "-" * 40)
    print(f"  Total Issues: {report.total_issues}")
    print()

    if report.bottlenecks:
        print(f"  Bottlenecks ({len(report.bottlenecks)}):")
        for b in report.bottlenecks:
            print(f"    [!] {b['skill_name']} -- avg {b['avg_duration_ms']:.0f}ms [{b['severity']}]")
        print()

    if report.instability:
        print(f"  Instability ({len(report.instability)}):")
        for u in report.instability:
            print(f"    [!] {u['skill_name']} -- {u['success_rate']:.0%} success [{u['severity']}]")
        print()

    if report.inefficiencies:
        print(f"  Inefficiencies ({len(report.inefficiencies)}):")
        for e in report.inefficiencies:
            print(f"    [!] {e['skill_name']} -- p95/avg ratio {e['variance_ratio']:.1f}x")
        print()

    if report.total_issues == 0:
        print("  [OK] All systems nominal.")
        print()


def cmd_layers():
    """Show authority layer status."""
    orch = _get_orchestrator()
    available = orch.layers.get_available()

    print("  Authority Layer Stack")
    print("  " + "-" * 40)
    for level in range(1, 6):
        from james.layers import LayerLevel
        ll = LayerLevel(level)
        layer = orch.layers.get(ll)
        if layer:
            avail = "[OK]" if layer in available else "[--]"
            print(f"  {avail} Layer {level}: {layer.name}")
            print(f"           {layer.description}")
        else:
            print(f"  [--] Layer {level}: not registered")
    print()


def cmd_bootstrap():
    """Run system discovery and seed skills."""
    print("  Running system bootstrap...")
    print()

    orch = _get_orchestrator()
    from james.bootstrap import run_bootstrap
    result = run_bootstrap(orch.memory, orch.skills)

    print("  Bootstrap Results")
    print("  " + "-" * 40)
    print(f"  Tools Found:     {result['tools_found']}")
    print(f"  Tools Missing:   {result['tools_missing']}")
    print(f"  Skills Seeded:   {result['skills_seeded']}")
    print(f"  Total Skills:    {result['total_skills']}")
    print()

    if result.get('found'):
        print("  Discovered Tools")
        print("  " + "-" * 40)
        for name, info in sorted(result['found'].items()):
            print(f"  [{info['category']:16s}] {name:15s} {info['version'][:50]}")
        print()

    if result.get('missing'):
        print(f"  Not Found: {', '.join(result['missing'][:20])}")
        print()


# Need these for cmd_run display
from james.dag import NodeState  # noqa: E402



def cmd_shell():
    """Interactive JAMES shell (REPL)."""
    orch = _get_orchestrator()

    # Show compact status
    status = orch.status()
    ai_info = status.get("ai", {})
    ai_str = f"{ai_info.get('model', 'N/A')}" if ai_info.get("available") else "offline"
    print(f"  Layers: {status['layers']['available']}/{status['layers']['registered']}  "
          f"Skills: {status['skills']}  Tools: {status['tools']}  AI: {ai_str}")
    print()
    print("  Type commands, tasks, or questions. Type 'help' for commands, 'exit' to quit.")
    print()

    # Import classifier for smart routing
    from james.ai.classifier import IntentClassifier
    classifier = IntentClassifier()

    # REPL commands (local dispatch)
    shell_commands = {
        "status": lambda _: cmd_status(),
        "skills": lambda _: cmd_skills(),
        "memory": lambda _: cmd_memory(),
        "optimize": lambda _: cmd_optimize(),
        "diagnose": lambda _: cmd_diagnose(),
        "layers": lambda _: cmd_layers(),
        "bootstrap": lambda _: cmd_bootstrap(),
    }

    def _show_help():
        print("  ┌──────────────────────────────────────────────┐")
        print("  │  JAMES Interactive Shell                     │")
        print("  ├──────────────────────────────────────────────┤")
        print("  │  status      System status overview          │")
        print("  │  !<cmd>      Execute OS command directly     │")
        print("  │  run <task>  Plan and execute a task          │")
        print("  │  skills      List learned skills              │")
        print("  │  memory      Memory system stats              │")
        print("  │  optimize    Run improvement cycle            │")
        print("  │  diagnose    System diagnostics               │")
        print("  │  layers      Authority layer status           │")
        print("  │  bootstrap   System discovery + skill seeding │")
        print("  │  audit [n]   View audit log (last n entries)  │")
        print("  │  clear       Clear conversation history       │")
        print("  │  help        Show this help                   │")
        print("  │  exit/quit   Exit the shell                   │")
        print("  ├──────────────────────────────────────────────┤")
        print("  │  Or type any question/instruction for AI     │")
        print("  └──────────────────────────────────────────────┘")
        print()

    # Conversation history for multi-turn chat
    chat_history: list[dict] = []

    while True:
        try:
            line = input("  JAMES> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print("  Goodbye! JAMES standing by.")
            break

        if not line:
            continue

        lower = line.lower()

        # Exit commands
        if lower in ("exit", "quit", "q"):
            print("  Goodbye! JAMES standing by.")
            break

        # Help
        if lower == "help":
            _show_help()
            continue

        # Clear chat history
        if lower == "clear":
            chat_history.clear()
            print("  Conversation history cleared.")
            print()
            continue

        # Audit (special: takes optional arg)
        if lower.startswith("audit"):
            parts = line.split()
            cmd_audit(parts[1:])
            continue

        # Run (special: takes rest of line)
        if lower.startswith("run "):
            task = line[4:].strip()
            if task:
                cmd_run(task.split())
            else:
                print("  Usage: run <task description>")
                print()
            continue

        # Shell commands (simple dispatch)
        handler = shell_commands.get(lower)
        if handler:
            try:
                handler(None)
            except Exception as e:
                print(f"  [X] Error: {e}")
            continue

        # Direct OS command with ! prefix
        if line.startswith("!") or line.startswith("$"):
            cmd_text = line.lstrip("!$").strip()
            if cmd_text:
                graph = orch.run(f"!{cmd_text}")
                node = list(graph.nodes.values())[0]
                if node.result and node.result.output:
                    output = node.result.output
                    if isinstance(output, dict):
                        stdout = output.get("stdout", "")
                        stderr = output.get("stderr", "")
                        if stdout:
                            print(stdout)
                        if stderr:
                            print(f"  [stderr] {stderr}")
                    elif isinstance(output, str):
                        print(output)
                if node.result and node.result.error:
                    print(f"  [error] {node.result.error[:300]}")
                print()
            continue

        # ── AI routing ────────────────────────────────────
        intent, confidence = classifier.classify(line)

        # Short-circuit for trivial intents
        short_circuit = classifier.get_short_circuit_response(intent, confidence)
        if short_circuit:
            print(f"  {short_circuit}")
            print()
            chat_history.append({"role": "user", "content": line})
            chat_history.append({"role": "assistant", "content": short_circuit})
            continue

        # Try AI decomposition
        try:
            from james import ai as james_ai
            if james_ai.is_available():
                context = orch._build_ai_context(line)
                intent_hint = classifier.get_intent_hint(intent, confidence)
                if intent_hint:
                    context["_intent_hint"] = intent_hint
                    context["_detected_intent"] = intent

                result = james_ai.decompose_task(line, context=context)

                if result.get("type") == "chat":
                    msg = result.get("message", "")
                    print(f"  {msg}")
                    print()
                    chat_history.append({"role": "user", "content": line})
                    chat_history.append({"role": "assistant", "content": msg})
                    continue

                if result.get("steps"):
                    plan_name = result.get("intent", line[:40])
                    steps = result["steps"]
                    reasoning = result.get("reasoning", "")

                    if reasoning:
                        print(f"  [Reasoning] {reasoning}")

                    print(f"  [Plan] {plan_name} ({len(steps)} steps)")
                    for i, step in enumerate(steps):
                        action = step.get("action", {})
                        print(f"    {i+1}. {step.get('name', '?')} "
                              f"[{action.get('type', '?')}]")
                    print()

                    # Auto-execute the plan
                    print("  Executing...")
                    start = time.time()
                    graph = orch.run({
                        "name": plan_name,
                        "steps": steps,
                    })
                    elapsed = (time.time() - start) * 1000

                    done, total = graph.progress
                    print(f"  [{done}/{total}] completed in {elapsed:.0f}ms")

                    for nid, node in graph.nodes.items():
                        icon = "✓" if node.state == NodeState.SUCCESS else "✗"
                        print(f"    {icon} {node.name}")
                        if node.result and node.result.output:
                            output = node.result.output
                            if isinstance(output, dict):
                                stdout = output.get("stdout", "")
                                if stdout:
                                    for l in stdout.splitlines()[:5]:
                                        print(f"      {l}")
                            elif isinstance(output, str):
                                for l in output.splitlines()[:5]:
                                    print(f"      {l}")
                        if node.result and node.result.error:
                            print(f"      ERROR: {node.result.error[:200]}")
                    print()
                    continue
            else:
                # No AI — try as command
                print(f"  [No AI] Treating as command: {line}")
                graph = orch.run(line)
                done, total = graph.progress
                node = list(graph.nodes.values())[0]
                if node.result and node.result.output:
                    output = node.result.output
                    if isinstance(output, dict):
                        stdout = output.get("stdout", "")
                        if stdout:
                            print(stdout)
                    elif isinstance(output, str):
                        print(output)
                if node.result and node.result.error:
                    print(f"  [error] {node.result.error[:300]}")
                print()
                continue

        except Exception as e:
            print(f"  [AI Error] {e}")
            # Fallback: treat as command
            try:
                graph = orch.run(f"!{line}")
                node = list(graph.nodes.values())[0]
                if node.result and node.result.output:
                    output = node.result.output
                    if isinstance(output, dict):
                        stdout = output.get("stdout", "")
                        if stdout:
                            print(stdout)
                    elif isinstance(output, str):
                        print(output)
                if node.result and node.result.error:
                    print(f"  [error] {node.result.error[:300]}")
            except Exception:
                pass
            print()


def cmd_web(args: list[str]):
    """Launch web dashboard."""
    port = int(args[0]) if args else 7700
    print(f"  Starting JAMES Web Dashboard on http://127.0.0.1:{port}")
    print("  Press Ctrl+C to stop.")
    print()
    from james.web.server import app
    app.run(host="127.0.0.1", port=port, debug=False)


def main():
    """Main CLI entry point."""
    _print_header()

    if len(sys.argv) < 2 or sys.argv[1].lower() == "shell":
        # No args or explicit 'shell' → interactive REPL
        cmd_shell()
        return

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    commands = {
        "status": lambda: cmd_status(),
        "run": lambda: cmd_run(args),
        "cmd": lambda: cmd_command(args),
        "bootstrap": lambda: cmd_bootstrap(),
        "skills": lambda: cmd_skills(),
        "memory": lambda: cmd_memory(),
        "optimize": lambda: cmd_optimize(),
        "audit": lambda: cmd_audit(args),
        "diagnose": lambda: cmd_diagnose(),
        "layers": lambda: cmd_layers(),
        "web": lambda: cmd_web(args),
    }

    handler = commands.get(command)
    if handler:
        try:
            handler()
        except Exception as e:
            print(f"  [X] Error: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"  Unknown command: {command}")
        print("  Run 'python -m james' for usage info.")


if __name__ == "__main__":
    main()

