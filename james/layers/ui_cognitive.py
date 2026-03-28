"""
JAMES Layer 3 — UI Cognitive Interaction

Visual interpretation + input simulation:
  - PyAutoGUI screen interaction (lazy)
  - OpenCV template matching (lazy)
  - AutoHotkey script generation (lazy)
  - Screen capture and OCR pipeline

All imports are lazy — JAMES runs fine without these packages.
Layer reports unavailable if none are installed.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Optional

from james.layers import ControlLayer, LayerLevel, LayerResult

logger = logging.getLogger("james.layers.ui_cognitive")


def _has_pyautogui() -> bool:
    try:
        import pyautogui  # noqa: F401
        return True
    except ImportError:
        return False


def _has_opencv() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def _has_ahk() -> bool:
    try:
        import ahk  # noqa: F401
        return True
    except ImportError:
        # Check for standalone AutoHotkey.exe
        return os.path.isfile(r"C:\Program Files\AutoHotkey\v2\AutoHotkey.exe") or (
            os.path.isfile(r"C:\Program Files\AutoHotkey\AutoHotkey.exe")
        )


class UICognitiveLayer(ControlLayer):
    """
    Layer 3: Visual interpretation and input simulation.
    All dependencies are optional — graceful degradation.
    """

    level = LayerLevel.UI_COGNITIVE
    name = "ui_cognitive"
    description = "PyAutoGUI, OpenCV template matching, AutoHotkey scripting"

    def execute(self, action: dict) -> LayerResult:
        """
        Execute a UI cognitive action.

        Supported action types:
            - "click":          Click at coordinates or locate-and-click
            - "type":           Type text
            - "hotkey":         Send keyboard shortcut
            - "screenshot":     Capture screenshot
            - "locate":         Find element on screen via template matching
            - "move_mouse":     Move mouse to coordinates
            - "ahk_script":     Run AutoHotkey script
        """
        action_type = action.get("type", "")
        dispatch = {
            "click": self._click,
            "type": self._type_text,
            "hotkey": self._hotkey,
            "screenshot": self._screenshot,
            "locate": self._locate,
            "move_mouse": self._move_mouse,
            "ahk_script": self._ahk_script,
        }

        handler = dispatch.get(action_type)
        if not handler:
            return LayerResult(
                success=False,
                error=f"Unknown UI cognitive action type: {action_type}",
            )

        start = time.perf_counter()
        try:
            result = handler(action)
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            logger.error(f"UI cognitive layer error in {action_type}: {e}")
            return LayerResult(success=False, error=str(e), duration_ms=duration)

    def is_available(self) -> bool:
        """Available if at least one UI automation tool is installed."""
        return _has_pyautogui() or _has_ahk()

    # ── PyAutoGUI Actions ────────────────────────────────────────

    def _click(self, action: dict) -> LayerResult:
        if not _has_pyautogui():
            return LayerResult(success=False, error="pyautogui not installed")
        import pyautogui

        x = action.get("x")
        y = action.get("y")
        button = action.get("button", "left")
        clicks = action.get("clicks", 1)

        # If no coordinates, try to locate by image
        if x is None or y is None:
            template = action.get("target")
            if template and _has_opencv():
                loc = self._locate_internal(template)
                if loc:
                    x, y = loc
                else:
                    return LayerResult(success=False, error=f"Could not locate: {template}")
            else:
                return LayerResult(success=False, error="No coordinates or template provided")

        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        return LayerResult(success=True, output={"clicked": {"x": x, "y": y}})

    def _type_text(self, action: dict) -> LayerResult:
        if not _has_pyautogui():
            return LayerResult(success=False, error="pyautogui not installed")
        import pyautogui

        text = action.get("target", "")
        interval = action.get("interval", 0.02)
        pyautogui.typewrite(text, interval=interval)
        return LayerResult(success=True, output=f"Typed {len(text)} characters")

    def _hotkey(self, action: dict) -> LayerResult:
        if not _has_pyautogui():
            return LayerResult(success=False, error="pyautogui not installed")
        import pyautogui

        keys = action.get("target", "").split("+")
        pyautogui.hotkey(*keys)
        return LayerResult(success=True, output=f"Pressed: {'+'.join(keys)}")

    def _screenshot(self, action: dict) -> LayerResult:
        if not _has_pyautogui():
            return LayerResult(success=False, error="pyautogui not installed")
        import pyautogui

        path = action.get("target", "james_screenshot.png")
        region = action.get("region")  # (left, top, width, height)
        img = pyautogui.screenshot(region=region)
        img.save(path)
        return LayerResult(success=True, output={"path": path, "size": img.size})

    def _move_mouse(self, action: dict) -> LayerResult:
        if not _has_pyautogui():
            return LayerResult(success=False, error="pyautogui not installed")
        import pyautogui

        x = action.get("x", 0)
        y = action.get("y", 0)
        duration = action.get("duration", 0.25)
        pyautogui.moveTo(x, y, duration=duration)
        return LayerResult(success=True, output={"moved_to": {"x": x, "y": y}})

    # ── OpenCV Template Matching ─────────────────────────────────

    def _locate(self, action: dict) -> LayerResult:
        template_path = action.get("target", "")
        if not _has_opencv():
            return LayerResult(success=False, error="opencv-python not installed")

        loc = self._locate_internal(template_path)
        if loc:
            return LayerResult(success=True, output={"x": loc[0], "y": loc[1]})
        return LayerResult(success=False, error=f"Template not found on screen: {template_path}")

    def _locate_internal(self, template_path: str) -> Optional[tuple[int, int]]:
        """Internal: locate a template on screen. Returns (x, y) center or None."""
        if not _has_opencv() or not _has_pyautogui():
            return None

        import cv2
        import numpy as np
        import pyautogui

        # Capture screen
        screenshot = pyautogui.screenshot()
        screen = np.array(screenshot)
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY)

        # Load template
        if not os.path.isfile(template_path):
            return None
        template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            return None

        # Match
        result = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        threshold = 0.8
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            h, w = template.shape
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            return (center_x, center_y)

        return None

    # ── AutoHotkey ───────────────────────────────────────────────

    def _ahk_script(self, action: dict) -> LayerResult:
        """Run an AutoHotkey script."""
        script = action.get("target", "")
        if not script:
            return LayerResult(success=False, error="No AHK script provided")

        # Find AHK executable
        ahk_paths = [
            r"C:\Program Files\AutoHotkey\v2\AutoHotkey.exe",
            r"C:\Program Files\AutoHotkey\AutoHotkey.exe",
        ]
        ahk_exe = None
        for p in ahk_paths:
            if os.path.isfile(p):
                ahk_exe = p
                break

        if not ahk_exe:
            # Try ahk Python package
            try:
                import ahk
                a = ahk.AHK()
                a.run_script(script)
                return LayerResult(success=True, output="AHK script executed via python-ahk")
            except Exception as e:
                return LayerResult(success=False, error=f"AHK not available: {e}")

        # Write temp script and execute
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ahk', delete=False) as f:
            f.write(script)
            script_path = f.name

        try:
            result = subprocess.run(
                [ahk_exe, script_path],
                capture_output=True, text=True, timeout=30,
            )
            return LayerResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr.strip() if result.returncode != 0 else None,
            )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass
