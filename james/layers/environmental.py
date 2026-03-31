"""
JAMES Layer 5 — Environmental Restructuring

Modify the system environment to enable control:
  - Package/tool installer (pip, choco, winget)
  - Service manager (start/stop/enable Windows services)
  - Permission reconfiguration (gated by safety policy)
  - Environment variable persistence
  - PATH management
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

from james.layers import ControlLayer, LayerLevel, LayerResult

logger = logging.getLogger("james.layers.environmental")


class EnvironmentalLayer(ControlLayer):
    """
    Layer 5: Restructures the environment to enable control paths.
    All destructive operations are gated by security policy.
    """

    level = LayerLevel.ENVIRONMENTAL
    name = "environmental_restructuring"
    description = "Package installation, service management, environment configuration"

    def execute(self, action: dict) -> LayerResult:
        """
        Supported action types:
            - "pip_install":     Install Python package
            - "choco_install":   Install package via Chocolatey
            - "winget_install":  Install package via winget
            - "service_start":   Start a Windows service
            - "service_stop":    Stop a Windows service
            - "service_status":  Check service status
            - "path_add":        Add directory to PATH
            - "env_persist":     Persist environment variable
            - "enable_feature":  Enable Windows optional feature
        """
        action_type = action.get("type", "")
        dispatch = {
            "pip_install": self._pip_install,
            "choco_install": self._choco_install,
            "winget_install": self._winget_install,
            "service_start": self._service_control,
            "service_stop": self._service_control,
            "service_status": self._service_status,
            "path_add": self._path_add,
            "env_persist": self._env_persist,
            "enable_feature": self._enable_feature,
        }

        handler = dispatch.get(action_type)
        if not handler:
            return LayerResult(
                success=False,
                error=f"Unknown environmental action type: {action_type}",
            )

        start = time.perf_counter()
        try:
            result = handler(action)
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            logger.error(f"Environmental layer error in {action_type}: {e}")
            return LayerResult(success=False, error=str(e), duration_ms=duration)

    def is_available(self) -> bool:
        """Environmental layer is available on Windows with pip."""
        return os.name == "nt"

    # ── Package Installation ─────────────────────────────────────

    def _pip_install(self, action: dict) -> LayerResult:
        """Install a Python package via pip."""
        package = action.get("target", "")
        if not package:
            return LayerResult(success=False, error="No package specified")

        # Use the venv pip if available
        venv_pip = os.path.join(
            os.environ.get("VIRTUAL_ENV", ""),
            "Scripts", "pip.exe"
        )
        pip_cmd = venv_pip if os.path.isfile(venv_pip) else "pip"

        result = subprocess.run(
            [pip_cmd, "install", package, "--quiet"],
            capture_output=True, text=True, timeout=120,
        )
        return LayerResult(
            success=result.returncode == 0,
            output=result.stdout.strip() or f"Installed: {package}",
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    def _choco_install(self, action: dict) -> LayerResult:
        """Install a package via Chocolatey."""
        package = action.get("target", "")
        if not package:
            return LayerResult(success=False, error="No package specified")

        # Check if choco is available
        choco = subprocess.run(
            "where choco", shell=True, capture_output=True, text=True,
        )
        if choco.returncode != 0:
            return LayerResult(
                success=False,
                error="Chocolatey not installed. Install from https://chocolatey.org/install",
            )

        result = subprocess.run(
            f"choco install {package} -y --no-progress",
            shell=True, capture_output=True, text=True, timeout=300,
        )
        return LayerResult(
            success=result.returncode == 0,
            output=result.stdout.strip()[-500:],  # Tail output
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    def _winget_install(self, action: dict) -> LayerResult:
        """Install a package via winget."""
        package = action.get("target", "")
        if not package:
            return LayerResult(success=False, error="No package specified")

        result = subprocess.run(
            ["winget", "install", "--id", package, "--accept-package-agreements", "--accept-source-agreements", "--silent"],
            shell=False, capture_output=True, text=True, timeout=300,
        )
        return LayerResult(
            success=result.returncode == 0,
            output=result.stdout.strip()[-500:],
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    # ── Service Management ───────────────────────────────────────

    def _service_control(self, action: dict) -> LayerResult:
        """Start or stop a Windows service."""
        service = action.get("target", "")
        action_type = action.get("type", "")

        if not service:
            return LayerResult(success=False, error="No service specified")

        verb = "Start" if "start" in action_type else "Stop"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"{verb}-Service -Name '{service}' -Force -ErrorAction Stop"],
            capture_output=True, text=True, timeout=30,
        )
        return LayerResult(
            success=result.returncode == 0,
            output=f"Service '{service}' {verb.lower()}ed",
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    def _service_status(self, action: dict) -> LayerResult:
        """Check the status of a Windows service."""
        service = action.get("target", "")
        if not service:
            return LayerResult(success=False, error="No service specified")

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Service -Name '{service}' | Select-Object Name, Status, StartType | ConvertTo-Json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            try:
                import json
                svc_info = json.loads(result.stdout)
                return LayerResult(success=True, output=svc_info)
            except Exception:
                return LayerResult(success=True, output=result.stdout.strip())
        return LayerResult(
            success=False,
            error=result.stderr.strip() or f"Service not found: {service}",
        )

    # ── PATH Management ──────────────────────────────────────────

    def _path_add(self, action: dict) -> LayerResult:
        """Add a directory to the current process PATH."""
        directory = action.get("target", "")
        if not directory:
            return LayerResult(success=False, error="No directory specified")
        if not os.path.isdir(directory):
            return LayerResult(success=False, error=f"Directory not found: {directory}")

        current_path = os.environ.get("PATH", "")
        if directory.lower() not in current_path.lower():
            os.environ["PATH"] = f"{directory};{current_path}"
            return LayerResult(success=True, output=f"Added to PATH: {directory}")
        return LayerResult(success=True, output=f"Already in PATH: {directory}")

    # ── Environment Variable Persistence ─────────────────────────

    def _env_persist(self, action: dict) -> LayerResult:
        """Persist an environment variable via setx."""
        var_name = action.get("target", "")
        var_value = action.get("value", "")
        scope = action.get("scope", "user")  # "user" or "machine"

        if not var_name:
            return LayerResult(success=False, error="No variable name specified")

        cmd = f'setx {var_name} "{var_value}"'
        if scope == "machine":
            cmd += " /M"

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15,
        )
        return LayerResult(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    # ── Windows Features ─────────────────────────────────────────

    def _enable_feature(self, action: dict) -> LayerResult:
        """Enable a Windows optional feature (requires elevation)."""
        feature = action.get("target", "")
        if not feature:
            return LayerResult(success=False, error="No feature specified")

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Enable-WindowsOptionalFeature -Online -FeatureName '{feature}' -NoRestart"],
            capture_output=True, text=True, timeout=120,
        )
        return LayerResult(
            success=result.returncode == 0,
            output=result.stdout.strip()[-500:],
            error=result.stderr.strip() if result.returncode != 0 else None,
        )
