"""
JAMES Security & Integrity Layer

Full audit logging, operation classification,
confirmation gates, file versioning, and
self-evolution boundary enforcement.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


class OpClass(Enum):
    """Operation safety classification."""
    SAFE = "safe"
    DESTRUCTIVE = "destructive"
    SYSTEM_LEVEL = "system_level"
    PRODUCTION = "production"


class EvolutionBoundary(Enum):
    """Self-evolution permission classification."""
    ALLOWED = "allowed"
    RESTRICTED = "restricted"

class Role(Enum):
    """User/Execution Authorization Roles for RBAC."""
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"

# ── Destructive operation keywords ──────────────────────────────

_DESTRUCTIVE_KEYWORDS = {
    "rm -rf", "rmdir /s", "del /f", "format", "fdisk",
    "Remove-Item -Recurse -Force", "Clear-Content",
    "DROP TABLE", "DROP DATABASE", "TRUNCATE",
    "reg delete", "bcdedit", "diskpart",
}

_SYSTEM_KEYWORDS = {
    "net stop", "net start", "sc config", "sc delete",
    "Set-Service", "Stop-Service", "Restart-Service",
    "reg add", "regedit", "schtasks",
    "netsh", "wmic", "bcdedit",
    "Set-ExecutionPolicy", "Enable-WindowsOptionalFeature",
}

_PRODUCTION_KEYWORDS = {
    "deploy", "publish", "release", "push --force",
    "git push origin main", "git push origin master",
    "docker push", "kubectl apply",
}


@dataclass
class AuditEntry:
    """Single audit log entry."""
    operation: str
    classification: OpClass
    timestamp: float = field(default_factory=time.time)
    node_id: str = ""
    details: str = ""
    approved: bool = True
    user_confirmed: bool = False


class SecurityPolicy:
    """
    Reads policy from .antigravity/config.yaml and enforces
    operation classification + confirmation gates.
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config: dict = {}
        self._config_path = config_path
        self.default_role = Role.ADMIN
        if config_path and os.path.isfile(config_path):
            self._load_config(config_path)

    def _load_config(self, path: str) -> None:
        """Load YAML config, falling back to safe defaults."""
        try:
            if _HAS_YAML:
                with open(path, "r", encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}
            else:
                # Minimal YAML-less fallback: assume strict mode
                self._config = {
                    "safety": {
                        "destructive_ops": {"require_confirmation": True},
                        "production_ops": {"require_confirmation": True},
                    }
                }
        except Exception:
            self._config = {}

    @property
    def destructive_requires_confirmation(self) -> bool:
        return (
            self._config
            .get("safety", {})
            .get("destructive_ops", {})
            .get("require_confirmation", True)
        )

    @property
    def production_requires_confirmation(self) -> bool:
        return (
            self._config
            .get("safety", {})
            .get("production_ops", {})
            .get("require_confirmation", True)
        )

    def classify_operation(self, command: str) -> OpClass:
        """Classify a command string by safety level."""
        cmd_lower = command.lower()

        for kw in _DESTRUCTIVE_KEYWORDS:
            if kw.lower() in cmd_lower:
                return OpClass.DESTRUCTIVE

        for kw in _PRODUCTION_KEYWORDS:
            if kw.lower() in cmd_lower:
                return OpClass.PRODUCTION

        for kw in _SYSTEM_KEYWORDS:
            if kw.lower() in cmd_lower:
                return OpClass.SYSTEM_LEVEL

        return OpClass.SAFE

    def is_permitted(self, op_class: OpClass, role: Optional[Role] = None) -> bool:
        """Check if a role is permitted to execute an operation class."""
        current_role = role or self.default_role
        
        if current_role == Role.ADMIN:
            return True
        elif current_role == Role.READONLY:
            return op_class == OpClass.SAFE
        elif current_role == Role.USER:
            # Users can run SAFE and SYSTEM, but not DESTRUCTIVE or PRODUCTION natively
            return op_class not in (OpClass.DESTRUCTIVE, OpClass.PRODUCTION)
            
        return False

    def requires_confirmation(self, op_class: OpClass, role: Optional[Role] = None) -> bool:
        """Check if an operation class requires user confirmation based on role."""
        current_role = role or self.default_role
        
        if current_role == Role.READONLY:
            # Readonly cannot run risky tasks EVEN with confirmation
            return op_class != OpClass.SAFE

        if op_class == OpClass.DESTRUCTIVE:
            return self.destructive_requires_confirmation
        if op_class == OpClass.PRODUCTION:
            return self.production_requires_confirmation
        if op_class == OpClass.SYSTEM_LEVEL:
            return self.destructive_requires_confirmation  # Same gate
        return False

    @staticmethod
    def classify_evolution(action: str) -> EvolutionBoundary:
        """
        Classify a self-evolution action.
        Allowed: skill creation/modification, execution optimization, tool generation
        Restricted: disabling safety, privilege escalation, kernel manipulation
        """
        action_lower = action.lower()

        restricted_patterns = [
            "disable safety", "disable security", "disable audit",
            "privilege escalation", "escalate privilege",
            "kernel", "driver", "ring0", "ntoskrnl",
            "bypass", "override security",
        ]
        for pattern in restricted_patterns:
            if pattern in action_lower:
                return EvolutionBoundary.RESTRICTED

        return EvolutionBoundary.ALLOWED


class AuditLog:
    """
    Append-only audit log stored as JSON Lines.
    Every operation JAMES executes is recorded here.
    """

    def __init__(self, log_path: str):
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._cached_count: Optional[int] = None

    def record(self, entry: AuditEntry) -> AuditEntry:
        """Record an operation to the audit log."""
        line = json.dumps({
            "ts": entry.timestamp,
            "op": entry.operation,
            "class": entry.classification.value,
            "node": entry.node_id,
            "details": entry.details,
            "approved": entry.approved,
            "confirmed": entry.user_confirmed,
        }, separators=(",", ":"))

        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        if self._cached_count is not None:
            self._cached_count += 1

        return entry

    def read_recent(self, count: int = 50) -> list[dict]:
        """Read the most recent N audit entries."""
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines[-count:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    @property
    def entry_count(self) -> int:
        """Total number of audit entries."""
        if not self._path.exists():
            return 0

        # ⚡ Bolt: Prevent O(N) memory allocation and file reads during status polling
        if self._cached_count is None:
            with open(self._path, "rb") as f:
                self._cached_count = sum(1 for _ in f)

        return self._cached_count


class RestorePointManager:
    """
    File versioning via restore points.
    Creates snapshots of files before modification.
    """

    def __init__(self, restore_dir: str):
        self._dir = Path(restore_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def create_restore_point(self, file_path: str, label: str = "") -> Optional[str]:
        """
        Create a restore point for a file.
        Returns the restore point path, or None if file doesn't exist.
        """
        src = Path(file_path)
        if not src.exists():
            return None

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_name = src.name.replace(" ", "_")
        suffix = f"_{label}" if label else ""
        restore_name = f"{timestamp}{suffix}_{safe_name}"
        dest = self._dir / restore_name

        shutil.copy2(str(src), str(dest))
        return str(dest)

    def restore(self, restore_point_path: str, target_path: str) -> bool:
        """Restore a file from a restore point."""
        rp = Path(restore_point_path)
        if not rp.exists():
            return False
        shutil.copy2(str(rp), target_path)
        return True

    def list_restore_points(self, limit: int = 20) -> list[dict]:
        """List available restore points."""
        points = []
        for f in sorted(self._dir.iterdir(), reverse=True)[:limit]:
            if f.is_file():
                points.append({
                    "path": str(f),
                    "name": f.name,
                    "size": f.stat().st_size,
                    "created": f.stat().st_ctime,
                })
        return points
