import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from james.bootstrap import discover_tools
from james.memory.store import MemoryStore


@pytest.fixture
def memory_mock():
    return MagicMock(spec=MemoryStore)


def test_discover_tools_all_missing(memory_mock):
    with patch("shutil.which", return_value=None):
        summary = discover_tools(memory_mock)

    assert summary["tools_found"] == 0
    assert summary["tools_missing"] > 0
    assert len(summary["found"]) == 0
    assert len(summary["missing"]) == summary["tools_missing"]

    # Check that python details were still added
    memory_mock.map_set.assert_any_call("python.executable", sys.executable, category="runtime")


def test_discover_tools_happy_path(memory_mock):
    def mock_which(tool_name):
        return f"/usr/bin/{tool_name}"

    def mock_run(*args, **kwargs):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v1.2.3\n"
        return mock_result

    with patch("shutil.which", side_effect=mock_which), patch("subprocess.run", side_effect=mock_run):
        with patch("james.bootstrap._TOOL_CATALOG", {"test_category": [("test_tool", "test_tool --version")]}):
            summary = discover_tools(memory_mock)

    assert summary["tools_found"] == 1
    assert summary["tools_missing"] == 0
    assert "test_tool" in summary["found"]
    assert summary["found"]["test_tool"]["version"] == "v1.2.3"
    assert summary["found"]["test_tool"]["path"] == "/usr/bin/test_tool"

    memory_mock.map_set.assert_any_call("tool.test_tool", "/usr/bin/test_tool", category="test_category")
    memory_mock.lt_set.assert_any_call("tool.test_tool.version", "v1.2.3", category="tool_version")


def test_discover_tools_version_from_stderr(memory_mock):
    def mock_which(tool_name):
        return f"/usr/bin/{tool_name}"

    def mock_run(*args, **kwargs):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "java version 1.8.0\n"
        return mock_result

    with patch("shutil.which", side_effect=mock_which), patch("subprocess.run", side_effect=mock_run):
        with patch("james.bootstrap._TOOL_CATALOG", {"test_category": [("test_tool", "test_tool --version")]}):
            summary = discover_tools(memory_mock)

    assert summary["tools_found"] == 1
    assert summary["found"]["test_tool"]["version"] == "java version 1.8.0"


def test_discover_tools_subprocess_exception(memory_mock):
    def mock_which(tool_name):
        return f"/usr/bin/{tool_name}"

    def mock_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("cmd", 10)

    with patch("shutil.which", side_effect=mock_which), patch("subprocess.run", side_effect=mock_run):
        with patch("james.bootstrap._TOOL_CATALOG", {"test_category": [("test_tool", "test_tool --version")]}):
            summary = discover_tools(memory_mock)

    assert summary["tools_found"] == 1
    assert summary["found"]["test_tool"]["version"] == "unknown"
