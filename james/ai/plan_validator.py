"""
JAMES Plan Validator — Pre-flight verification of AI-generated execution plans.

Checks:
  - Tool existence (tool_call targets must be registered)
  - Dangerous command blocking (rm -rf, format, shutdown, etc.)
  - Layer auto-correction (tool_call always uses layer 1)
  - Required kwargs enforcement
  - Path traversal detection in file operations
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("james.ai.plan_validator")


@dataclass
class ValidationResult:
    """Result of validating an AI-generated plan."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    corrected_plan: dict = field(default_factory=dict)
    corrections_applied: int = 0


class PlanValidator:
    """
    Validates AI-generated execution plans before execution.

    Three-pass validation:
      1. Structural: required fields, correct types
      2. Safety: blocked commands, path traversal, privilege escalation
      3. Semantic: tool existence, parameter validity, layer correctness
    """

    # Commands that should NEVER be executed without explicit user confirmation
    DANGEROUS_PATTERNS = [
        r"rm\s+-r[f]?\s+/",                         # rm -rf /
        r"del\s+/[sfq]",                             # del /s /f /q
        r"format\s+[a-zA-Z]:",                       # format C:
        r"shutdown\s+/[srfa]",                       # shutdown /s /r
        r":\(\)\s*{\s*:\s*\|\s*:\s*&\s*}\s*;",      # fork bomb
        r">\s*/dev/sd",                               # overwrite disk
        r"mkfs\.",                                    # make filesystem
        r"dd\s+if=",                                  # raw disk write
        r"reg\s+delete\s+HK[LU]M",                  # registry delete
        r"net\s+user\s+.+\s+/delete",               # delete user account
        r"cipher\s+/w:",                              # secure wipe
        r"diskpart",                                  # disk partitioning
        r"bcdedit",                                   # boot config edit
        r"sfc\s+/scannow",                           # system file checker (benign but needs admin)
    ]

    # File paths that should never be targeted
    BLOCKED_PATHS = [
        r"C:\\Windows\\System32\\config",
        r"C:\\Windows\\System32\\drivers",
        r"/etc/shadow",
        r"/etc/passwd",
        r"\\\.ssh\\",
        r"\\\.gnupg\\",
    ]

    # Action types that must always use layer 1
    LAYER_1_TYPES = {"tool_call", "noop", "command", "powershell",
                     "file_read", "file_write", "file_list",
                     "file_exists", "file_delete"}

    def __init__(self, tool_registry=None, security_policy=None):
        self._tools = tool_registry
        self._security = security_policy
        self._tool_names: Optional[set[str]] = None

    @property
    def tool_names(self) -> set[str]:
        """Lazily load the set of registered tool names."""
        if self._tool_names is None and self._tools:
            self._tool_names = {t["name"] for t in self._tools.list_tools()}
        return self._tool_names or set()

    def _check_safety(
        self,
        action_type: str,
        target: str,
        kwargs: Any,
        step_label: str,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """Pass 2: Safety checks."""
        # 2a. Dangerous command patterns
        if action_type in ("command", "powershell") and target:
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, target, re.IGNORECASE):
                    errors.append(
                        f"{step_label}: BLOCKED dangerous command matching "
                        f"pattern '{pattern}' in target: '{target[:80]}'"
                    )
                    break

        # 2b. Blocked file paths
        if action_type in ("file_read", "file_write", "file_delete") and target:
            for path_pattern in self.BLOCKED_PATHS:
                if re.search(path_pattern, target, re.IGNORECASE):
                    errors.append(
                        f"{step_label}: BLOCKED access to protected path: '{target[:80]}'"
                    )
                    break

        # 2c. Path traversal in kwargs
        if isinstance(kwargs, dict):
            for key, val in kwargs.items():
                if isinstance(val, str) and ".." in val:
                    warnings.append(
                        f"{step_label}: Potential path traversal in kwarg '{key}': '{val[:60]}'"
                    )

    def _check_semantics(
        self,
        step: dict,
        action: dict,
        action_type: str,
        target: str,
        step_label: str,
        i: int,
        errors: list[str],
        warnings: list[str],
    ) -> int:
        """Pass 3: Semantic checks."""
        corrections = 0

        # 3a. Tool existence
        if action_type == "tool_call" and target and self.tool_names:
            if target not in self.tool_names:
                # Try fuzzy match for helpful error message
                close = [t for t in self.tool_names if target in t or t in target]
                hint = f" Did you mean: {close[:3]}?" if close else ""
                errors.append(
                    f"{step_label}: Unknown tool '{target}'.{hint}"
                )

        # 3b. Layer auto-correction
        current_layer = step.get("layer")
        if action_type in self.LAYER_1_TYPES:
            if current_layer is not None and current_layer != 1:
                warnings.append(
                    f"{step_label}: '{action_type}' should use layer 1, got {current_layer}. Auto-correcting."
                )
                step["layer"] = 1
                corrections += 1
            elif current_layer is None:
                step["layer"] = 1
                corrections += 1

        # 3c. Missing kwargs for tool_call
        if action_type == "tool_call" and "kwargs" not in action:
            warnings.append(
                f"{step_label}: Missing 'kwargs' for tool_call. Adding empty dict."
            )
            action["kwargs"] = {}
            corrections += 1

        # 3d. Validate step has a name
        if not step.get("name"):
            step["name"] = f"step_{i + 1}"
            corrections += 1

        return corrections

    def validate(self, plan: dict) -> ValidationResult:
        """
        Run all validation passes on a plan. Returns ValidationResult.
        Auto-corrects minor issues (layer assignment, missing kwargs).
        """
        errors: list[str] = []
        warnings: list[str] = []
        corrections = 0

        steps = plan.get("steps", [])

        if not steps:
            errors.append("Plan has no steps.")
            return ValidationResult(
                valid=False,
                errors=errors,
                corrected_plan=plan,
            )

        for i, step in enumerate(steps):
            step_label = f"Step {i + 1} ('{step.get('name', 'unnamed')}')"
            action = step.get("action", {})

            if not isinstance(action, dict):
                errors.append(f"{step_label}: 'action' must be a dict, got {type(action).__name__}")
                continue

            action_type = action.get("type", "")
            target = action.get("target", "")

            # ── Pass 1: Structural checks ────────────────────
            if not action_type:
                errors.append(f"{step_label}: Missing 'action.type'")
                continue

            self._check_safety(action_type, target, action.get("kwargs", {}), step_label, errors, warnings)
            corrections += self._check_semantics(step, action, action_type, target, step_label, i, errors, warnings)

        is_valid = len(errors) == 0

        if errors:
            logger.warning(f"Plan validation FAILED with {len(errors)} errors")
            for e in errors:
                logger.warning(f"  ✗ {e}")
        if warnings:
            for w in warnings:
                logger.info(f"  ⚠ {w}")
        if corrections:
            logger.info(f"  Auto-corrected {corrections} issues")

        return ValidationResult(
            valid=is_valid,
            errors=errors,
            warnings=warnings,
            corrected_plan=plan,
            corrections_applied=corrections,
        )
