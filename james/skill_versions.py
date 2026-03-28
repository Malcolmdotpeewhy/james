"""
JAMES Skill Versioning — Track versions of learned skills with rollback.

Every time a skill is updated, the previous version is archived.
Skills can be rolled back to any previous version.

Storage:
  - Each skill version is stored as a JSON file in skills/.versions/
  - Format: {skill_name}__v{N}.json
  - Metadata tracks version history, author, and change description
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("james.skill_versions")


class SkillVersion:
    """A single skill version snapshot."""

    def __init__(self, version: int, skill_data: dict,
                 description: str = "", timestamp: float = None):
        self.version = version
        self.skill_data = skill_data
        self.description = description
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "skill_data": self.skill_data,
            "description": self.description,
            "timestamp": self.timestamp,
        }


class SkillVersionManager:
    """
    Manage versioned snapshots of skills.

    Automatically archives previous versions when skills are updated.
    Supports rollback to any previous version.
    """

    def __init__(self, versions_dir: str):
        self._versions_dir = versions_dir
        os.makedirs(versions_dir, exist_ok=True)
        self._version_counts: dict[str, int] = {}
        self._load_version_counts()

    def _load_version_counts(self) -> None:
        """Scan versions directory to determine current version numbers."""
        if not os.path.isdir(self._versions_dir):
            return

        for f in os.listdir(self._versions_dir):
            if f.endswith(".json") and "__v" in f:
                parts = f.rsplit("__v", 1)
                if len(parts) == 2:
                    skill_name = parts[0]
                    try:
                        version = int(parts[1].replace(".json", ""))
                        current = self._version_counts.get(skill_name, 0)
                        self._version_counts[skill_name] = max(current, version)
                    except ValueError:
                        pass

    # ── Core Operations ──────────────────────────────────────────

    def save_version(self, skill_name: str, skill_data: dict,
                     description: str = "") -> int:
        """
        Save a new version of a skill.

        Args:
            skill_name: Unique skill identifier.
            skill_data: Full skill data dict.
            description: What changed in this version.

        Returns:
            New version number.
        """
        current = self._version_counts.get(skill_name, 0)
        new_version = current + 1

        sv = SkillVersion(
            version=new_version,
            skill_data=skill_data,
            description=description,
        )

        # Write version file
        filename = f"{skill_name}__v{new_version}.json"
        filepath = os.path.join(self._versions_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(sv.to_dict(), f, indent=2, default=str)
            self._version_counts[skill_name] = new_version
            logger.info(f"Skill '{skill_name}' saved as v{new_version}")
            return new_version
        except Exception as e:
            logger.error(f"Failed to save skill version: {e}")
            raise

    def get_version(self, skill_name: str,
                    version: int = None) -> Optional[SkillVersion]:
        """
        Get a specific version of a skill.

        Args:
            skill_name: Skill identifier.
            version: Version number (default: latest).

        Returns:
            SkillVersion or None.
        """
        if version is None:
            version = self._version_counts.get(skill_name, 0)

        if version == 0:
            return None

        filename = f"{skill_name}__v{version}.json"
        filepath = os.path.join(self._versions_dir, filename)

        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return SkillVersion(
                version=data["version"],
                skill_data=data["skill_data"],
                description=data.get("description", ""),
                timestamp=data.get("timestamp", 0),
            )
        except Exception as e:
            logger.error(f"Failed to load skill version: {e}")
            return None

    def rollback(self, skill_name: str, target_version: int) -> Optional[dict]:
        """
        Roll back a skill to a previous version.

        Args:
            skill_name: Skill identifier.
            target_version: Version to restore.

        Returns:
            The restored skill_data, or None if failed.
        """
        sv = self.get_version(skill_name, target_version)
        if sv is None:
            logger.warning(f"Version {target_version} not found for '{skill_name}'")
            return None

        # Save the rollback as a new version
        new_v = self.save_version(
            skill_name,
            sv.skill_data,
            description=f"Rollback to v{target_version}",
        )
        logger.info(f"Skill '{skill_name}' rolled back to v{target_version} (saved as v{new_v})")
        return sv.skill_data

    def get_history(self, skill_name: str) -> list[dict]:
        """Get all versions of a skill."""
        versions = []
        max_v = self._version_counts.get(skill_name, 0)

        for v in range(1, max_v + 1):
            sv = self.get_version(skill_name, v)
            if sv:
                versions.append({
                    "version": sv.version,
                    "description": sv.description,
                    "timestamp": sv.timestamp,
                })

        return versions

    def get_current_version(self, skill_name: str) -> int:
        """Get the current version number of a skill."""
        return self._version_counts.get(skill_name, 0)

    def list_versioned_skills(self) -> list[dict]:
        """List all skills that have version history."""
        return [
            {"name": name, "current_version": version}
            for name, version in sorted(self._version_counts.items())
        ]

    def delete_versions(self, skill_name: str) -> int:
        """Delete all versions of a skill."""
        deleted = 0
        max_v = self._version_counts.get(skill_name, 0)

        for v in range(1, max_v + 1):
            filepath = os.path.join(self._versions_dir, f"{skill_name}__v{v}.json")
            if os.path.exists(filepath):
                os.remove(filepath)
                deleted += 1

        self._version_counts.pop(skill_name, None)
        return deleted

    # ── Status ───────────────────────────────────────────────────

    def status(self) -> dict:
        total_versions = sum(self._version_counts.values())
        return {
            "versioned_skills": len(self._version_counts),
            "total_versions": total_versions,
            "versions_dir": self._versions_dir,
        }
