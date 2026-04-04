"""
JAMES Tool Registry — Callable tool functions for the orchestrator.

Tools are Python functions that the AI can invoke directly (zero-subprocess overhead).
Each tool is registered with a name, description, and parameter schema for the AI.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import socket
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import request as urllib_request
from urllib.error import URLError

logger = logging.getLogger("james.tools")

_registry_instance = None
_ACTIVE_MEMORY = None


class ToolRegistry:
    """Registry of callable tools available to JAMES."""

    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._register_builtins()

    def set_memory(self, memory_store) -> None:
        """Inject the memory store instance globally for memory tools to access."""
        global _ACTIVE_MEMORY
        _ACTIVE_MEMORY = memory_store

    def register(self, name: str, fn: Callable, description: str, params: dict = None):
        """Register a tool function."""
        self._tools[name] = {
            "fn": fn,
            "description": description,
            "params": params or {},
        }

    def call(self, name: str, **kwargs) -> Any:
        """Call a tool by name."""
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        return tool["fn"](**kwargs)

    def list_tools(self) -> list[dict]:
        """List all available tools with descriptions."""
        return [
            {"name": k, "description": v["description"], "params": v["params"]}
            for k, v in sorted(self._tools.items())
        ]

    @property
    def count(self) -> int:
        return len(self._tools)

    # ══════════════════════════════════════════════════════════════
    # BUILTIN TOOLS
    # ══════════════════════════════════════════════════════════════

    def _register_builtins(self):
        """Register all built-in tools."""

        # ── System Information ────────────────────────────────
        self.register("system_info", _tool_system_info,
            "Get comprehensive system information (OS, CPU, RAM, disk, network)",
            {"detail": "basic|full"})

        self.register("disk_usage", _tool_disk_usage,
            "Get disk space usage for all drives",
            {"path": "optional specific path"})

        self.register("memory_usage", _tool_memory_usage,
            "Get current RAM and swap usage")

        self.register("cpu_info", _tool_cpu_info,
            "Get CPU details and current load percentage")

        self.register("network_info", _tool_network_info,
            "Get network interfaces, IP addresses, and connectivity")

        self.register("uptime", _tool_uptime,
            "Get system uptime and last boot time")

        # ── File Operations ───────────────────────────────────
        self.register("file_read", _tool_file_read,
            "Read the contents of a text file. Returns content, line count, and size",
            {"path": "file path (absolute or relative)", "max_lines": "limit lines returned (default 200)"})

        self.register("file_write", _tool_file_write,
            "Write or append text to a file. Creates parent directories if needed",
            {"path": "file path", "content": "text to write", "mode": "write|append (default write)"})

        self.register("file_list", _tool_file_list,
            "List contents of a directory with metadata (size, modified date, type)",
            {"path": "directory path (default .)", "pattern": "glob filter (default *)", "recursive": "true for deep scan"})

        self.register("file_copy", _tool_file_copy,
            "Copy a file or directory to a new location",
            {"source": "source path", "destination": "destination path"})

        self.register("file_delete", _tool_file_delete,
            "Delete a file. Requires confirm=true for safety",
            {"path": "file to delete", "confirm": "must be true to proceed"})

        self.register("file_search", _tool_file_search,
            "Search for files matching a pattern recursively",
            {"path": "root directory", "pattern": "glob pattern", "max_results": "limit"})

        self.register("file_info", _tool_file_info,
            "Get detailed file info (size, dates, permissions, hash)",
            {"path": "file path"})

        self.register("dir_tree", _tool_dir_tree,
            "Get directory tree structure (like `tree` command)",
            {"path": "directory", "depth": "max depth"})

        self.register("find_large_files", _tool_find_large_files,
            "Find largest files in a directory tree",
            {"path": "root dir", "count": "how many", "min_mb": "minimum size in MB"})

        # ── Compression ───────────────────────────────────────
        self.register("zip_create", _tool_zip_create,
            "Create a zip archive from files or directories",
            {"sources": "list of paths", "output": "output zip path"})

        self.register("zip_extract", _tool_zip_extract,
            "Extract a zip archive",
            {"path": "zip file path", "output": "extraction directory"})

        self.register("zip_list", _tool_zip_list,
            "List contents of a zip archive",
            {"path": "zip file path"})

        # ── Web / HTTP ────────────────────────────────────────
        self.register("http_get", _tool_http_get,
            "Make an HTTP GET request and return the response",
            {"url": "target URL", "headers": "optional headers dict"})

        self.register("http_post", _tool_http_post,
            "Make an HTTP POST request with JSON body",
            {"url": "target URL", "body": "JSON body dict", "headers": "optional headers"})

        self.register("download_file", _tool_download_file,
            "Download a file from URL to local path",
            {"url": "source URL", "output": "local file path"})

        self.register("dns_lookup", _tool_dns_lookup,
            "Resolve a hostname to IP addresses",
            {"hostname": "domain name"})

        self.register("port_check", _tool_port_check,
            "Check if a TCP port is open on a host",
            {"host": "hostname/IP", "port": "port number"})

        # ── Environment ───────────────────────────────────────
        self.register("env_list", _tool_env_list,
            "List all environment variables (or filtered)",
            {"filter": "optional substring filter"})

        self.register("path_list", _tool_path_list,
            "List all directories in the system PATH",
            {"check_exists": "verify each dir exists"})

        self.register("installed_packages", _tool_installed_packages,
            "List installed Python packages (pip list)",
            {"filter": "optional package name filter"})

        # ── Date/Time ─────────────────────────────────────────
        self.register("current_time", _tool_current_time,
            "Get current date/time in various formats")

        self.register("timezone_info", _tool_timezone_info,
            "Get system timezone information")

        # ── Text/Data Processing ──────────────────────────────
        self.register("json_validate", _tool_json_validate,
            "Validate and pretty-print a JSON string",
            {"data": "JSON string"})

        self.register("text_stats", _tool_text_stats,
            "Get statistics about a text (lines, words, chars, encoding)",
            {"text": "input text or file path"})

        self.register("base64_encode", _tool_base64_encode,
            "Encode text to base64",
            {"text": "input text"})

        self.register("base64_decode", _tool_base64_decode,
            "Decode base64 to text",
            {"data": "base64 string"})

        # ── Clipboard ─────────────────────────────────────────
        self.register("clipboard_get", _tool_clipboard_get,
            "Get current clipboard content (text)")

        self.register("clipboard_set", _tool_clipboard_set,
            "Set clipboard content",
            {"text": "text to copy"})

        # ── Windows-specific ──────────────────────────────────
        self.register("installed_programs", _tool_installed_programs,
            "List programs installed on Windows")

        self.register("windows_services", _tool_windows_services,
            "List Windows services and their status",
            {"filter": "optional name filter", "status": "running|stopped|all"})

        self.register("scheduled_tasks", _tool_scheduled_tasks,
            "List Windows scheduled tasks")

        self.register("startup_items", _tool_startup_items,
            "List programs that run on Windows startup")

        self.register("event_log", _tool_event_log,
            "Get recent Windows event log entries",
            {"log": "System|Application|Security", "count": "number of entries"})

        # ── Memory (LTM) ──────────────────────────────────────
        self.register("memory_save", _tool_memory_save,
            "Save important facts or project structure data to long-term memory",
            {"key": "unique identifier", "value": "the facts or data (string/json)", "category": "grouping category e.g., 'project_context'"})

        self.register("memory_search", _tool_memory_search,
            "Search long-term memory by keyword, category, or key name",
            {"query": "search terms, category, or key name to look up"})

        self.register("memory_get", _tool_memory_get,
            "Get a specific value from long-term memory by exact key",
            {"key": "the exact memory key to retrieve"})

        # ── Web Intelligence (browsing/scraping) ──────────────
        from james.tools.web import register_web_tools
        register_web_tools(self)

        # ── Task Scheduler ─────────────────────────────────────
        self.register("schedule_task", _tool_schedule_task,
            "Schedule a task to run later or on a recurring interval",
            {"name": "human-readable task name",
             "task": "command or description to execute",
             "delay_minutes": "run after N minutes (for one-shot)",
             "interval_minutes": "repeat every N minutes (for recurring)"})

        self.register("list_scheduled", _tool_list_scheduled,
            "List all scheduled tasks with their status and next run times")

        self.register("cancel_scheduled", _tool_cancel_scheduled,
            "Cancel a scheduled task by its ID",
            {"task_id": "ID of the scheduled task to cancel"})

        # ── RAG (Document Retrieval) ───────────────────────────────
        self.register("rag_ingest", _tool_rag_ingest,
            "Ingest a file or directory into the RAG knowledge base for semantic search",
            {"path": "file or directory path to ingest",
             "recursive": "scan subdirectories (default true)"})

        self.register("rag_search", _tool_rag_search,
            "Search ingested documents for relevant content using semantic similarity",
            {"query": "natural language search query",
             "top_k": "max results (default 5)"})

        self.register("rag_status", _tool_rag_status,
            "Get RAG pipeline status (indexed documents, sources)")

         # ── Vector Memory Search ───────────────────────────────────
        self.register("vector_search", _tool_vector_search,
            "Semantic search across all memories using vector similarity",
            {"query": "natural language search query",
             "top_k": "max results (default 5)"})

        # ── File Watcher ───────────────────────────────────────────
        self.register("watch_directory", _tool_watch_directory,
            "Watch a directory for file changes and trigger a task automatically",
            {"directory": "directory to watch",
             "task": "command or instruction to run on change",
             "patterns": "glob patterns to match (default ['*'])",
             "debounce": "seconds between triggers (default 2)"})

        self.register("unwatch", _tool_unwatch,
            "Stop watching a directory",
            {"rule_id": "watch rule ID to remove"})

        self.register("list_watches", _tool_list_watches,
            "List all active file watch rules")

        # ── Conversation History ───────────────────────────────────
        self.register("conversation_history", _tool_conversation_history,
            "Get recent conversation history",
            {"conversation": "conversation name (default 'web_default')",
             "limit": "max messages (default 20)"})

        self.register("list_conversations", _tool_list_conversations,
            "List all saved conversations")

        # ── Skill Versioning ───────────────────────────────────────
        self.register("skill_history", _tool_skill_history,
            "Get version history of a skill",
            {"skill_name": "name of the skill"})

        self.register("skill_rollback", _tool_skill_rollback,
            "Rollback a skill to a previous version",
            {"skill_name": "name of the skill",
             "version": "version number to restore"})

        # ── Health Monitor ─────────────────────────────────────────
        self.register("system_health", _tool_system_health,
            "Get a real-time snapshot of system health, CPU, memory, and error rates")

        # ── Plugin Management ──────────────────────────────────────
        self.register("load_plugin", _tool_load_plugin,
            "Load and activate a plugin by name",
            {"plugin_name": "name of the plugin to load"})

        self.register("unload_plugin", _tool_unload_plugin,
            "Unload an active plugin",
            {"plugin_name": "name of the plugin to unload"})

        self.register("list_plugins", _tool_list_plugins,
            "List all discovered plugins and their load status")

        # ── Multi-Agent ────────────────────────────────────────────
        self.register("delegate_task", _tool_delegate_task,
            "Delegate a subtask to a specialized agent",
            {"task": "description of the task to delegate",
             "agent_name": "specific agent to use (optional)",
             "role": "agent role like 'code', 'research', 'system' (optional)"})

        # ── Tool Evolution ─────────────────────────────────────────
        self.register("evolve_tool_code", _tool_evolve_tool_code,
            "Rewrite a dynamically generated tool's source code to fix edge cases or warnings, bumping its version.",
            {"tool_name": "The name of the tool to evolve", "warning": "The error, warning, or feedback guiding the rewrite"})

# ══════════════════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ══════════════════════════════════════════════════════════════════

def _tool_memory_save(key: str, value: Any, category: str = "general") -> dict:
    """Save a fact to global LTM."""
    if _ACTIVE_MEMORY is None:
        raise RuntimeError("MemoryStore not injected into ToolRegistry.")
    # Truncate to avoid exploding LTM
    val_str = str(value)
    if len(val_str) > 5000:
        logger.warning(f"Memory save for '{key}' truncated to 5000 chars.")
        val_str = val_str[:5000] + "...[TRUNCATED]"
    _ACTIVE_MEMORY.lt_set(key, val_str, category)
    return {"status": "success", "message": f"Saved memory key '{key}' in category '{category}'."}

def _tool_memory_search(query: str = None, key: str = None, **kwargs) -> list[dict]:
    """Search global LTM by keyword, key, or category. Accepts 'query' or 'key' arg."""
    if _ACTIVE_MEMORY is None:
        raise RuntimeError("MemoryStore not injected into ToolRegistry.")
    # Accept 'key' as alias for 'query' — LLM sometimes uses wrong param name
    search_term = query or key or ""
    # Also drain any extra kwargs (e.g. 'description' from the LLM)
    if not search_term:
        for v in kwargs.values():
            if isinstance(v, str) and v:
                search_term = v
                break
    if not search_term:
        # Return recent memories if no query provided
        return _ACTIVE_MEMORY.lt_list(limit=10)

    results = []
    all_ltm = _ACTIVE_MEMORY.lt_list(limit=200)
    q_low = search_term.lower()
    for item in all_ltm:
        cat = str(item.get("category", "")).lower()
        k = str(item.get("key", "")).lower()
        v = str(item.get("value", "")).lower()
        if q_low in k or q_low in v or q_low in cat:
            results.append({
                "key": item["key"],
                "category": item["category"],
                "value": item["value"],
                "updated_at": item.get("updated_at", 0)
            })
    return results[:10]

def _tool_memory_get(key: str) -> dict:
    """Get a specific value from LTM by exact key."""
    if _ACTIVE_MEMORY is None:
        raise RuntimeError("MemoryStore not injected into ToolRegistry.")
    value = _ACTIVE_MEMORY.lt_get(key)
    if value is None:
        return {"found": False, "key": key, "value": None}
    return {"found": True, "key": key, "value": value}

def _tool_system_info(detail: str = "full") -> dict:
    """Comprehensive system information."""
    import platform as plat
    info = {
        "hostname": socket.gethostname(),
        "os": plat.system(),
        "os_version": plat.version(),
        "os_release": plat.release(),
        "architecture": plat.machine(),
        "processor": plat.processor(),
        "python_version": plat.python_version(),
        "user": os.environ.get("USERNAME", os.environ.get("USER", "unknown")),
        "home": str(Path.home()),
        "cwd": os.getcwd(),
        "cpu_count": os.cpu_count(),
    }

    if detail == "full":
        try:
            # Memory via PowerShell (no psutil dependency)
            import subprocess
            mem_cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json"'
            r = subprocess.run(mem_cmd, shell=True, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                mem = json.loads(r.stdout)
                total_kb = mem.get("TotalVisibleMemorySize", 0)
                free_kb = mem.get("FreePhysicalMemory", 0)
                info["ram_total_gb"] = round(total_kb / 1048576, 1)
                info["ram_free_gb"] = round(free_kb / 1048576, 1)
                info["ram_used_pct"] = round((1 - free_kb / total_kb) * 100, 1) if total_kb else 0
        except Exception:
            pass

        try:
            # GPU info
            import subprocess
            gpu_cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json"'
            r = subprocess.run(gpu_cmd, shell=True, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                gpus = json.loads(r.stdout)
                if isinstance(gpus, dict):
                    gpus = [gpus]
                info["gpus"] = [
                    {
                        "name": g.get("Name", ""),
                        "vram_gb": round(g.get("AdapterRAM", 0) / 1073741824, 1) if g.get("AdapterRAM") else 0,
                        "driver": g.get("DriverVersion", ""),
                    }
                    for g in gpus
                ]
        except Exception:
            pass

    return info


def _tool_disk_usage(path: str = None) -> list:
    """Get disk usage for all drives or a specific path."""
    import subprocess
    cmd = 'powershell -NoProfile -Command "Get-PSDrive -PSProvider FileSystem | Select-Object Name,Used,Free,Root | ConvertTo-Json"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return [{"error": r.stderr}]
    drives = json.loads(r.stdout)
    if isinstance(drives, dict):
        drives = [drives]
    return [
        {
            "drive": d.get("Root", d.get("Name", "")),
            "used_gb": round(d.get("Used", 0) / 1073741824, 1) if d.get("Used") else 0,
            "free_gb": round(d.get("Free", 0) / 1073741824, 1) if d.get("Free") else 0,
            "total_gb": round((d.get("Used", 0) + d.get("Free", 0)) / 1073741824, 1),
        }
        for d in drives
    ]


def _tool_memory_usage() -> dict:
    """Get RAM usage."""
    import subprocess
    cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory,TotalVirtualMemorySize,FreeVirtualMemory | ConvertTo-Json"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return {"error": r.stderr}
    data = json.loads(r.stdout)
    total = data.get("TotalVisibleMemorySize", 0)
    free = data.get("FreePhysicalMemory", 0)
    return {
        "total_gb": round(total / 1048576, 2),
        "free_gb": round(free / 1048576, 2),
        "used_gb": round((total - free) / 1048576, 2),
        "used_pct": round((1 - free / total) * 100, 1) if total else 0,
    }


def _tool_cpu_info() -> dict:
    """CPU information and load."""
    import subprocess
    cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,LoadPercentage | ConvertTo-Json"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return {"error": r.stderr}
    data = json.loads(r.stdout)
    if isinstance(data, list):
        data = data[0]
    return {
        "name": data.get("Name", ""),
        "cores": data.get("NumberOfCores", 0),
        "threads": data.get("NumberOfLogicalProcessors", 0),
        "max_clock_mhz": data.get("MaxClockSpeed", 0),
        "load_pct": data.get("LoadPercentage", 0),
    }


def _tool_network_info() -> dict:
    """Network information."""
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "unknown"

    info = {"hostname": hostname, "local_ip": local_ip, "interfaces": []}

    try:
        import subprocess
        cmd = 'powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -ne \'127.0.0.1\'} | Select-Object InterfaceAlias,IPAddress,PrefixLength | ConvertTo-Json"'
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            ifaces = json.loads(r.stdout)
            if isinstance(ifaces, dict):
                ifaces = [ifaces]
            info["interfaces"] = [
                {"name": i.get("InterfaceAlias"), "ip": i.get("IPAddress"), "prefix": i.get("PrefixLength")}
                for i in ifaces
            ]
    except Exception:
        pass

    # Internet connectivity check
    try:
        urllib_request.urlopen("https://1.1.1.1", timeout=3)
        info["internet"] = True
    except Exception:
        info["internet"] = False

    return info


def _tool_uptime() -> dict:
    """System uptime."""
    import subprocess
    cmd = 'powershell -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString(\'o\')"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    boot_time = r.stdout.strip() if r.returncode == 0 else "unknown"
    return {"last_boot": boot_time, "current_time": datetime.now().isoformat()}


def _tool_file_search(path: str = ".", pattern: str = "*", max_results: int = 50) -> list:
    """Search for files matching a glob pattern.

    ⚡ Bolt: Optimized recursive traversal using os.walk to avoid O(N)
    scanning of massive ignored directories like node_modules or .venv.
    """
    results = []
    skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv", "env", "build", "dist", "target", ".idea", ".vscode"}
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for item in dirs + files:
                match = Path(root) / item
                if match.match(pattern):
                    if len(results) >= max_results:
                        return results
                    try:
                        stat = match.stat()
                        results.append({
                            "path": str(match),
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "is_dir": match.is_dir(),
                        })
                    except Exception:
                        results.append({"path": str(match), "error": "stat failed"})
    except Exception as e:
        return [{"error": str(e)}]
    return results


def _tool_file_info(path: str) -> dict:
    """Detailed file information."""
    p = Path(path)
    if not p.exists():
        return {"error": f"Path not found: {path}"}
    stat = p.stat()
    info = {
        "path": str(p.resolve()),
        "name": p.name,
        "extension": p.suffix,
        "size_bytes": stat.st_size,
        "size_human": _human_size(stat.st_size),
        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "is_file": p.is_file(),
        "is_dir": p.is_dir(),
        "is_symlink": p.is_symlink(),
    }
    if p.is_dir():
        try:
            count = 0
            for _ in p.iterdir():
                count += 1
            info["children"] = count
        except Exception:
            pass
    return info


def _tool_dir_tree(path: str = ".", depth: int = 3) -> dict:
    """Directory tree structure."""
    def _walk(p: Path, d: int) -> dict:
        node = {"name": p.name, "type": "dir" if p.is_dir() else "file"}
        if p.is_file():
            node["size"] = p.stat().st_size
        elif p.is_dir() and d > 0:
            try:
                children = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                node["children"] = [_walk(c, d - 1) for c in children[:50]]
            except PermissionError:
                node["error"] = "permission denied"
        return node
    return _walk(Path(path), depth)


def _tool_find_large_files(path: str = ".", count: int = 20, min_mb: float = 1.0) -> list:
    """Find largest files in a directory.

    ⚡ Bolt: Optimized directory traversal using os.walk to drastically
    reduce memory and I/O overhead from ignored directories.
    """
    min_bytes = int(min_mb * 1048576)
    files = []
    skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv", "env", "build", "dist", "target", ".idea", ".vscode"}
    try:
        for root, dirs, filenames in os.walk(path):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for filename in filenames:
                try:
                    f = Path(root) / filename
                    size = f.stat().st_size
                    if size >= min_bytes:
                        files.append({"path": str(f), "size_mb": round(size / 1048576, 1)})
                except Exception:
                    pass
    except Exception:
        pass
    files.sort(key=lambda x: x["size_mb"], reverse=True)
    return files[:count]


def _tool_file_hash(path: str, algorithm: str = "sha256") -> dict:
    """Compute file hash."""
    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return {"path": path, "algorithm": algorithm, "hash": h.hexdigest()}


def _tool_zip_create(sources: list, output: str) -> dict:
    """Create zip archive."""
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        count = 0
        for src in sources:
            p = Path(src)
            if p.is_file():
                zf.write(p, p.name)
                count += 1
            elif p.is_dir():
                # ⚡ Bolt: Replace Path.rglob with os.walk to avoid traversing into ignored directories
                skip_dirs = {".git", "__pycache__", ".venv", "venv", ".tox"}
                for root, dirs, files in os.walk(p):
                    dirs[:] = [d for d in dirs if d not in skip_dirs]
                    for f in files:
                        child = Path(root) / f
                        zf.write(child, child.relative_to(p.parent))
                        count += 1
    return {"output": output, "files_added": count, "size": os.path.getsize(output)}


def _tool_zip_extract(path: str, output: str = ".") -> dict:
    """Extract zip archive."""
    with zipfile.ZipFile(path, "r") as zf:
        zf.extractall(output)
        return {"extracted_to": output, "files": len(zf.namelist())}


def _tool_zip_list(path: str) -> list:
    """List zip contents."""
    with zipfile.ZipFile(path, "r") as zf:
        return [
            {"name": info.filename, "size": info.file_size, "compressed": info.compress_size}
            for info in zf.infolist()
        ]


def _tool_http_get(url: str, headers: dict = None) -> dict:
    """HTTP GET request."""
    req = urllib_request.Request(url, headers=headers or {})
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": body[:10000],
                "length": len(body),
            }
    except URLError as e:
        return {"error": str(e)}


def _tool_http_post(url: str, body: dict = None, headers: dict = None) -> dict:
    """HTTP POST request with JSON body."""
    data = json.dumps(body or {}).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib_request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            rbody = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "body": rbody[:10000]}
    except URLError as e:
        return {"error": str(e)}


def _tool_download_file(url: str, output: str) -> dict:
    """Download file from URL."""
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    try:
        urllib_request.urlretrieve(url, output)
        return {"output": output, "size": os.path.getsize(output)}
    except Exception as e:
        return {"error": str(e)}


def _tool_dns_lookup(hostname: str) -> dict:
    """DNS resolution."""
    try:
        results = socket.getaddrinfo(hostname, None)
        ips = list(set(r[4][0] for r in results))
        return {"hostname": hostname, "addresses": ips}
    except Exception as e:
        return {"hostname": hostname, "error": str(e)}


def _tool_port_check(host: str, port: int) -> dict:
    """TCP port check."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex((host, int(port)))
        s.close()
        return {"host": host, "port": port, "open": result == 0}
    except Exception as e:
        return {"host": host, "port": port, "error": str(e)}


def _tool_env_list(filter: str = None) -> dict:
    """List environment variables."""
    envs = dict(os.environ)
    if filter:
        # ⚡ Bolt: Hoist filter.lower() out of dict comprehension to avoid O(N) re-evaluation
        filter_lower = filter.lower()
        envs = {k: v for k, v in envs.items() if filter_lower in k.lower()}
    return envs


def _tool_path_list(check_exists: bool = True) -> list:
    """List PATH directories."""
    dirs = os.environ.get("PATH", "").split(os.pathsep)
    return [
        {"path": d, "exists": os.path.isdir(d) if check_exists else None}
        for d in dirs
    ]


def _tool_installed_packages(filter: str = None) -> list:
    """List pip packages."""
    import subprocess
    r = subprocess.run(
        "pip list --format=json", shell=True, capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        return [{"error": r.stderr}]
    packages = json.loads(r.stdout)
    if filter:
        # ⚡ Bolt: Hoist filter.lower() out of list comprehension to avoid O(N) re-evaluation
        filter_lower = filter.lower()
        packages = [p for p in packages if filter_lower in p.get("name", "").lower()]
    return packages


def _tool_current_time() -> dict:
    """Current time in multiple formats."""
    now = datetime.now()
    return {
        "iso": now.isoformat(),
        "timestamp": time.time(),
        "human": now.strftime("%A, %B %d, %Y %I:%M:%S %p"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
    }


def _tool_timezone_info() -> dict:
    """Timezone information."""
    import time as t
    return {
        "timezone": t.tzname,
        "utc_offset_hours": -t.timezone / 3600,
        "daylight_saving": bool(t.daylight),
    }


def _tool_json_validate(data: str) -> dict:
    """Validate and format JSON."""
    try:
        parsed = json.loads(data)
        return {"valid": True, "formatted": json.dumps(parsed, indent=2), "type": type(parsed).__name__}
    except json.JSONDecodeError as e:
        return {"valid": False, "error": str(e)}


def _tool_text_stats(text: str) -> dict:
    """Text statistics."""
    # Check if it's a file path
    if os.path.isfile(text):
        with open(text, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    return {
        "characters": len(text),
        "lines": text.count("\n") + 1,
        "words": len(text.split()),
        "bytes": len(text.encode("utf-8")),
    }


def _tool_base64_encode(text: str) -> dict:
    """Base64 encode."""
    import base64
    return {"encoded": base64.b64encode(text.encode()).decode()}


def _tool_base64_decode(data: str) -> dict:
    """Base64 decode."""
    import base64
    try:
        return {"decoded": base64.b64decode(data).decode()}
    except Exception as e:
        return {"error": str(e)}


def _tool_clipboard_get() -> dict:
    """Get clipboard text (Windows)."""
    import subprocess
    r = subprocess.run(
        'powershell -NoProfile -Command "Get-Clipboard"',
        shell=True, capture_output=True, text=True, timeout=5
    )
    return {"text": r.stdout.strip() if r.returncode == 0 else "", "success": r.returncode == 0}


def _tool_clipboard_set(text: str) -> dict:
    """Set clipboard text (Windows)."""
    import subprocess
    r = subprocess.run(
        ['powershell', '-NoProfile', '-Command', f'Set-Clipboard -Value "{text}"'],
        capture_output=True, text=True, timeout=5
    )
    return {"success": r.returncode == 0}


def _tool_installed_programs() -> list:
    """List installed programs (Windows)."""
    import subprocess
    cmd = 'powershell -NoProfile -Command "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Select-Object DisplayName,DisplayVersion,Publisher,InstallDate | Where-Object {$_.DisplayName -ne $null} | Sort-Object DisplayName | ConvertTo-Json"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return [{"error": r.stderr}]
    try:
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            data = [data]
        return [
            {
                "name": p.get("DisplayName", ""),
                "version": p.get("DisplayVersion", ""),
                "publisher": p.get("Publisher", ""),
            }
            for p in data[:200]
        ]
    except Exception:
        return []


def _tool_windows_services(filter: str = None, status: str = "all") -> list:
    """List Windows services."""
    import subprocess
    cmd = 'powershell -NoProfile -Command "Get-Service | Select-Object Name,DisplayName,Status | ConvertTo-Json"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return [{"error": r.stderr}]
    services = json.loads(r.stdout)
    if isinstance(services, dict):
        services = [services]
    if filter:
        # ⚡ Bolt: Hoist filter.lower() out of list comprehension to avoid O(N) re-evaluation
        filter_lower = filter.lower()
        services = [s for s in services if filter_lower in s.get("DisplayName", "").lower() or filter_lower in s.get("Name", "").lower()]
    if status != "all":
        status_map = {"running": 4, "stopped": 1}
        target = status_map.get(status.lower(), 0)
        if target:
            services = [s for s in services if s.get("Status") == target]
    return [
        {"name": s.get("Name"), "display": s.get("DisplayName"), "status": "Running" if s.get("Status") == 4 else "Stopped"}
        for s in services[:100]
    ]


def _tool_scheduled_tasks() -> list:
    """List scheduled tasks."""
    import subprocess
    cmd = 'powershell -NoProfile -Command "Get-ScheduledTask | Where-Object {$_.State -ne \'Disabled\'} | Select-Object TaskName,TaskPath,State | ConvertTo-Json"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return [{"error": r.stderr}]
    try:
        tasks = json.loads(r.stdout)
        if isinstance(tasks, dict):
            tasks = [tasks]
        return [
            {"name": t.get("TaskName"), "path": t.get("TaskPath"), "state": str(t.get("State"))}
            for t in tasks[:100]
        ]
    except Exception:
        return []


def _tool_startup_items() -> list:
    """List startup programs."""
    import subprocess
    cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location | ConvertTo-Json"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return [{"error": r.stderr}]
    try:
        items = json.loads(r.stdout)
        if isinstance(items, dict):
            items = [items]
        return items
    except Exception:
        return []


def _tool_event_log(log: str = "System", count: int = 20) -> list:
    """Windows event log entries."""
    import subprocess
    cmd = f'powershell -NoProfile -Command "Get-EventLog -LogName {log} -Newest {count} | Select-Object TimeGenerated,EntryType,Source,Message | ConvertTo-Json"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return [{"error": r.stderr}]
    try:
        events = json.loads(r.stdout)
        if isinstance(events, dict):
            events = [events]
        return [
            {
                "time": e.get("TimeGenerated", ""),
                "type": str(e.get("EntryType", "")),
                "source": e.get("Source", ""),
                "message": str(e.get("Message", ""))[:200],
            }
            for e in events
        ]
    except Exception:
        return []


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


# ── File CRUD Tools ───────────────────────────────────────────

_BLOCKED_PATHS = [
    "C:\\Windows\\System32", "C:\\Windows\\SysWOW64",
    "C:\\Windows\\Boot", "C:\\$Recycle.Bin",
    "/etc/shadow", "/etc/passwd", "/etc/sudoers",
    "/boot", "/dev", "/proc", "/sys",
]


def _safe_path(path: str) -> str:
    """Canonicalize and validate a file path against blocked system dirs."""
    resolved = os.path.abspath(os.path.expanduser(path))
    for blocked in _BLOCKED_PATHS:
        if resolved.lower().startswith(blocked.lower()):
            raise PermissionError(f"Access denied: {blocked} is a protected system path")
    return resolved


def _tool_file_read(path: str, max_lines: int = 200) -> dict:
    """Read text file contents safely."""
    try:
        resolved = _safe_path(path)
        if not os.path.exists(resolved):
            return {"error": f"File not found: {path}"}
        if os.path.isdir(resolved):
            return {"error": f"Path is a directory, not a file: {path}"}
        size = os.path.getsize(resolved)
        if size > 10_000_000:  # 10MB limit
            return {"error": f"File too large: {size / 1e6:.1f}MB (limit 10MB)"}
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        total = len(lines)
        truncated = False
        if max_lines and total > max_lines:
            lines = lines[:max_lines]
            truncated = True
        return {
            "content": "".join(lines),
            "lines": total,
            "size_bytes": size,
            "size_human": _human_size(size),
            "truncated": truncated,
            "path": resolved,
        }
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to read file: {e}"}


def _tool_file_write(path: str, content: str, mode: str = "write") -> dict:
    """Write or append text to a file."""
    try:
        resolved = _safe_path(path)
        os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
        if len(content) > 5_000_000:  # 5MB write limit
            return {"error": f"Content too large: {len(content)} chars (limit 5M)"}
        file_mode = "a" if mode == "append" else "w"
        existed = os.path.exists(resolved)
        with open(resolved, file_mode, encoding="utf-8") as f:
            f.write(content)
        new_size = os.path.getsize(resolved)
        logger.info(f"file_write: {'appended' if mode == 'append' else 'wrote'} {len(content)} chars to {resolved}")
        return {
            "status": "success",
            "path": resolved,
            "action": "appended" if mode == "append" else ("overwritten" if existed else "created"),
            "bytes_written": len(content.encode("utf-8")),
            "total_size": _human_size(new_size),
        }
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to write file: {e}"}


def _tool_file_list(path: str = ".", pattern: str = "*", recursive: bool = False) -> dict:
    """List directory contents with metadata."""
    try:
        resolved = _safe_path(path)
        if not os.path.isdir(resolved):
            return {"error": f"Not a directory: {path}"}

        all_paths = []
        if recursive:
            # ⚡ Bolt: Replace Path.rglob with os.walk to prune ignored dirs and avoid O(N) traversal overhead
            skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".tox"}
            for root, dirs, files in os.walk(resolved):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for item in dirs + files:
                    p = Path(root) / item
                    if p.match(pattern):
                        all_paths.append(p)
        else:
            all_paths = list(Path(resolved).glob(pattern))

        entries = []
        for p in sorted(all_paths):
            if len(entries) >= 200:  # cap results
                break
            try:
                stat = p.stat()
                entries.append({
                    "name": p.name,
                    "path": str(p),
                    "is_dir": p.is_dir(),
                    "size": _human_size(stat.st_size) if p.is_file() else None,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
            except (PermissionError, OSError):
                continue
        return {"path": resolved, "count": len(entries), "entries": entries}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to list directory: {e}"}


def _tool_file_copy(source: str, destination: str) -> dict:
    """Copy a file or directory."""
    try:
        src = _safe_path(source)
        dst = _safe_path(destination)
        if not os.path.exists(src):
            return {"error": f"Source not found: {source}"}
        if os.path.isdir(src):
            shutil.copytree(src, dst)
            return {"status": "success", "action": "copied directory", "source": src, "destination": dst}
        else:
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            shutil.copy2(src, dst)
            return {"status": "success", "action": "copied file", "source": src, "destination": dst,
                    "size": _human_size(os.path.getsize(dst))}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to copy: {e}"}


def _tool_file_delete(path: str, confirm: bool = False) -> dict:
    """Delete a file. Requires explicit confirm=True."""
    if not confirm:
        return {"error": "Safety: you must pass confirm=true to delete a file.",
                "hint": "Set kwargs.confirm to true if you really want to delete."}
    try:
        resolved = _safe_path(path)
        if not os.path.exists(resolved):
            return {"error": f"File not found: {path}"}
        if os.path.isdir(resolved):
            return {"error": "Path is a directory. Use a shell command to delete directories."}
        size = os.path.getsize(resolved)
        os.remove(resolved)
        logger.warning(f"file_delete: DELETED {resolved} ({_human_size(size)})")
        return {"status": "success", "deleted": resolved, "size": _human_size(size)}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to delete: {e}"}


# ── Scheduler Tools ──────────────────────────────────────────────

_ACTIVE_SCHEDULER = None

def set_scheduler(scheduler_instance) -> None:
    """Inject the scheduler instance for tool access."""
    global _ACTIVE_SCHEDULER
    _ACTIVE_SCHEDULER = scheduler_instance


def _tool_schedule_task(
    name: str = "unnamed_task",
    task: str = "",
    delay_minutes: float = 0,
    interval_minutes: float = 0,
    **kwargs,
) -> dict:
    """Schedule a task for future or recurring execution."""
    if _ACTIVE_SCHEDULER is None:
        return {"error": "Scheduler not available"}
    if not task:
        return {"error": "No task specified. Provide 'task' parameter."}

    from james.scheduler import TaskSchedule
    if interval_minutes > 0:
        # Recurring task
        task_id = _ACTIVE_SCHEDULER.add_task(
            name=name,
            task=task,
            schedule=TaskSchedule(
                schedule_type="interval",
                interval_seconds=int(interval_minutes * 60),
            )
        )
        return {
            "status": "scheduled",
            "task_id": task_id,
            "type": "recurring",
            "interval": f"{interval_minutes} minutes",
            "message": f"Task '{name}' scheduled to repeat every {interval_minutes} minutes",
        }
    else:
        # One-shot delayed task
        delay_secs = int(delay_minutes * 60) if delay_minutes > 0 else 0
        task_id = _ACTIVE_SCHEDULER.add_task(
            name=name,
            task=task,
            schedule=TaskSchedule(
                schedule_type="once",
                delay_seconds=delay_secs,
            )
        )
        return {
            "status": "scheduled",
            "task_id": task_id,
            "type": "one-shot",
            "delay": f"{delay_minutes} minutes" if delay_minutes > 0 else "immediate",
            "message": f"Task '{name}' scheduled for {delay_minutes:.0f} min from now",
        }


def _tool_list_scheduled(**kwargs) -> dict:
    """List all scheduled tasks."""
    if _ACTIVE_SCHEDULER is None:
        return {"error": "Scheduler not available"}
    return _ACTIVE_SCHEDULER.status()


def _tool_cancel_scheduled(task_id: str = "", **kwargs) -> dict:
    """Cancel a scheduled task."""
    if _ACTIVE_SCHEDULER is None:
        return {"error": "Scheduler not available"}
    if not task_id:
        return {"error": "No task_id specified"}
    cancelled = _ACTIVE_SCHEDULER.cancel_task(task_id)
    if cancelled:
        return {"status": "cancelled", "task_id": task_id}
    return {"error": f"Task '{task_id}' not found"}


# ── RAG & Vector Tools ──────────────────────────────────────────

_ACTIVE_RAG = None
_ACTIVE_VECTORS = None


def set_rag(rag_instance) -> None:
    """Inject the RAG pipeline instance for tool access."""
    global _ACTIVE_RAG
    _ACTIVE_RAG = rag_instance


def set_vectors(vector_instance) -> None:
    """Inject the VectorStore instance for tool access."""
    global _ACTIVE_VECTORS
    _ACTIVE_VECTORS = vector_instance


def _tool_rag_ingest(path: str = "", recursive: bool = True, **kwargs) -> dict:
    """Ingest a file or directory into the RAG knowledge base."""
    if _ACTIVE_RAG is None:
        return {"error": "RAG pipeline not available"}
    if not path:
        return {"error": "No path specified. Provide 'path' parameter."}
    return _ACTIVE_RAG.ingest(path, recursive=recursive)


def _tool_rag_search(query: str = "", top_k: int = 5, **kwargs) -> dict:
    """Search ingested documents using semantic similarity."""
    if _ACTIVE_RAG is None:
        return {"error": "RAG pipeline not available"}
    if not query:
        return {"error": "No query specified"}
    results = _ACTIVE_RAG.retrieve(query, top_k=top_k)
    return {"results": results, "count": len(results)}


def _tool_rag_status(**kwargs) -> dict:
    """Get RAG pipeline status."""
    if _ACTIVE_RAG is None:
        return {"error": "RAG pipeline not available"}
    return _ACTIVE_RAG.status()


def _tool_vector_search(query: str = "", top_k: int = 5, **kwargs) -> dict:
    """Semantic search across vector memory."""
    if _ACTIVE_VECTORS is None:
        return {"error": "Vector store not available"}
    if not query:
        return {"error": "No query specified"}
    results = _ACTIVE_VECTORS.search(query, top_k=top_k)
    return {
        "results": [{"key": k, "relevance": round(s, 3)} for k, s in results],
        "count": len(results),
    }


# ── Phase 4 Tools: Watcher, Conversations, Skill Versions ───────

_ACTIVE_WATCHER = None
_ACTIVE_CONVERSATIONS = None
_ACTIVE_SKILL_VERSIONS = None


def set_watcher(watcher_instance) -> None:
    global _ACTIVE_WATCHER
    _ACTIVE_WATCHER = watcher_instance


def set_conversations(conv_instance) -> None:
    global _ACTIVE_CONVERSATIONS
    _ACTIVE_CONVERSATIONS = conv_instance


def set_skill_versions(sv_instance) -> None:
    global _ACTIVE_SKILL_VERSIONS
    _ACTIVE_SKILL_VERSIONS = sv_instance


def _tool_watch_directory(directory: str = "", task: str = "",
                          patterns: list = None, debounce: float = 2.0,
                          **kwargs) -> dict:
    """Watch a directory for file changes."""
    if _ACTIVE_WATCHER is None:
        return {"error": "File watcher not available"}
    if not directory:
        return {"error": "No directory specified"}
    if not task:
        return {"error": "No task specified"}
    try:
        # Start the watcher if not running
        if not _ACTIVE_WATCHER.is_running:
            _ACTIVE_WATCHER.start()
        rule_id = _ACTIVE_WATCHER.watch(
            directory, task,
            patterns=patterns, debounce=debounce,
        )
        return {"status": "watching", "rule_id": rule_id,
                "directory": directory, "task": task}
    except Exception as e:
        return {"error": str(e)}


def _tool_unwatch(rule_id: str = "", **kwargs) -> dict:
    """Remove a watch rule."""
    if _ACTIVE_WATCHER is None:
        return {"error": "File watcher not available"}
    if not rule_id:
        return {"error": "No rule_id specified"}
    removed = _ACTIVE_WATCHER.unwatch(rule_id)
    if removed:
        return {"status": "removed", "rule_id": rule_id}
    return {"error": f"Rule '{rule_id}' not found"}


def _tool_list_watches(**kwargs) -> dict:
    """List active watch rules."""
    if _ACTIVE_WATCHER is None:
        return {"error": "File watcher not available"}
    return {"rules": _ACTIVE_WATCHER.list_rules(),
            "running": _ACTIVE_WATCHER.is_running}


def _tool_conversation_history(conversation: str = "web_default",
                                limit: int = 20, **kwargs) -> dict:
    """Get conversation history."""
    if _ACTIVE_CONVERSATIONS is None:
        return {"error": "Conversation store not available"}
    history = _ACTIVE_CONVERSATIONS.get_history(conversation, limit=limit)
    return {"conversation": conversation, "messages": history,
            "count": len(history)}


def _tool_list_conversations(**kwargs) -> dict:
    """List all conversations."""
    if _ACTIVE_CONVERSATIONS is None:
        return {"error": "Conversation store not available"}
    convs = _ACTIVE_CONVERSATIONS.list_conversations()
    return {"conversations": convs, "count": len(convs)}


def _tool_skill_history(skill_name: str = "", **kwargs) -> dict:
    """Get version history of a skill."""
    if _ACTIVE_SKILL_VERSIONS is None:
        return {"error": "Skill versioning not available"}
    if not skill_name:
        return {"error": "No skill_name specified"}
    history = _ACTIVE_SKILL_VERSIONS.get_history(skill_name)
    return {"skill": skill_name, "versions": history,
            "current": _ACTIVE_SKILL_VERSIONS.get_current_version(skill_name)}


def _tool_skill_rollback(skill_name: str = "", version: int = 0,
                          **kwargs) -> dict:
    """Rollback a skill to a previous version."""
    if _ACTIVE_SKILL_VERSIONS is None:
        return {"error": "Skill versioning not available"}
    if not skill_name:
        return {"error": "No skill_name specified"}
    if version <= 0:
        return {"error": "Invalid version number"}
    result = _ACTIVE_SKILL_VERSIONS.rollback(skill_name, version)
    if result:
        return {"status": "rolled_back", "skill": skill_name,
                "restored_version": version}
    return {"error": f"Version {version} not found for '{skill_name}'"}


# ── Phase 5 Tools: Health, Plugins, Agents ───────────────────────

_ACTIVE_HEALTH = None
_ACTIVE_PLUGINS = None
_ACTIVE_AGENTS = None

def set_health(health_instance) -> None:
    global _ACTIVE_HEALTH
    _ACTIVE_HEALTH = health_instance

def set_plugins(plugins_instance) -> None:
    global _ACTIVE_PLUGINS
    _ACTIVE_PLUGINS = plugins_instance

def set_agents(agents_instance) -> None:
    global _ACTIVE_AGENTS
    _ACTIVE_AGENTS = agents_instance

def _tool_system_health(**kwargs) -> dict:
    if _ACTIVE_HEALTH is None:
        return {"error": "Health monitor not available"}
    return _ACTIVE_HEALTH.snapshot()

def _tool_load_plugin(plugin_name: str = "", **kwargs) -> dict:
    if _ACTIVE_PLUGINS is None:
        return {"error": "Plugin manager not available"}
    if not plugin_name:
        return {"error": "No plugin_name specified"}
    return _ACTIVE_PLUGINS.load(plugin_name)

def _tool_unload_plugin(plugin_name: str = "", **kwargs) -> dict:
    if _ACTIVE_PLUGINS is None:
        return {"error": "Plugin manager not available"}
    if not plugin_name:
        return {"error": "No plugin_name specified"}
    return _ACTIVE_PLUGINS.unload(plugin_name)

def _tool_list_plugins(**kwargs) -> dict:
    if _ACTIVE_PLUGINS is None:
        return {"error": "Plugin manager not available"}
    return {"plugins": _ACTIVE_PLUGINS.list_plugins()}

def _tool_delegate_task(task: str = "", agent_name: str = None, role: str = None, **kwargs) -> dict:
    if _ACTIVE_AGENTS is None:
        return {"error": "Agent coordinator not available"}
    if not task:
        return {"error": "No task specified"}
    
    from james.agents import AgentRole
    enum_role = None
    if role:
        try:
            enum_role = AgentRole(role.lower())
        except ValueError:
            return {"error": f"Invalid role '{role}'. Valid roles: code, research, system"}

    result = _ACTIVE_AGENTS.delegate(task, agent_name=agent_name, role=enum_role)
    return {
        "status": "success" if result.success else "failed",
        "agent_id": result.agent_id,
        "output": result.output,
        "error": result.error,
        "duration_ms": result.duration_ms
    }


def _tool_evolve_tool_code(tool_name: str = "", warning: str = "", **kwargs) -> dict:
    """Use AI to rewrite and improve a generated tool's code, handling edge cases."""
    if not tool_name:
        return {"error": "tool_name is required"}

    from james import ai as james_ai
    import json as _json
    from pathlib import Path as _Path
    import re
    if not james_ai.is_available():
        return {"error": "AI is not available to evolve the tool."}

    plugin_name = f"self_evolved_{tool_name}"
    # Calculate plugins directory path relative to this file (james/tools/registry.py -> james/plugins)
    plugins_dir = os.path.join(_Path(__file__).resolve().parent.parent, "plugins")
    target_dir = os.path.join(plugins_dir, plugin_name)
    main_py = os.path.join(target_dir, "main.py")
    manifest_json = os.path.join(target_dir, "manifest.json")

    if not os.path.exists(main_py):
        return {"error": f"Tool plugin '{plugin_name}' not found at {main_py}"}

    with open(main_py, "r", encoding="utf-8") as f:
        old_code = f.read()

    prompt = f"""You are a senior Python software engineer. You need to improve the following JAMES tool code.
The tool `{tool_name}` produced this warning or encountered this edge case during execution:
"{warning}"

Please rewrite the tool's core logic to address the warning, improve safety, and handle edge cases gracefully.
Here is the current code:
```python
{old_code}
```

Requirements:
1. Maintain the existing `register` function logic at the bottom.
2. The main tool function must be named `_tool_{tool_name}` and return a dict.
3. Handle any new imports required.
4. Output ONLY the raw Python code, without markdown formatting or code blocks. Do not wrap code in ```python tags.
"""

    messages = [
        {"role": "system", "content": "You are a Python code generator. Output only valid Python code without formatting fences."},
        {"role": "user", "content": prompt},
    ]

    try:
        from james.ai.local_llm import _call_api
        new_code = _call_api(messages, temperature=0.1)

        if not new_code:
            return {"error": "AI returned empty code."}

        # Robustly extract python code block using regex
        match = re.search(r"```python\s*(.*?)\s*```", new_code, re.DOTALL | re.IGNORECASE)
        if match:
            new_code = match.group(1).strip()
        elif new_code.startswith("```"):
            lines = new_code.split("\n")
            if "python" in lines[0].lower():
                lines = lines[1:]
            while lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            new_code = "\n".join(lines).strip()

        # Sandbox validate the code
        from james.evolution.expander import ToolSandbox
        sandbox = ToolSandbox()
        sa = sandbox.validate_code_safety(new_code)
        if not sa["safe"]:
             return {"error": f"Safety validation failed on new code: {sa['violations']}"}

        # We don't execute it right away, just syntax check
        test = sandbox.test_tool(new_code, f"_tool_{tool_name}", {})
        if not test["success"] and "missing required positional arguments" not in str(test.get("error", "")).lower():
            return {"error": f"Sandbox syntax check failed: {test.get('error')}"}

        # Save new code
        with open(main_py, "w", encoding="utf-8") as f:
            f.write(new_code)

        # Update manifest version
        if os.path.exists(manifest_json):
            with open(manifest_json, "r", encoding="utf-8") as f:
                manifest = _json.load(f)

            # Bump version naive e.g. 1.0 -> 2.0
            v = manifest.get("version", "1.0")
            try:
                major = int(float(v))
                manifest["version"] = f"{major + 1}.0"
            except ValueError:
                manifest["version"] = "2.0"

            manifest["description"] = f"{manifest.get('description', '')} (Evolved to fix warning)"
            with open(manifest_json, "w", encoding="utf-8") as f:
                _json.dump(manifest, f, indent=2)

        # Reload plugin if possible
        if _ACTIVE_PLUGINS:
            _ACTIVE_PLUGINS.unload(plugin_name)
            res = _ACTIVE_PLUGINS.load(plugin_name)
            if res.get("status") == "error":
                return {"error": f"Generated code failed to load: {res.get('error')}"}

        return {
            "status": "success",
            "tool_name": tool_name,
            "message": f"Tool '{tool_name}' successfully evolved to V2 and reloaded.",
            "new_code_length": len(new_code)
        }
    except Exception as e:
        return {"error": str(e)}

def get_registry() -> ToolRegistry:
    """Get or create the global tool registry singleton."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ToolRegistry()
    return _registry_instance

