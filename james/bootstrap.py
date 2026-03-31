"""
JAMES System Discovery & Bootstrap

Auto-discovers tools, paths, and capabilities on first run.
Populates the system map and seeds initial skills.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

from james.memory.store import MemoryStore
from james.skills.skill import Skill, SkillStore

logger = logging.getLogger("james.bootstrap")


# Tools to discover, grouped by category
_TOOL_CATALOG = {
    "runtime": [
        ("python", "python --version"),
        ("pip", "pip --version"),
        ("node", "node --version"),
        ("npm", "npm --version"),
        ("java", "java -version"),
    ],
    "build": [
        ("gcc", "gcc --version"),
        ("cmake", "cmake --version"),
        ("msbuild", "msbuild -version"),
        ("dotnet", "dotnet --version"),
    ],
    "vcs": [
        ("git", "git --version"),
        ("svn", "svn --version"),
    ],
    "package_manager": [
        ("choco", "choco --version"),
        ("winget", "winget --version"),
        ("scoop", "scoop --version"),
        ("pip", "pip --version"),
    ],
    "container": [
        ("docker", "docker --version"),
        ("kubectl", "kubectl version --client --short"),
    ],
    "shell": [
        ("powershell", "powershell -NoProfile -Command $PSVersionTable.PSVersion.ToString()"),
        ("pwsh", "pwsh -NoProfile -Command $PSVersionTable.PSVersion.ToString()"),
        ("bash", "bash --version"),
    ],
    "automation": [
        ("playwright", "python -m playwright --version"),
        ("autohotkey", "where AutoHotkey"),
    ],
    "editor": [
        ("code", "code --version"),
        ("vim", "vim --version"),
    ],
}

# Initial seed skills
_SEED_SKILLS = [
    # ══════════════════════════════════════════════════════════
    # CORE EXECUTION
    # ══════════════════════════════════════════════════════════
    Skill(
        id="run_command",
        name="Run Shell Command",
        description="Execute a shell command via cmd.exe or PowerShell and capture output",
        methods=["CLI"],
        steps=[
            {"action": "subprocess.run", "shell": True, "capture_output": True},
        ],
        preconditions=["Valid command string provided"],
        postconditions=["Exit code captured", "stdout/stderr captured"],
        tags=["system", "command", "shell", "core"],
    ),
    Skill(
        id="run_powershell",
        name="Run PowerShell Command",
        description="Execute a PowerShell command with -NoProfile for isolation",
        methods=["CLI"],
        steps=[
            {"action": "subprocess.run", "args": ["powershell", "-NoProfile", "-Command"]},
        ],
        preconditions=["PowerShell available"],
        postconditions=["Output captured"],
        tags=["system", "powershell", "core"],
    ),

    # ══════════════════════════════════════════════════════════
    # FILE OPERATIONS
    # ══════════════════════════════════════════════════════════
    Skill(
        id="file_read",
        name="Read File Contents",
        description="Read the contents of a text file with encoding detection",
        methods=["CLI"],
        steps=[{"action": "file_read", "target": "<path>"}],
        preconditions=["File exists at path"],
        postconditions=["Content returned as string"],
        tags=["filesystem", "read", "core"],
    ),
    Skill(
        id="file_write",
        name="Write File Contents",
        description="Write content to a file, creating parent directories if needed",
        methods=["CLI"],
        steps=[{"action": "file_write", "target": "<path>", "content": "<data>"}],
        preconditions=["Target path writable"],
        postconditions=["File exists with expected content"],
        tags=["filesystem", "write", "core"],
    ),
    Skill(
        id="file_search",
        name="Search Files",
        description="Recursively search for files matching a pattern (*.log, *.py, etc)",
        methods=["CLI", "tool_call"],
        steps=[{"action": "tool_call", "target": "file_search", "kwargs": {"path": ".", "pattern": "*"}}],
        preconditions=["Valid directory path"],
        postconditions=["List of matching files with sizes and dates"],
        tags=["filesystem", "search", "find"],
    ),
    Skill(
        id="find_large_files",
        name="Find Large Files",
        description="Find the largest files in a directory tree for cleanup",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "find_large_files", "kwargs": {"path": ".", "count": 20}}],
        preconditions=["Valid directory path"],
        postconditions=["Sorted list of largest files"],
        tags=["filesystem", "disk", "cleanup", "monitoring"],
    ),
    Skill(
        id="dir_tree",
        name="Directory Tree",
        description="Visualize directory structure as a tree",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "dir_tree", "kwargs": {"path": ".", "depth": 3}}],
        preconditions=["Valid directory path"],
        postconditions=["Tree structure dict"],
        tags=["filesystem", "visualization"],
    ),
    Skill(
        id="zip_archive",
        name="Create Zip Archive",
        description="Compress files/directories into a zip archive",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "zip_create", "kwargs": {"sources": [], "output": "archive.zip"}}],
        preconditions=["Source files exist"],
        postconditions=["Zip file created"],
        tags=["compression", "backup", "archive"],
    ),

    # ══════════════════════════════════════════════════════════
    # SYSTEM MONITORING & INFO
    # ══════════════════════════════════════════════════════════
    Skill(
        id="system_info",
        name="System Information",
        description="Get comprehensive system info: OS, CPU cores, RAM, GPU, hostname, Python version",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "system_info", "kwargs": {"detail": "full"}}],
        preconditions=["Windows OS"],
        postconditions=["System info dict with CPU, RAM, GPU, OS details"],
        tags=["system", "monitoring", "hardware", "core"],
    ),
    Skill(
        id="disk_usage",
        name="Disk Space Analysis",
        description="Check disk space usage across all drives",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "disk_usage"}],
        preconditions=["Windows OS"],
        postconditions=["Drive usage with used/free/total GB"],
        tags=["system", "disk", "monitoring", "storage"],
    ),
    Skill(
        id="memory_usage",
        name="RAM Usage Check",
        description="Check current RAM usage, free memory, and usage percentage",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "memory_usage"}],
        preconditions=["Windows OS"],
        postconditions=["RAM total, free, used, and percentage"],
        tags=["system", "memory", "monitoring", "performance"],
    ),
    Skill(
        id="cpu_info",
        name="CPU Performance",
        description="Get CPU name, core count, clock speed, and current load percentage",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "cpu_info"}],
        preconditions=["Windows OS"],
        postconditions=["CPU details and load percentage"],
        tags=["system", "cpu", "monitoring", "performance"],
    ),
    Skill(
        id="process_list",
        name="List Running Processes",
        description="List all running processes or filter by name",
        methods=["CLI"],
        steps=[{"action": "tasklist /FO CSV /NH", "parse": "csv"}],
        preconditions=["Windows OS"],
        postconditions=["Process list with name, PID, memory"],
        tags=["system", "process", "monitoring"],
    ),
    Skill(
        id="uptime",
        name="System Uptime",
        description="Get system uptime and last boot time",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "uptime"}],
        preconditions=["Windows OS"],
        postconditions=["Last boot time and current time"],
        tags=["system", "uptime", "monitoring"],
    ),

    # ══════════════════════════════════════════════════════════
    # NETWORK & HTTP
    # ══════════════════════════════════════════════════════════
    Skill(
        id="http_get",
        name="HTTP GET Request",
        description="Make an HTTP GET request and return status, headers, and body",
        methods=["API", "tool_call"],
        steps=[{"action": "tool_call", "target": "http_get", "kwargs": {"url": "<url>"}}],
        preconditions=["URL is valid", "Network available"],
        postconditions=["Response status code, headers, and body captured"],
        tags=["network", "http", "api", "web", "core"],
    ),
    Skill(
        id="http_post",
        name="HTTP POST Request",
        description="Make an HTTP POST request with JSON body",
        methods=["API", "tool_call"],
        steps=[{"action": "tool_call", "target": "http_post", "kwargs": {"url": "<url>", "body": {}}}],
        preconditions=["URL is valid", "Network available"],
        postconditions=["Response status and body captured"],
        tags=["network", "http", "api", "web"],
    ),
    Skill(
        id="download_file",
        name="Download File from URL",
        description="Download a file from the internet to a local path",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "download_file", "kwargs": {"url": "<url>", "output": "<path>"}}],
        preconditions=["URL is valid", "Network available", "Output path writable"],
        postconditions=["File downloaded to specified path"],
        tags=["network", "download", "web"],
    ),
    Skill(
        id="network_diagnostic",
        name="Network Diagnostics",
        description="Check network interfaces, IP addresses, and internet connectivity",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "network_info"}],
        preconditions=["Windows OS"],
        postconditions=["Network interfaces list, local IP, internet status"],
        tags=["network", "diagnostic", "connectivity"],
    ),
    Skill(
        id="dns_lookup",
        name="DNS Lookup",
        description="Resolve a hostname to IP addresses",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "dns_lookup", "kwargs": {"hostname": "<domain>"}}],
        preconditions=["Network available"],
        postconditions=["IP addresses for domain"],
        tags=["network", "dns", "diagnostic"],
    ),
    Skill(
        id="port_check",
        name="Port Check",
        description="Check if a TCP port is open on a host",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "port_check", "kwargs": {"host": "<host>", "port": 0}}],
        preconditions=["Network available"],
        postconditions=["Port open/closed status"],
        tags=["network", "port", "firewall", "diagnostic"],
    ),
    Skill(
        id="ping_host",
        name="Ping Host",
        description="Ping a host to check latency and reachability",
        methods=["CLI"],
        steps=[{"action": "powershell", "target": "Test-Connection -ComputerName <host> -Count 4 | Select-Object Address,ResponseTime,StatusCode | ConvertTo-Json"}],
        preconditions=["Network available"],
        postconditions=["Ping results with latency"],
        tags=["network", "ping", "diagnostic", "latency"],
    ),

    # ══════════════════════════════════════════════════════════
    # PACKAGE MANAGEMENT
    # ══════════════════════════════════════════════════════════
    Skill(
        id="pip_install",
        name="Install Python Package",
        description="Install a Python package via pip into the active venv",
        methods=["CLI"],
        steps=[{"action": "pip install <package> --quiet"}],
        preconditions=["pip available", "Network access"],
        postconditions=["Package importable"],
        tags=["package", "python", "dependency"],
    ),
    Skill(
        id="pip_list",
        name="List Python Packages",
        description="List all installed Python packages with versions",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "installed_packages"}],
        preconditions=["pip available"],
        postconditions=["Package list with name and version"],
        tags=["package", "python", "inspection"],
    ),
    Skill(
        id="npm_install",
        name="Install Node.js Package",
        description="Install a Node.js package via npm",
        methods=["CLI"],
        steps=[{"action": "command", "target": "npm install <package>"}],
        preconditions=["npm available"],
        postconditions=["Package in node_modules"],
        tags=["package", "node", "javascript", "dependency"],
    ),

    # ══════════════════════════════════════════════════════════
    # VERSION CONTROL
    # ══════════════════════════════════════════════════════════
    Skill(
        id="git_status",
        name="Git Repository Status",
        description="Get the current status of a git repository",
        methods=["CLI"],
        steps=[{"action": "git status --porcelain"}],
        preconditions=["git available", "Inside a git repository"],
        postconditions=["Status output captured"],
        tags=["vcs", "git", "repository"],
    ),
    Skill(
        id="git_commit",
        name="Git Commit Changes",
        description="Stage all changes and create a commit with a message",
        methods=["CLI"],
        steps=[
            {"action": "command", "target": "git add -A"},
            {"action": "command", "target": 'git commit -m "<message>"'},
        ],
        preconditions=["git available", "Changes to commit"],
        postconditions=["Commit created"],
        tags=["vcs", "git", "commit"],
    ),
    Skill(
        id="git_log",
        name="Git History",
        description="Get recent commit history with details",
        methods=["CLI"],
        steps=[{"action": "command", "target": "git log --oneline -20"}],
        preconditions=["git available", "Inside a git repository"],
        postconditions=["Commit list captured"],
        tags=["vcs", "git", "history"],
    ),

    # ══════════════════════════════════════════════════════════
    # WINDOWS ADMINISTRATION
    # ══════════════════════════════════════════════════════════
    Skill(
        id="windows_services",
        name="Manage Windows Services",
        description="List, start, stop, or restart Windows services",
        methods=["tool_call", "CLI"],
        steps=[{"action": "tool_call", "target": "windows_services", "kwargs": {"status": "all"}}],
        preconditions=["Windows OS", "Admin rights for start/stop"],
        postconditions=["Service status list"],
        tags=["windows", "service", "admin"],
    ),
    Skill(
        id="installed_programs",
        name="List Installed Programs",
        description="List all programs installed on the machine",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "installed_programs"}],
        preconditions=["Windows OS"],
        postconditions=["Program list with name, version, publisher"],
        tags=["windows", "software", "inventory"],
    ),
    Skill(
        id="event_log",
        name="Read Event Logs",
        description="Read recent Windows event log entries (System, Application, Security)",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "event_log", "kwargs": {"log": "System", "count": 20}}],
        preconditions=["Windows OS"],
        postconditions=["Event entries with time, type, source, message"],
        tags=["windows", "logs", "diagnostic", "monitoring"],
    ),
    Skill(
        id="scheduled_tasks",
        name="View Scheduled Tasks",
        description="List Windows scheduled tasks (enabled ones)",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "scheduled_tasks"}],
        preconditions=["Windows OS"],
        postconditions=["Task list with name, path, state"],
        tags=["windows", "scheduler", "automation"],
    ),
    Skill(
        id="startup_items",
        name="Startup Programs",
        description="List programs that run on Windows startup",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "startup_items"}],
        preconditions=["Windows OS"],
        postconditions=["Startup program list"],
        tags=["windows", "startup", "boot", "security"],
    ),

    # ══════════════════════════════════════════════════════════
    # SECURITY & INTEGRITY
    # ══════════════════════════════════════════════════════════
    Skill(
        id="file_hash",
        name="File Hash/Checksum",
        description="Compute SHA256 or MD5 hash of a file for integrity verification",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "file_hash", "kwargs": {"path": "<file>", "algorithm": "sha256"}}],
        preconditions=["File exists"],
        postconditions=["Hash string returned"],
        tags=["security", "hash", "integrity", "checksum"],
    ),
    Skill(
        id="check_open_ports",
        name="Scan Open Ports",
        description="Check which common ports are open on a host",
        methods=["CLI"],
        steps=[{"action": "powershell", "target": "1..1024 | ForEach-Object { $p=$_; try { $c=New-Object System.Net.Sockets.TcpClient; $c.Connect('localhost',$p); \"Port $p OPEN\"; $c.Close() } catch {} }"}],
        preconditions=["Network available"],
        postconditions=["List of open ports"],
        tags=["security", "network", "ports", "scan"],
    ),
    Skill(
        id="firewall_status",
        name="Firewall Status",
        description="Check Windows Firewall status and profile settings",
        methods=["CLI"],
        steps=[{"action": "powershell", "target": "Get-NetFirewallProfile | Select-Object Name,Enabled | ConvertTo-Json"}],
        preconditions=["Windows OS"],
        postconditions=["Firewall status per profile"],
        tags=["security", "firewall", "windows"],
    ),

    # ══════════════════════════════════════════════════════════
    # DATA & TEXT PROCESSING
    # ══════════════════════════════════════════════════════════
    Skill(
        id="json_validate",
        name="Validate JSON",
        description="Validate and pretty-print JSON data",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "json_validate", "kwargs": {"data": "<json_string>"}}],
        preconditions=["Input string provided"],
        postconditions=["Validation result and formatted output"],
        tags=["data", "json", "validation"],
    ),
    Skill(
        id="clipboard_ops",
        name="Clipboard Operations",
        description="Get or set Windows clipboard content",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "clipboard_get"}],
        preconditions=["Windows OS"],
        postconditions=["Clipboard text content"],
        tags=["clipboard", "windows", "utility"],
    ),

    # ══════════════════════════════════════════════════════════
    # WEB INTELLIGENCE (browsing/scraping)
    # ══════════════════════════════════════════════════════════
    Skill(
        id="web_browse",
        name="Browse Web Page",
        description="Browse a web page and extract clean readable text, links, images, and metadata. Like having a browser that returns structured data.",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "web_browse", "kwargs": {"url": "<url>", "extract": "all"}}],
        preconditions=["Network available", "Valid URL"],
        postconditions=["Page text, title, links, images, headings extracted"],
        tags=["web", "browse", "scrape", "read", "core"],
    ),
    Skill(
        id="web_search",
        name="Search the Web",
        description="Search the internet using DuckDuckGo — returns titles, URLs, and snippets. No API key needed.",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "web_search", "kwargs": {"query": "<search terms>", "count": 10}}],
        preconditions=["Network available"],
        postconditions=["List of search results with title, URL, snippet"],
        tags=["web", "search", "internet", "google", "research", "core"],
    ),
    Skill(
        id="web_scrape_tables",
        name="Scrape Tables from Page",
        description="Extract HTML tables from a web page as structured data with headers and rows",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "web_extract_tables", "kwargs": {"url": "<url>"}}],
        preconditions=["Network available", "Valid URL"],
        postconditions=["List of tables with headers and row data"],
        tags=["web", "scrape", "table", "data", "extract"],
    ),
    Skill(
        id="web_extract_all_links",
        name="Extract Page Links",
        description="Extract all links from a web page, categorized as internal vs external",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "web_extract_links", "kwargs": {"url": "<url>"}}],
        preconditions=["Network available", "Valid URL"],
        postconditions=["Internal and external links with text"],
        tags=["web", "links", "scrape", "seo"],
    ),
    Skill(
        id="web_crawl_site",
        name="Crawl Website",
        description="Crawl a website following links up to a depth limit, collecting page titles and word counts",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "web_crawl", "kwargs": {"start_url": "<url>", "max_pages": 10, "depth": 2}}],
        preconditions=["Network available"],
        postconditions=["List of crawled pages with metadata"],
        tags=["web", "crawl", "spider", "sitemap"],
    ),
    Skill(
        id="web_read_article",
        name="Read Article (Reader Mode)",
        description="Extract the main article content from a page, stripping ads, navigation, and sidebars — like reader mode",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "web_read_article", "kwargs": {"url": "<url>"}}],
        preconditions=["Network available"],
        postconditions=["Clean article text with title, author, date"],
        tags=["web", "article", "read", "content", "news"],
    ),
    Skill(
        id="web_monitor_page",
        name="Monitor Page for Changes",
        description="Check if a web page has changed since the last visit using content hashing",
        methods=["tool_call"],
        steps=[{"action": "tool_call", "target": "web_page_diff", "kwargs": {"url": "<url>"}}],
        preconditions=["Network available"],
        postconditions=["Hash value and change status"],
        tags=["web", "monitor", "diff", "watch", "changes"],
    ),
]



def discover_tools(memory: MemoryStore) -> dict:
    """
    Auto-discover available tools and populate the system map.
    Returns a summary dict of findings.
    """
    logger.info("Starting system tool discovery...")
    found = {}
    missing = {}

    for category, tools in _TOOL_CATALOG.items():
        for tool_name, version_cmd in tools:
            # Check if on PATH
            tool_path = shutil.which(tool_name)
            if tool_path:
                # Get version
                version = "unknown"
                try:
                    result = subprocess.run(
                        version_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        version = result.stdout.strip().splitlines()[0][:100]
                    elif result.stderr.strip():
                        # Some tools (java) output version to stderr
                        version = result.stderr.strip().splitlines()[0][:100]
                except Exception:
                    pass

                memory.map_set(
                    f"tool.{tool_name}",
                    tool_path,
                    category=category,
                )
                memory.lt_set(
                    f"tool.{tool_name}.version",
                    version,
                    category="tool_version",
                )
                found[tool_name] = {"path": tool_path, "version": version, "category": category}
                logger.info(f"  Found: {tool_name} -> {tool_path} ({version})")
            else:
                missing[tool_name] = category

    # Discover Python environment
    python_path = sys.executable
    memory.map_set("python.executable", python_path, category="runtime")
    memory.map_set("python.version", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", category="runtime")

    venv = os.environ.get("VIRTUAL_ENV", "")
    if venv:
        memory.map_set("python.venv", venv, category="runtime")

    # Discover OS info
    memory.map_set("os.name", os.name, category="system")
    memory.map_set("os.platform", sys.platform, category="system")

    try:
        import platform
        memory.map_set("os.version", platform.version(), category="system")
        memory.map_set("os.machine", platform.machine(), category="system")
        memory.map_set("os.node", platform.node(), category="system")
    except Exception:
        pass

    summary = {
        "tools_found": len(found),
        "tools_missing": len(missing),
        "found": found,
        "missing": list(missing.keys()),
    }

    memory.lt_set("bootstrap.discovery", summary, category="system")
    logger.info(f"Discovery complete: {len(found)} found, {len(missing)} missing")
    return summary


def seed_skills(skill_store: SkillStore) -> int:
    """
    Seed the skill store with initial core skills.
    Returns the number of skills seeded.
    """
    seeded = 0
    for skill in _SEED_SKILLS:
        if not skill_store.get(skill.id):
            skill_store.create(skill)
            seeded += 1
            logger.info(f"  Seeded skill: {skill.id} ({skill.name})")
    return seeded


def run_bootstrap(memory: MemoryStore, skill_store: SkillStore) -> dict:
    """
    Full bootstrap: discover system + seed skills.
    Returns combined summary.
    """
    logger.info("=" * 50)
    logger.info("JAMES Bootstrap: System Discovery & Skill Seeding")
    logger.info("=" * 50)

    discovery = discover_tools(memory)
    skills_seeded = seed_skills(skill_store)

    summary = {
        **discovery,
        "skills_seeded": skills_seeded,
        "total_skills": skill_store.count,
    }

    memory.lt_set("bootstrap.last_run", summary, category="system")
    logger.info(f"Bootstrap complete: {discovery['tools_found']} tools, {skills_seeded} skills seeded")
    return summary
