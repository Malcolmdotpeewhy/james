"""
JAMES Layer 1 — Native System Authority

Direct OS interaction:
  - PowerShell / cmd command execution
  - WMI queries (lazy import)
  - Registry access via winreg
  - File system operations
  - Process management
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

from james.layers import ControlLayer, LayerLevel, LayerResult

logger = logging.getLogger("james.layers.native")


class NativeLayer(ControlLayer):
    """
    Layer 1: Highest reliability, lowest latency.
    Direct interaction with the operating system.
    """

    level = LayerLevel.NATIVE
    name = "native_system"
    description = "Direct OS interaction via PowerShell, WMI, registry, filesystem"

    # ── Action Dispatch ──────────────────────────────────────────

    def execute(self, action: dict) -> LayerResult:
        """
        Execute a native system action.

        Supported action types:
            - "command":    Run a shell command
            - "powershell": Run PowerShell command
            - "file_read":  Read a file
            - "file_write": Write to a file
            - "file_list":  List directory contents
            - "file_exists": Check if path exists
            - "file_delete": Delete a file
            - "process_list": List running processes
            - "process_kill": Kill a process by name/PID
            - "env_get":    Get environment variable
            - "env_set":    Set environment variable (current process)
            - "registry":   Read/write Windows registry
            - "wmi_query":  WMI query
        """
        action_type = action.get("type", "")
        dispatch = {
            "command": self._run_command,
            "powershell": self._run_powershell,
            "file_read": self._file_read,
            "file_write": self._file_write,
            "file_list": self._file_list,
            "file_exists": self._file_exists,
            "file_delete": self._file_delete,
            "process_list": self._process_list,
            "process_kill": self._process_kill,
            "env_get": self._env_get,
            "env_set": self._env_set,
            "registry": self._registry_op,
            "wmi_query": self._wmi_query,
            "tool_call": self._tool_call,
            "noop": self._noop,
        }

        handler = dispatch.get(action_type)
        if not handler:
            return LayerResult(
                success=False,
                error=f"Unknown native action type: {action_type}",
            )

        start = time.perf_counter()
        try:
            result = handler(action)
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            logger.error(f"Native layer error in {action_type}: {e}")
            return LayerResult(success=False, error=str(e), duration_ms=duration)

    def is_available(self) -> bool:
        """Native layer is always available on Windows."""
        return os.name == "nt"

    # ── Command Execution ────────────────────────────────────────

    def _run_command(self, action: dict) -> LayerResult:
        """Run a shell command via subprocess."""
        cmd = action.get("target", "")
        timeout = action.get("timeout", 60)
        shell = action.get("shell", True)
        cwd = action.get("cwd")

        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return LayerResult(
            success=result.returncode == 0,
            output={
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    def _run_powershell(self, action: dict) -> LayerResult:
        """Run a PowerShell command."""
        cmd = action.get("target", "")
        timeout = action.get("timeout", 60)

        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return LayerResult(
            success=result.returncode == 0,
            output={
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    # ── File System ──────────────────────────────────────────────

    def _file_read(self, action: dict) -> LayerResult:
        path = action.get("target", "")
        encoding = action.get("encoding", "utf-8")
        if not os.path.isfile(path):
            return LayerResult(success=False, error=f"File not found: {path}")
        content = open(path, "r", encoding=encoding).read()
        return LayerResult(success=True, output=content)

    def _file_write(self, action: dict) -> LayerResult:
        path = action.get("target", "")
        content = action.get("content", "")
        encoding = action.get("encoding", "utf-8")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding=encoding) as f:
            f.write(content)
        return LayerResult(success=True, output=f"Written {len(content)} bytes to {path}")

    def _file_list(self, action: dict) -> LayerResult:
        path = action.get("target", ".")
        if not os.path.isdir(path):
            return LayerResult(success=False, error=f"Directory not found: {path}")
        entries = []
        for entry in os.scandir(path):
            entries.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
            })
        return LayerResult(success=True, output=entries)

    def _file_exists(self, action: dict) -> LayerResult:
        path = action.get("target", "")
        exists = os.path.exists(path)
        return LayerResult(success=True, output={"exists": exists, "path": path})

    def _file_delete(self, action: dict) -> LayerResult:
        path = action.get("target", "")
        if not os.path.exists(path):
            return LayerResult(success=True, output="Already absent")
        os.remove(path)
        return LayerResult(success=True, output=f"Deleted: {path}")

    # ── Process Management ───────────────────────────────────────

    def _process_list(self, action: dict) -> LayerResult:
        filter_name = action.get("target", "")
        cmd = "tasklist /FO CSV /NH"
        if filter_name:
            cmd = f'tasklist /FI "IMAGENAME eq {filter_name}" /FO CSV /NH'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        processes = []
        for line in result.stdout.strip().splitlines():
            parts = line.replace('"', '').split(',')
            if len(parts) >= 5:
                processes.append({
                    "name": parts[0],
                    "pid": parts[1],
                    "session": parts[2],
                    "memory": parts[4],
                })
        return LayerResult(success=True, output=processes)

    def _process_kill(self, action: dict) -> LayerResult:
        target = action.get("target", "")
        try:
            pid = int(target)
            cmd = f"taskkill /PID {pid} /F"
        except ValueError:
            cmd = f'taskkill /IM "{target}" /F'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return LayerResult(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    # ── Environment Variables ────────────────────────────────────

    def _env_get(self, action: dict) -> LayerResult:
        var = action.get("target", "")
        value = os.environ.get(var)
        return LayerResult(success=True, output={"variable": var, "value": value})

    def _env_set(self, action: dict) -> LayerResult:
        var = action.get("target", "")
        value = action.get("value", "")
        os.environ[var] = value
        return LayerResult(success=True, output=f"Set {var}={value}")

    # ── Windows Registry ─────────────────────────────────────────

    def _registry_op(self, action: dict) -> LayerResult:
        try:
            import winreg
        except ImportError:
            return LayerResult(success=False, error="winreg not available (non-Windows)")

        op = action.get("operation", "read")
        key_path = action.get("target", "")
        value_name = action.get("value_name", "")

        # Map common root key strings
        root_map = {
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKCR": winreg.HKEY_CLASSES_ROOT,
        }

        parts = key_path.split("\\", 1)
        if len(parts) < 2:
            return LayerResult(success=False, error=f"Invalid registry path: {key_path}")

        root_key = root_map.get(parts[0].upper())
        if not root_key:
            return LayerResult(success=False, error=f"Unknown registry root: {parts[0]}")

        subkey = parts[1]

        if op == "read":
            try:
                key = winreg.OpenKey(root_key, subkey, access=winreg.KEY_READ)
                value, reg_type = winreg.QueryValueEx(key, value_name)
                winreg.CloseKey(key)
                return LayerResult(success=True, output={"value": value, "type": reg_type})
            except FileNotFoundError:
                return LayerResult(success=False, error=f"Registry key not found: {key_path}")
        else:
            return LayerResult(success=False, error="Registry write ops gated by security policy")

    # ── WMI ──────────────────────────────────────────────────────

    def _wmi_query(self, action: dict) -> LayerResult:
        """Execute a WMI query. Requires `wmi` package (lazy import)."""
        try:
            import wmi as wmi_mod
        except ImportError:
            # Fallback to PowerShell WMI
            query = action.get("target", "")
            return self._run_powershell({
                "target": f"Get-WmiObject -Query '{query}' | ConvertTo-Json",
                "timeout": 30,
            })

        query = action.get("target", "")
        c = wmi_mod.WMI()
        try:
            results = c.query(query)
            output = []
            for item in results:
                props = {}
                for prop in item.properties:
                    try:
                        props[prop] = getattr(item, prop)
                    except Exception:
                        props[prop] = None
                output.append(props)
            return LayerResult(success=True, output=output)
        except Exception as e:
            return LayerResult(success=False, error=f"WMI query failed: {e}")

    # ── Tool Call (registered Python tools) ──────────────────

    def _tool_call(self, action: dict) -> LayerResult:
        """Call a registered tool by name with kwargs."""
        tool_name = action.get("target", "")
        kwargs = action.get("kwargs", {})

        try:
            from james.tools import get_registry
            registry = get_registry()
            result = registry.call(tool_name, **kwargs)
            return LayerResult(success=True, output=result)
        except ValueError as e:
            return LayerResult(success=False, error=str(e))
        except Exception as e:
            return LayerResult(success=False, error=f"Tool '{tool_name}' error: {e}")

    # ── No-Op (for AI chat responses) ───────────────────────

    def _noop(self, action: dict) -> LayerResult:
        """No-operation — used for AI chat nodes."""
        return LayerResult(success=True, output=action.get("message", "noop"))
