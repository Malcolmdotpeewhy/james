"""
JAMES Output Guardrails — Multi-layer safety filtering.

Prevents:
  - Dangerous command execution (rm -rf, format drives, etc.)
  - System prompt leakage
  - Sensitive data exposure (passwords, API keys, SSNs)
  - Injection attacks
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("james.guardrails")


class GuardrailResult:
    """Result of a guardrail check."""

    __slots__ = ("allowed", "filtered_output", "violations", "warnings")

    def __init__(self):
        self.allowed: bool = True
        self.filtered_output: Any = None
        self.violations: list[str] = []
        self.warnings: list[str] = []


class OutputGuardrails:
    """
    Multi-layer output filtering for AI safety.

    Three filter stages:
      1. Command safety — block destructive system commands
      2. Prompt leak prevention — detect system prompt in output
      3. Sensitive data redaction — mask passwords, keys, SSNs, emails
    """

    # ── Stage 1: Dangerous command patterns ───────────────────
    BLOCKED_COMMANDS = [
        # Linux/Unix destructive
        (r"rm\s+-r[f]?\s+/(?!\w)", "recursive delete on root"),
        (r"rm\s+-rf\s+~", "recursive delete on home"),
        (r"mkfs\.\w+", "filesystem format"),
        (r"dd\s+if=.+of=/dev/", "disk overwrite"),
        (r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;:", "fork bomb"),
        (r">\s*/dev/sd[a-z]", "raw disk write"),
        (r"chmod\s+-R\s+777\s+/", "recursive permission change on root"),

        # Windows destructive
        (r"format\s+[a-zA-Z]:\s*/[yYqQ]", "disk format"),
        (r"del\s+/[sfq]\s+[a-zA-Z]:\\", "recursive file delete"),
        (r"rd\s+/[sq]\s+[a-zA-Z]:\\", "recursive dir delete"),
        (r"shutdown\s+/[srfa]", "system shutdown/restart"),
        (r"reg\s+delete\s+HK(LM|CU|CR)", "registry key delete"),
        (r"bcdedit\s+/delete", "boot config delete"),
        (r"net\s+user\s+\w+\s+/delete", "user account delete"),
        (r"cipher\s+/w:", "disk wipe"),
        (r"diskpart", "disk partition tool"),

        # Data destruction
        (r"DROP\s+(TABLE|DATABASE|SCHEMA)", "SQL drop"),
        (r"TRUNCATE\s+TABLE", "SQL truncate"),
        (r"DELETE\s+FROM\s+\w+\s*(;|$)", "SQL delete all rows"),
    ]

    # ── Stage 2: System prompt leak patterns ──────────────────
    PROMPT_LEAK_PATTERNS = [
        r"you\s+are\s+james",
        r"system\s+prompt",
        r"<\|system\|>",
        r"RESPONSE\s+FORMAT",
        r"FORMAT\s+[12]\s+[—–-]",
        r"STRICT\s+RULES",
        r"MEMORY\s+TOOL\s+EXACT\s+SIGNATURES",
        r"CRITICAL\s+MEMORY\s+RULE",
        r"YOUR\s+CAPABILITIES\s+\(\d+\s+registered\s+tools",
        r"_SYSTEM_PROMPT",
        r"REASONING\s+REQUIREMENT",
    ]

    # ── Stage 3: Sensitive data patterns to redact ────────────
    REDACT_PATTERNS = [
        # Email addresses
        (r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b",
         "[EMAIL_REDACTED]", "email_address"),
        # Social Security Numbers
        (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN_REDACTED]", "ssn"),
        # Credit card numbers (basic)
        (r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b",
         "[CC_REDACTED]", "credit_card"),
        # Passwords in key=value format
        (r"(?:password|passwd|pwd|pass)\s*[:=]\s*['\"]?(\S+)['\"]?",
         r"password=[REDACTED]", "password"),
        # API keys and tokens
        (r"(?:api[_\-]?key|secret[_\-]?key|access[_\-]?token|auth[_\-]?token|bearer)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{16,})['\"]?",
         r"\g<0>".replace(r"\g<0>", "[API_KEY_REDACTED]"), "api_key"),
        # AWS keys
        (r"AKIA[0-9A-Z]{16}", "[AWS_KEY_REDACTED]", "aws_key"),
        # Private keys
        (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "[PRIVATE_KEY_REDACTED]", "private_key"),
    ]

    def __init__(self, redact_sensitive: bool = True, block_dangerous: bool = True,
                 prevent_leaks: bool = True):
        self.redact_sensitive = redact_sensitive
        self.block_dangerous = block_dangerous
        self.prevent_leaks = prevent_leaks

    def check(self, output: dict) -> GuardrailResult:
        """
        Apply all guardrails to AI output dict.

        Handles both chat responses and execution plans.
        Returns GuardrailResult with filtered output.
        """
        result = GuardrailResult()
        output = dict(output)  # don't mutate original

        # ── Chat message filtering ────────────────────────
        if output.get("type") == "chat":
            msg = output.get("message", "")
            msg, violations = self._filter_text(msg)
            output["message"] = msg
            result.violations.extend(violations)

        # ── Plan step filtering ───────────────────────────
        if "steps" in output:
            output["steps"], step_violations = self._filter_steps(output["steps"])
            result.violations.extend(step_violations)

        # ── Single action filtering (bare tool_call) ──────
        if output.get("type") == "tool_call":
            target = output.get("target", "")
            blocked, reason = self._check_command_safety(target)
            if blocked:
                result.violations.append(f"Blocked dangerous target: {reason}")
                output["target"] = f"[BLOCKED:{reason}]"

        result.allowed = len(result.violations) == 0
        result.filtered_output = output
        return result

    def _filter_text(self, text: str) -> tuple[str, list[str]]:
        """Filter chat message text. Returns (filtered_text, violations)."""
        violations = []

        # Stage 2: Prompt leak detection
        if self.prevent_leaks:
            for pattern in self.PROMPT_LEAK_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(f"Prompt leak detected: {pattern[:40]}")
                    text = "[Content filtered: I can't share internal system details.]"
                    return text, violations

        # Stage 3: Sensitive data redaction
        if self.redact_sensitive:
            for pattern, replacement, data_type in self.REDACT_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
                    violations.append(f"Redacted {data_type}")

        return text, violations

    def _filter_steps(self, steps: list) -> tuple[list, list[str]]:
        """Filter execution plan steps. Returns (filtered_steps, violations)."""
        violations = []
        filtered = []

        for i, step in enumerate(steps):
            step = dict(step)  # copy
            action = step.get("action", {})
            action_type = action.get("type", "")
            target = action.get("target", "")

            # Check command targets for danger
            if action_type in ("command", "tool_call"):
                blocked, reason = self._check_command_safety(target)
                if blocked:
                    violations.append(f"Step {i+1}: Blocked '{target[:50]}' — {reason}")
                    action = dict(action)
                    action["target"] = f"[BLOCKED:{reason}]"
                    action["_original_target"] = target
                    step["action"] = action
                    step["_blocked"] = True

            # Auto-correct layer for tool_call
            if action_type == "tool_call" and step.get("layer", 1) != 1:
                step["layer"] = 1

            # Check kwargs for sensitive data
            kwargs = action.get("kwargs", {})
            if isinstance(kwargs, dict) and self.redact_sensitive:
                for k, v in kwargs.items():
                    if isinstance(v, str):
                        for pattern, replacement, data_type in self.REDACT_PATTERNS:
                            if re.search(pattern, v, re.IGNORECASE):
                                # Don't redact in kwargs — just warn
                                violations.append(
                                    f"Step {i+1}: kwargs.{k} contains {data_type}"
                                )

            filtered.append(step)

        return filtered, violations

    def _check_command_safety(self, target: str) -> tuple[bool, str]:
        """Check if a command target is dangerous. Returns (blocked, reason)."""
        if not target or not self.block_dangerous:
            return False, ""

        for pattern, reason in self.BLOCKED_COMMANDS:
            if re.search(pattern, target, re.IGNORECASE):
                logger.warning(f"Guardrail BLOCKED: '{target[:60]}' — {reason}")
                return True, reason

        return False, ""

    def filter_synthesis(self, text: str) -> str:
        """Filter synthesized output text (lighter check — no plan steps)."""
        filtered, _ = self._filter_text(text)
        return filtered
