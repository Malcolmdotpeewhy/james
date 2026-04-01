"""
JAMES Plugin Architecture — Dynamic loading of external capability plugins.

Plugins are directories under james/plugins/ with a manifest.json:
  {
    "name": "my_plugin",
    "version": "1.0",
    "description": "Does something cool",
    "entry": "main.py",
    "tools": ["tool_a", "tool_b"],
    "dependencies": ["requests"]
  }

Each plugin's entry file must expose:
  - register(registry): Called on load to register tools
  - unregister(registry): Called on unload (optional)
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("james.plugins")


class PluginInfo:
    """Metadata for a loaded plugin."""

    def __init__(self, path: str, manifest: dict[str, Any], default_name: str):
        self.name = manifest.get("name", default_name)
        self.version = manifest.get("version", "0.0")
        self.description = manifest.get("description", "")
        self.path = path
        self.tools = manifest.get("tools", [])
        self.dependencies = manifest.get("dependencies", [])
        self.loaded = False
        self.module = None
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "loaded": self.loaded,
            "tools": self.tools,
            "dependencies": self.dependencies,
            "error": self.error,
        }


class PluginManager:
    """
    Discover, load, and manage capability plugins.

    Scans the plugins directory for plugin folders containing
    manifest.json, validates them, and loads their entry modules.
    """

    def __init__(self, plugins_dir: str, tool_registry=None):
        self._plugins_dir = plugins_dir
        self._registry = tool_registry
        self._plugins: dict[str, PluginInfo] = {}
        os.makedirs(plugins_dir, exist_ok=True)

    # ── Discovery ────────────────────────────────────────────────

    def discover(self) -> list[PluginInfo]:
        """
        Scan the plugins directory for available plugins.

        Returns list of discovered PluginInfo objects.
        """
        discovered = []

        if not os.path.isdir(self._plugins_dir):
            return discovered

        for item in os.listdir(self._plugins_dir):
            plugin_dir = os.path.join(self._plugins_dir, item)
            if not os.path.isdir(plugin_dir):
                continue

            manifest_path = os.path.join(plugin_dir, "manifest.json")
            if not os.path.exists(manifest_path):
                continue

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                info = PluginInfo(
                    path=plugin_dir,
                    manifest=manifest,
                    default_name=item,
                )
                discovered.append(info)
                self._plugins[info.name] = info
                logger.debug(f"Discovered plugin: {info.name} v{info.version}")

            except Exception as e:
                logger.warning(f"Invalid plugin at {plugin_dir}: {e}")

        return discovered

    # ── Loading ──────────────────────────────────────────────────

    def load(self, name: str) -> dict:
        """
        Load and activate a plugin by name.

        Returns:
            {status, name, tools_registered, error}
        """
        info = self._plugins.get(name)
        if not info:
            return {"status": "error", "error": f"Plugin '{name}' not found"}

        if info.loaded:
            return {"status": "already_loaded", "name": name}

        # Check dependencies
        missing_deps = self._check_dependencies(info.dependencies)
        if missing_deps:
            info.error = f"Missing dependencies: {missing_deps}"
            return {
                "status": "error",
                "error": info.error,
                "missing": missing_deps,
            }

        # Load the entry module
        manifest_path = os.path.join(info.path, "manifest.json")
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
        except Exception as e:
            info.error = f"Cannot read manifest: {e}"
            return {"status": "error", "error": info.error}

        entry_file = manifest.get("entry", "main.py")
        entry_path = os.path.join(info.path, entry_file)

        if not os.path.exists(entry_path):
            info.error = f"Entry file not found: {entry_file}"
            return {"status": "error", "error": info.error}

        try:
            spec = importlib.util.spec_from_file_location(
                f"james.plugins.{name}", entry_path
            )
            if not spec or not spec.loader:
                info.error = "Failed to create module spec"
                return {"status": "error", "error": info.error}

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            info.module = module

            # Call register() if available
            tools_registered = 0
            if hasattr(module, "register") and self._registry:
                result = module.register(self._registry)
                if isinstance(result, int):
                    tools_registered = result
                elif isinstance(result, list):
                    tools_registered = len(result)

            info.loaded = True
            info.error = None
            logger.info(f"Plugin '{name}' loaded ({tools_registered} tools)")

            return {
                "status": "loaded",
                "name": name,
                "version": info.version,
                "tools_registered": tools_registered,
            }

        except Exception as e:
            info.error = f"Load error: {e}"
            logger.error(f"Failed to load plugin '{name}': {e}")
            return {"status": "error", "error": info.error}

    def unload(self, name: str) -> dict:
        """Unload a plugin."""
        info = self._plugins.get(name)
        if not info:
            return {"status": "error", "error": f"Plugin '{name}' not found"}

        if not info.loaded:
            return {"status": "not_loaded", "name": name}

        # Call unregister() if available
        if info.module and hasattr(info.module, "unregister") and self._registry:
            try:
                info.module.unregister(self._registry)
            except Exception as e:
                logger.warning(f"Plugin '{name}' unregister error: {e}")

        info.loaded = False
        info.module = None
        logger.info(f"Plugin '{name}' unloaded")
        return {"status": "unloaded", "name": name}

    def load_all(self) -> dict:
        """Discover and load all available plugins."""
        self.discover()
        results = {}
        for name in self._plugins:
            results[name] = self.load(name)
        return results

    # ── Info ─────────────────────────────────────────────────────

    def list_plugins(self) -> list[dict]:
        """List all discovered plugins."""
        return [info.to_dict() for info in self._plugins.values()]

    def get_plugin(self, name: str) -> Optional[dict]:
        """Get info about a specific plugin."""
        info = self._plugins.get(name)
        return info.to_dict() if info else None

    def _check_dependencies(self, deps: list[str]) -> list[str]:
        """Check which dependencies are missing."""
        missing = []
        for dep in deps:
            try:
                __import__(dep)
            except ImportError:
                missing.append(dep)
        return missing

    # ── Status ───────────────────────────────────────────────────

    def status(self) -> dict:
        loaded_count = 0
        for p in self._plugins.values():
            if p.loaded:
                loaded_count += 1
        return {
            "plugins_dir": self._plugins_dir,
            "total": len(self._plugins),
            "loaded": loaded_count,
            "plugins": self.list_plugins(),
        }
