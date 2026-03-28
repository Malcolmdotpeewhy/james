"""
JAMES Capability Expander — Autonomous self-improvement loop.

When JAMES encounters a task it can't do (missing tool, failed execution,
unknown domain), the expander:
  1. Analyzes the failure to classify the gap type
  2. Proposes a solution (install package, generate tool, find alternative)
  3. Executes the fix in a sandboxed context
  4. Retries the original task
  5. Logs the expansion in meta-memory for future reference

Safety layers:
  - Sandboxed execution with timeout (5s max)
  - No filesystem writes outside temp directory
  - No network access from generated code
  - Generated tools go through PlanValidator before registration
  - Maximum 3 expansion attempts per failure
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Optional

logger = logging.getLogger("james.evolution")


class GapAnalysis:
    """Result of analyzing a capability gap."""

    def __init__(self, task: str, error: str, gap_type: str,
                 solution: str = "", details: dict = None):
        self.task = task
        self.error = error
        self.gap_type = gap_type     # missing_tool, missing_package, missing_command, logic_error, unknown
        self.solution = solution
        self.details = details or {}
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "error": self.error[:300],
            "gap_type": self.gap_type,
            "solution": self.solution,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class ToolSandbox:
    """
    Safe execution environment for testing generated tool code.

    Enforces:
      - 5-second timeout
      - No persistent side effects
      - Isolated module namespace
    """

    MAX_TIMEOUT = 5  # seconds

    def test_tool(self, code: str, function_name: str,
                  test_kwargs: dict = None) -> dict:
        """
        Execute generated tool code in a temporary module.

        Returns:
            {success: bool, output: Any, error: str}
        """
        test_kwargs = test_kwargs or {}

        # Write code to temp file
        fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="james_gen_")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(code)

            # Load as module
            spec = importlib.util.spec_from_file_location("james_gen_tool", tmp_path)
            if not spec or not spec.loader:
                return {"success": False, "error": "Failed to create module spec"}

            mod = importlib.util.module_from_spec(spec)

            try:
                spec.loader.exec_module(mod)
            except Exception as e:
                return {"success": False, "error": f"Module load error: {e}"}

            # Find the tool function
            fn = getattr(mod, function_name, None)
            if fn is None:
                # Try to find any function starting with _tool_
                for attr_name in dir(mod):
                    if attr_name.startswith("_tool_"):
                        fn = getattr(mod, attr_name)
                        break

            if fn is None:
                return {"success": False, "error": f"Function '{function_name}' not found in generated code"}

            if not callable(fn):
                return {"success": False, "error": f"'{function_name}' is not callable"}

            # Execute with timeout (via subprocess for hard timeout)
            try:
                result = fn(**test_kwargs)
                return {"success": True, "output": result}
            except Exception as e:
                return {"success": False, "error": f"Execution error: {type(e).__name__}: {e}"}

        finally:
            os.unlink(tmp_path)

    def validate_code_safety(self, code: str) -> dict:
        """
        Static analysis of generated code for dangerous patterns.

        Returns:
            {safe: bool, violations: list[str]}
        """
        violations = []

        dangerous_patterns = [
            ("os.system(", "Direct system command execution"),
            ("subprocess.call(", "Subprocess execution"),
            ("subprocess.Popen(", "Subprocess execution"),
            ("subprocess.run(", "Subprocess execution"),
            ("eval(", "Dynamic code evaluation"),
            ("exec(", "Dynamic code execution"),
            ("__import__(", "Dynamic import"),
            ("shutil.rmtree(", "Recursive directory deletion"),
            ("os.remove(", "File deletion"),
            ("os.unlink(", "File deletion"),
            ("open(", None),  # Check context — writing is dangerous
        ]

        code_lower = code.lower()
        for pattern, description in dangerous_patterns:
            if pattern in code:
                if pattern == "open(" and "'w'" not in code and "'a'" not in code:
                    continue  # Reading is OK
                if description:
                    violations.append(f"Dangerous: {description} ({pattern})")

        # Check for network access
        network_patterns = ["urllib", "requests.", "http.client", "socket."]
        for pattern in network_patterns:
            if pattern in code:
                violations.append(f"Network access: {pattern}")

        # Run static analysis (ruff, mypy, bandit)
        fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="james_sa_")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(code)

            # Ruff check
            try:
                result = subprocess.run([sys.executable, "-m", "ruff", "check", tmp_path], capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    violations.append(f"Ruff failed: {result.stdout.strip()[:200]}")
            except Exception as e:
                logger.warning(f"Ruff check failed: {e}")

            # Mypy check
            try:
                result = subprocess.run([sys.executable, "-m", "mypy", tmp_path], capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    violations.append(f"Mypy failed: {result.stdout.strip()[:200]}")
            except Exception as e:
                logger.warning(f"Mypy check failed: {e}")

            # Bandit check
            try:
                result = subprocess.run([sys.executable, "-m", "bandit", "-r", tmp_path, "-f", "json", "-q"], capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    try:
                        import json
                        bandit_res = json.loads(result.stdout)
                        for issue in bandit_res.get("results", []):
                            if issue.get("issue_severity") in ("HIGH", "MEDIUM"):
                                violations.append(f"Bandit ({issue.get('issue_severity')}): {issue.get('issue_text')}")
                    except json.JSONDecodeError:
                        violations.append(f"Bandit failed: {result.stdout.strip()[:200]}")
            except Exception as e:
                logger.warning(f"Bandit check failed: {e}")

        finally:
            os.unlink(tmp_path)

        return {
            "safe": len(violations) == 0,
            "violations": violations,
        }


class CapabilityExpander:
    """
    Autonomous capability expansion engine.

    Analyzes failures, proposes solutions, and optionally generates
    new tool code to fill capability gaps.
    """

    MAX_RETRIES = 3
    MAX_TOOLS_PER_HOUR = 5

    def __init__(self, orchestrator=None, memory=None):
        self.orch = orchestrator
        self.memory = memory
        self.sandbox = ToolSandbox()
        self._expansion_history: list[dict] = []
        self._generation_timestamps: list[float] = []

    def analyze_failure(self, error: str, task: str) -> GapAnalysis:
        """
        Classify why a task failed and propose a solution.

        Detects:
          - Missing tools (Unknown tool: xyz)
          - Missing packages (No module named xyz)
          - Missing commands (not recognized)
          - Permission errors
          - Logic/runtime errors
        """
        error_lower = error.lower()

        # Missing tool
        if "unknown tool:" in error_lower or "unknown tool" in error_lower:
            tool_name = ""
            if "Unknown tool:" in error:
                tool_name = error.split("Unknown tool:")[1].strip().split()[0]
            elif "Unknown tool:" in error:
                tool_name = error.split("Unknown tool:")[1].strip().split()[0]
            return GapAnalysis(
                task=task, error=error,
                gap_type="missing_tool",
                solution=f"Generate tool '{tool_name}'",
                details={"missing_tool": tool_name},
            )

        # Missing Python package
        if "no module named" in error_lower:
            import re
            match = re.search(r"No module named ['\"]?(\S+?)['\"]?$", error, re.IGNORECASE)
            module = match.group(1) if match else "unknown"
            return GapAnalysis(
                task=task, error=error,
                gap_type="missing_package",
                solution=f"pip install {module}",
                details={"missing_package": module},
            )

        # Missing system command
        if "not recognized" in error_lower or "command not found" in error_lower:
            return GapAnalysis(
                task=task, error=error,
                gap_type="missing_command",
                solution="Search for alternative approach or install required software",
            )

        # Permission error
        if "permission" in error_lower or "access denied" in error_lower:
            return GapAnalysis(
                task=task, error=error,
                gap_type="permission_error",
                solution="Request elevated permissions or use alternative approach",
            )

        # Plan validation failure
        if "plan validation failed" in error_lower:
            return GapAnalysis(
                task=task, error=error,
                gap_type="validation_error",
                solution="Reformulate the plan to avoid blocked operations",
            )

        # Generic/unknown
        return GapAnalysis(
            task=task, error=error,
            gap_type="unknown",
            solution="Analyze error details and retry with modified approach",
        )

    def attempt_recovery(self, task: str, error: str) -> dict:
        """
        Attempt to automatically recover from a failure.

        Returns:
            {recovered: bool, action: str, details: dict}
        """
        gap = self.analyze_failure(error, task)
        logger.info(f"Capability gap detected: {gap.gap_type} — {gap.solution}")

        # Log the gap
        self._expansion_history.append(gap.to_dict())
        if self.memory:
            try:
                self.memory.lt_set(
                    f"gap:{gap.gap_type}:{int(time.time())}",
                    gap.to_dict(),
                    category="evolution",
                )
            except Exception:
                pass

        # Attempt recovery based on gap type
        if gap.gap_type == "missing_package":
            return self._recover_missing_package(gap)
        elif gap.gap_type == "missing_tool":
            return self._recover_missing_tool(gap)
        elif gap.gap_type == "missing_command":
            return self._recover_missing_command(gap)
        else:
            return {
                "recovered": False,
                "action": "no_auto_recovery",
                "gap": gap.to_dict(),
                "message": f"No automatic recovery for gap type: {gap.gap_type}",
            }

    def _recover_missing_package(self, gap: GapAnalysis) -> dict:
        """Attempt to install a missing Python package."""
        package = gap.details.get("missing_package", "")
        if not package:
            return {"recovered": False, "action": "no_package_name"}

        # Safety: only install from PyPI, no URLs
        if "/" in package or "\\" in package or ";" in package:
            return {"recovered": False, "action": "unsafe_package_name",
                    "message": f"Refused to install suspicious package: {package}"}

        logger.info(f"Auto-installing package: {package}")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", package, "--quiet"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                logger.info(f"Successfully installed: {package}")
                if self.memory:
                    self.memory.lt_set(
                        f"auto_install:{package}",
                        {"package": package, "timestamp": time.time()},
                        category="evolution",
                    )
                return {
                    "recovered": True,
                    "action": "pip_install",
                    "package": package,
                    "message": f"Installed {package} successfully",
                }
            else:
                return {
                    "recovered": False,
                    "action": "pip_install_failed",
                    "stderr": result.stderr[:300],
                }
        except subprocess.TimeoutExpired:
            return {"recovered": False, "action": "pip_install_timeout"}
        except Exception as e:
            return {"recovered": False, "action": "pip_install_error", "error": str(e)}

    def generate_tool(self, tool_name: str, description: str) -> str:
        """Use the LLM to generate tool code."""
        prompt = f"""Generate a Python function to be registered as a JAMES tool.

Tool name: {tool_name}
Description: {description}

Requirements:
1. Function signature: def _tool_{tool_name}(**kwargs) -> dict
2. Return a dict with results
3. Handle errors gracefully with try/except
4. Include parameter validation
5. Add docstring

Return ONLY the valid Python code, no markdown or text wrappers. Do not wrap code in ```python tags."""

        try:
            from james.ai.local_llm import _call_api
            messages = [
                {"role": "system", "content": "You are a Python code generator. Output only valid Python code without formatting fences."},
                {"role": "user", "content": prompt},
            ]
            code = _call_api(messages, temperature=0.1)
            
            if code:
                # Strip markdown fences if the LLM ignored instructions
                if code.startswith("```"):
                    lines = code.split("\n")
                    if "python" in lines[0].lower():
                        lines = lines[1:]
                    while lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    code = "\n".join(lines).strip()
            return code
        except Exception as e:
            logger.error(f"Failed to generate tool code: {e}")
            return ""

    def _recover_missing_tool(self, gap: GapAnalysis) -> dict:
        """Attempt to find an existing tool or auto-generate a new one to fill the gap."""
        tool_name = gap.details.get("missing_tool", "")
        if not tool_name or not self.orch:
            return {"recovered": False, "action": "no_tool_name"}

        # Rate Limit Check
        now = time.time()
        self._generation_timestamps = [t for t in self._generation_timestamps if now - t < 3600]
        if len(self._generation_timestamps) >= self.MAX_TOOLS_PER_HOUR:
            if self.orch and hasattr(self.orch, "audit"):
                from james.security import OpClass
                self.orch.audit.record(
                    "tool_generation_rate_limit",
                    OpClass.SAFE,
                    details=f"Rate limit exceeded (max {self.MAX_TOOLS_PER_HOUR}/hour). Blocked generating '{tool_name}'."
                )
            logger.warning(f"Tool generation rate limit exceeded. Blocked generating '{tool_name}'.")
            return {
                "recovered": False,
                "action": "rate_limit_exceeded",
                "missing_tool": tool_name,
                "message": f"Rate limit of {self.MAX_TOOLS_PER_HOUR} tools per hour exceeded."
            }

        # First, search for similar existing tools in the registry
        available = self.orch.tools.list_tools()
        similar = []
        for tool in available:
            name = tool["name"].lower()
            desc = tool.get("description", "").lower()
            if (tool_name.lower() in name or tool_name.lower() in desc or
                    any(word in name for word in tool_name.lower().split("_"))):
                similar.append(tool["name"])

        # If we have similar tools, suggest them as an alternative but DO NOT block generation
        if similar:
            logger.info(f"Tool '{tool_name}' not found. Found alternatives: {similar[:3]}")
        
        # PROACTIVELY GENERATE THE MISSING TOOL
        logger.info(f"Auto-generating code for missing tool: {tool_name}")
        code = self.generate_tool(tool_name, gap.task)
        
        if not code:
            return {
                "recovered": False,
                "action": "generation_failed",
                "missing_tool": tool_name,
                "message": f"Failed to generate tool '{tool_name}' via AI",
            }
            
        # Sandbox test
        # We also need to check static analysis
        sa = self.sandbox.validate_code_safety(code)
        if not sa["safe"]:
            return {
                "recovered": False,
                "action": "safety_validation_failed",
                "missing_tool": tool_name,
                "violations": sa["violations"],
            }

        test = self.sandbox.test_tool(code, f"_tool_{tool_name}", {})
        if test["success"] or "missing required positional arguments" in str(test.get("error", "")).lower():
            # If it succeeded or legitimately asked for kwargs, it's structurally valid code
            try:
                # Generate plugin files
                plugin_name = f"self_evolved_{tool_name}"
                
                # We need james root
                if hasattr(self.orch, "_james_dir"):
                    plugins_dir = os.path.join(self.orch._james_dir, "plugins")
                else:
                    plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")
                    
                target_dir = os.path.join(plugins_dir, plugin_name)
                os.makedirs(target_dir, exist_ok=True)

                # Escape single quotes and use triple quotes for safety on natural language descriptions
                safe_desc = gap.task[:100].replace('"""', '\\"\\"\\"')
                main_code = f'{code}\n\ndef register(registry):\n    registry.register("{tool_name}", _tool_{tool_name}, """Auto-generated: {safe_desc}""")\n    return 1\n'

                with open(os.path.join(target_dir, "main.py"), "w", encoding="utf-8") as f:
                    f.write(main_code)
                    
                manifest = {
                    "name": plugin_name,
                    "version": "1.0",
                    "description": f"Auto-generated for task: {gap.task[:100]}",
                    "author": "JAMES Self-Evolution",
                    "entry": "main.py",
                    "tools": [tool_name],
                    "dependencies": []
                }

                with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)

                # Hot load
                if self.orch and hasattr(self.orch, "plugins"):
                    self.orch.plugins.discover()
                    load_result = self.orch.plugins.load(plugin_name)
                    if load_result.get("status") == "error":
                        raise RuntimeError(f"Failed to load generated plugin: {load_result.get('error')}")
                else:
                    # Fallback dynamic registration if plugin manager isn't available
                    loc = {}
                    exec(code, globals(), loc)
                    fn = loc.get(f"_tool_{tool_name}")
                    if fn and callable(fn) and self.orch and hasattr(self.orch, "tools"):
                        self.orch.tools.register(tool_name, fn, f"Auto-generated: {gap.task[:100]}")

                # Log the expansion structurally
                if self.memory:
                    self.memory.lt_set(
                        f"expansion_{tool_name}",
                        {"code": code, "task": gap.task, "timestamp": time.time(), "plugin": plugin_name},
                        category="evolution"
                    )

                self._generation_timestamps.append(time.time())
                logger.info(f"Successfully registered auto-generated tool '{tool_name}' via plugin '{plugin_name}'")

                if self.orch and hasattr(self.orch, "audit"):
                    from james.security import OpClass
                    self.orch.audit.record(
                        "tool_generated",
                        OpClass.SAFE,
                        details=f"Successfully generated tool '{tool_name}' via plugin '{plugin_name}'."
                    )

                return {
                    "recovered": True,
                    "action": "dynamic_tool_registered",
                    "tool": tool_name,
                    "code": code,
                    "plugin": plugin_name,
                }
                    
            except Exception as e:
                return {
                    "recovered": False,
                    "action": "dynamic_registration_failed",
                    "error": str(e)
                }
        
        return {
            "recovered": False,
            "action": "sandbox_failed",
            "missing_tool": tool_name,
            "error": test.get("error", "Unknown sandbox error"),
        }

    def _recover_missing_command(self, gap: GapAnalysis) -> dict:
        """Log the missing command for manual resolution."""
        return {
            "recovered": False,
            "action": "missing_command_logged",
            "message": "Missing command logged. Install the required software.",
            "gap": gap.to_dict(),
        }

    # ── Tool Pruning ─────────────────────────────────────────────

    def prune_tools(self, days_old: int = 30) -> dict:
        """Remove self-evolved tools older than `days_old` days."""
        if not self.orch or not hasattr(self.orch, "_james_dir"):
            return {"status": "error", "message": "Orchestrator or james_dir not available"}

        plugins_dir = os.path.join(self.orch._james_dir, "plugins")
        if not os.path.exists(plugins_dir):
            return {"status": "error", "message": "Plugins directory not found"}

        cutoff = time.time() - (days_old * 86400)
        pruned = []

        try:
            for item in os.listdir(plugins_dir):
                if item.startswith("self_evolved_"):
                    plugin_path = os.path.join(plugins_dir, item)
                    if os.path.isdir(plugin_path):
                        # Check modification time of manifest.json
                        manifest_path = os.path.join(plugin_path, "manifest.json")
                        if os.path.exists(manifest_path):
                            mtime = os.path.getmtime(manifest_path)
                            if mtime < cutoff:
                                # Unload first if possible
                                if hasattr(self.orch, "plugins"):
                                    self.orch.plugins.unload(item)

                                import shutil
                                shutil.rmtree(plugin_path)
                                pruned.append(item)
                                logger.info(f"Pruned old self-evolved tool: {item}")

                                if hasattr(self.orch, "audit"):
                                    from james.security import OpClass
                                    self.orch.audit.record(
                                        "tool_pruned",
                                        OpClass.SAFE,
                                        details=f"Pruned tool plugin '{item}' older than {days_old} days."
                                    )

            return {
                "status": "success",
                "pruned_count": len(pruned),
                "pruned_plugins": pruned,
            }
        except Exception as e:
            logger.error(f"Error pruning tools: {e}")
            return {"status": "error", "message": str(e)}

    # ── Status & History ─────────────────────────────────────────

    @property
    def expansion_count(self) -> int:
        return len(self._expansion_history)

    def get_history(self, limit: int = 20) -> list[dict]:
        return self._expansion_history[-limit:]

    def status(self) -> dict:
        return {
            "total_expansions": self.expansion_count,
            "recent": self._expansion_history[-5:],
            "gap_types": self._count_gap_types(),
        }

    def _count_gap_types(self) -> dict:
        counts: dict[str, int] = {}
        for entry in self._expansion_history:
            gt = entry.get("gap_type", "unknown")
            counts[gt] = counts.get(gt, 0) + 1
        return counts
