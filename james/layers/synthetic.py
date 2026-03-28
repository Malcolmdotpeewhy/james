"""
JAMES Layer 4 — Synthetic Capability Engineering

When no control path exists, JAMES builds one:
  - Dynamic CLI wrapper generator
  - API bridge scaffolder
  - Accessibility hook interface (UI Automation COM)
  - [Unverified] stubs: memory hooks, binary instrumentation
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from typing import Any

from james.layers import ControlLayer, LayerLevel, LayerResult

logger = logging.getLogger("james.layers.synthetic")


class SyntheticLayer(ControlLayer):
    """
    Layer 4: Dynamically creates control mechanisms where none exist.
    """

    level = LayerLevel.SYNTHETIC
    name = "synthetic_engineering"
    description = "CLI wrapper generation, API bridges, accessibility hooks"

    def execute(self, action: dict) -> LayerResult:
        """
        Supported action types:
            - "cli_wrapper":      Generate a CLI wrapper script
            - "api_bridge":       Scaffold an API bridge
            - "ui_automation":    Windows UI Automation COM access
            - "accessibility":    Accessibility tree query
            - "memory_hook":      [Unverified] stub
            - "binary_instrument": [Unverified] stub
        """
        action_type = action.get("type", "")
        dispatch = {
            "cli_wrapper": self._generate_cli_wrapper,
            "api_bridge": self._scaffold_api_bridge,
            "ui_automation": self._ui_automation,
            "accessibility": self._accessibility_query,
            "memory_hook": self._stub_unverified,
            "binary_instrument": self._stub_unverified,
        }

        handler = dispatch.get(action_type)
        if not handler:
            return LayerResult(
                success=False,
                error=f"Unknown synthetic action type: {action_type}",
            )

        start = time.perf_counter()
        try:
            result = handler(action)
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            logger.error(f"Synthetic layer error in {action_type}: {e}")
            return LayerResult(success=False, error=str(e), duration_ms=duration)

    def is_available(self) -> bool:
        """Synthetic layer is always available (creates what it needs)."""
        return True

    # ── CLI Wrapper Generator ────────────────────────────────────

    def _generate_cli_wrapper(self, action: dict) -> LayerResult:
        """
        Generate a CLI wrapper script for an application.
        action keys:
            - target: application path or name
            - commands: list of command definitions [{name, args, description}]
            - output_path: where to write the wrapper
        """
        app = action.get("target", "")
        commands = action.get("commands", [])
        output_path = action.get("output_path", "")

        if not output_path:
            output_path = os.path.join(
                tempfile.gettempdir(),
                f"james_wrapper_{os.path.basename(app).replace('.', '_')}.py"
            )

        lines = [
            '"""Auto-generated CLI wrapper by JAMES Layer 4."""',
            "import subprocess",
            "import sys",
            "",
            f'APP = r"{app}"',
            "",
        ]

        for cmd in commands:
            name = cmd.get("name", "default")
            args = cmd.get("args", [])
            desc = cmd.get("description", "")
            lines.append(f"def {name}():")
            lines.append(f'    """{ desc }"""')
            args_str = ", ".join(f'"{a}"' for a in args)
            lines.append(f"    return subprocess.run([APP, {args_str}], capture_output=True, text=True)")
            lines.append("")

        lines.append('if __name__ == "__main__":')
        lines.append("    cmd = sys.argv[1] if len(sys.argv) > 1 else 'default'")
        lines.append("    fn = globals().get(cmd)")
        lines.append("    if fn:")
        lines.append("        result = fn()")
        lines.append("        print(result.stdout)")
        lines.append("    else:")
        lines.append('        print(f"Unknown command: {cmd}")')

        script_content = "\n".join(lines)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(script_content)

        return LayerResult(
            success=True,
            output={"wrapper_path": output_path, "commands": len(commands)},
        )

    # ── API Bridge Scaffolder ────────────────────────────────────

    def _scaffold_api_bridge(self, action: dict) -> LayerResult:
        """
        Scaffold an API bridge for an application.
        action keys:
            - target: base URL or application identifier
            - endpoints: list of [{path, method, description}]
            - output_path: where to write the bridge module
        """
        base_url = action.get("target", "http://localhost:8080")
        endpoints = action.get("endpoints", [])
        output_path = action.get("output_path", "")

        if not output_path:
            safe_name = base_url.replace("://", "_").replace("/", "_").replace(":", "_")
            output_path = os.path.join(tempfile.gettempdir(), f"james_bridge_{safe_name}.py")

        lines = [
            '"""Auto-generated API bridge by JAMES Layer 4."""',
            "import json",
            "import urllib.request",
            "import urllib.error",
            "",
            f'BASE_URL = "{base_url}"',
            "",
            "",
            "class APIBridge:",
            '    """Auto-generated API bridge."""',
            "",
            "    def __init__(self, base_url=BASE_URL):",
            "        self.base_url = base_url.rstrip('/')",
            "",
            "    def _request(self, method, path, data=None):",
            '        url = f"{self.base_url}{path}"',
            "        headers = {'Content-Type': 'application/json'}",
            "        body = json.dumps(data).encode() if data else None",
            "        req = urllib.request.Request(url, method=method, headers=headers, data=body)",
            "        try:",
            "            with urllib.request.urlopen(req, timeout=30) as resp:",
            "                return {'status': resp.status, 'body': json.loads(resp.read())}",
            "        except urllib.error.HTTPError as e:",
            "            return {'status': e.code, 'error': e.reason}",
            "        except Exception as e:",
            "            return {'status': 0, 'error': str(e)}",
            "",
        ]

        for ep in endpoints:
            path = ep.get("path", "/")
            method = ep.get("method", "GET")
            desc = ep.get("description", "")
            fn_name = path.strip("/").replace("/", "_").replace("-", "_") or "root"
            lines.append(f"    def {fn_name}(self, data=None):")
            lines.append(f'        """{desc}"""')
            lines.append(f'        return self._request("{method}", "{path}", data)')
            lines.append("")

        script_content = "\n".join(lines)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(script_content)

        return LayerResult(
            success=True,
            output={"bridge_path": output_path, "endpoints": len(endpoints)},
        )

    # ── Windows UI Automation ────────────────────────────────────

    def _ui_automation(self, action: dict) -> LayerResult:
        """
        Windows UI Automation via COM (comtypes/uiautomation).
        Falls back to PowerShell if COM not available.
        """
        target_window = action.get("target", "")
        operation = action.get("operation", "list_elements")

        # Try Python uiautomation package
        try:
            import uiautomation as auto
            if operation == "list_elements":
                window = auto.WindowControl(searchDepth=1, Name=target_window)
                if not window.Exists(3):
                    return LayerResult(success=False, error=f"Window not found: {target_window}")
                children = []
                for ctrl in window.GetChildren():
                    children.append({
                        "name": ctrl.Name,
                        "type": ctrl.ControlTypeName,
                        "automationId": ctrl.AutomationId,
                    })
                return LayerResult(success=True, output=children)
            elif operation == "click":
                element_name = action.get("element_name", "")
                window = auto.WindowControl(searchDepth=1, Name=target_window)
                ctrl = window.Control(searchDepth=5, Name=element_name)
                if ctrl.Exists(3):
                    ctrl.Click()
                    return LayerResult(success=True, output=f"Clicked: {element_name}")
                return LayerResult(success=False, error=f"Element not found: {element_name}")
        except ImportError:
            pass

        # Fallback: PowerShell UI Automation
        ps_script = f"""
Add-Type -AssemblyName UIAutomationClient
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty, "{target_window}")
$window = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if ($window) {{ "Found: {target_window}" }} else {{ "Not found" }}
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
        )
        return LayerResult(
            success="Found:" in result.stdout,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    # ── Accessibility Query ──────────────────────────────────────

    def _accessibility_query(self, action: dict) -> LayerResult:
        """Query accessibility tree for elements."""
        target = action.get("target", "")
        # Delegate to UI Automation
        return self._ui_automation({
            "type": "ui_automation",
            "target": target,
            "operation": "list_elements",
        })

    # ── Unverified Stubs ─────────────────────────────────────────

    def _stub_unverified(self, action: dict) -> LayerResult:
        """
        Stub for [Unverified] capabilities.
        These are NOT implemented for safety reasons.
        """
        action_type = action.get("type", "unknown")
        logger.warning(
            f"[UNVERIFIED] Action '{action_type}' is not implemented. "
            "Memory hooks and binary instrumentation are restricted."
        )
        return LayerResult(
            success=False,
            error=(
                f"[UNVERIFIED] '{action_type}' is not implemented. "
                "This capability is restricted per JAMES security policy. "
                "Consider using Layers 1-3 or Layer 5 instead."
            ),
        )
