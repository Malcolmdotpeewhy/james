"""
JAMES Layer 2 — Application-Level Integration

Interfaces with software ecosystems:
  - HTTP/REST API calls
  - CLI tool invocation with output capture
  - Playwright browser automation bridge (lazy)
  - Existing LCU API handler integration
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Any, Optional

from james.layers import ControlLayer, LayerLevel, LayerResult

logger = logging.getLogger("james.layers.application")


class ApplicationLayer(ControlLayer):
    """
    Layer 2: Application-level integration.
    Higher latency than native, but richer interaction.
    """

    level = LayerLevel.APPLICATION
    name = "application_integration"
    description = "HTTP APIs, CLI tools, browser automation, LCU integration"

    def execute(self, action: dict) -> LayerResult:
        """
        Execute an application-level action.

        Supported action types:
            - "http":       Make an HTTP request
            - "cli":        Run a CLI tool and capture output
            - "browser":    Playwright browser action (lazy)
            - "lcu_api":    League Client API call (via services.api_handler)
        """
        action_type = action.get("type", "")
        dispatch = {
            "http": self._http_request,
            "cli": self._cli_invoke,
            "browser": self._browser_action,
            "lcu_api": self._lcu_api_call,
        }

        handler = dispatch.get(action_type)
        if not handler:
            return LayerResult(
                success=False,
                error=f"Unknown application action type: {action_type}",
            )

        start = time.perf_counter()
        try:
            result = handler(action)
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            logger.error(f"Application layer error in {action_type}: {e}")
            return LayerResult(success=False, error=str(e), duration_ms=duration)

    def is_available(self) -> bool:
        """Application layer is available if we can import requests or urllib."""
        try:
            import urllib.request  # noqa: F401
            return True
        except ImportError:
            return False

    # ── HTTP Requests ────────────────────────────────────────────

    def _http_request(self, action: dict) -> LayerResult:
        """Make an HTTP request using requests (preferred) or urllib fallback."""
        url = action.get("target", "")
        method = action.get("method", "GET").upper()
        headers = action.get("headers", {})
        body = action.get("body")
        timeout = action.get("timeout", 30)
        verify_ssl = action.get("verify_ssl", True)

        # Try requests library first
        try:
            import requests
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                data=json.dumps(body) if isinstance(body, dict) else body,
                timeout=timeout,
                verify=verify_ssl,
            )
            return LayerResult(
                success=200 <= resp.status_code < 400,
                output={
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": resp.text[:10000],  # Cap output size
                },
                error=f"HTTP {resp.status_code}" if resp.status_code >= 400 else None,
            )
        except ImportError:
            pass

        # Fallback to urllib
        import urllib.request
        import urllib.error
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            if body:
                req.data = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body_text = resp.read().decode("utf-8", errors="replace")
                return LayerResult(
                    success=True,
                    output={
                        "status_code": resp.status,
                        "headers": dict(resp.headers),
                        "body": body_text[:10000],
                    },
                )
        except urllib.error.HTTPError as e:
            return LayerResult(
                success=False,
                output={"status_code": e.code},
                error=f"HTTP {e.code}: {e.reason}",
            )

    # ── CLI Tool Invocation ──────────────────────────────────────

    def _cli_invoke(self, action: dict) -> LayerResult:
        """Run a CLI tool and capture its output."""
        cmd = action.get("target", "")
        args = action.get("args", [])
        timeout = action.get("timeout", 60)
        cwd = action.get("cwd")

        if isinstance(cmd, str) and not args:
            # Shell mode for string commands
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=cwd,
            )
        else:
            # Direct mode with args list
            full_cmd = [cmd] + args if isinstance(cmd, str) else cmd
            result = subprocess.run(
                full_cmd, capture_output=True, text=True,
                timeout=timeout, cwd=cwd,
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

    # ── Browser Automation ───────────────────────────────────────

    def _browser_action(self, action: dict) -> LayerResult:
        """Playwright browser automation (lazy import)."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return LayerResult(
                success=False,
                error="Playwright not installed. Install with: pip install playwright && playwright install",
            )

        url = action.get("target", "")
        browser_action = action.get("browser_action", "screenshot")  # screenshot, content, click
        selector = action.get("selector")
        timeout = action.get("timeout", 30000)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=timeout)

                if browser_action == "screenshot":
                    path = action.get("output_path", "james_screenshot.png")
                    page.screenshot(path=path)
                    output = {"screenshot_path": path}
                elif browser_action == "content":
                    output = {"html": page.content()[:50000]}
                elif browser_action == "click" and selector:
                    page.click(selector, timeout=timeout)
                    output = {"clicked": selector}
                else:
                    output = {"title": page.title()}

                browser.close()
                return LayerResult(success=True, output=output)
        except Exception as e:
            return LayerResult(success=False, error=f"Browser action failed: {e}")

    # ── LCU API Integration ──────────────────────────────────────

    def _lcu_api_call(self, action: dict) -> LayerResult:
        """
        League Client Update API call.
        Bridges to the existing services.api_handler if available.
        """
        try:
            from services.api_handler import LCUHandler
        except ImportError:
            return LayerResult(
                success=False,
                error="LCU API handler not available (services.api_handler not in path)",
            )

        endpoint = action.get("target", "")
        method = action.get("method", "GET")

        try:
            handler = LCUHandler()
            if method.upper() == "GET":
                resp = handler.get(endpoint)
            elif method.upper() == "POST":
                resp = handler.post(endpoint, data=action.get("body", {}))
            elif method.upper() == "PUT":
                resp = handler.put(endpoint, data=action.get("body", {}))
            else:
                return LayerResult(success=False, error=f"Unsupported LCU method: {method}")

            return LayerResult(success=True, output=resp)
        except Exception as e:
            return LayerResult(success=False, error=f"LCU API call failed: {e}")
