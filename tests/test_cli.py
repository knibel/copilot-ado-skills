"""
Tests for the one-shot CLI entry point (ado_git_skill.cli).
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from ado_git_skill import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(function_name: str, params: dict, *, stdin_text: str | None = None) -> dict:
    """Call cli.main and return the parsed JSON that was printed to stdout."""
    if stdin_text is None:
        stdin_text = json.dumps(params)

    captured = StringIO()
    with (
        patch("sys.stdin", StringIO(stdin_text)),
        patch("sys.stdout", captured),
    ):
        cli.main([function_name])

    return json.loads(captured.getvalue())


# ---------------------------------------------------------------------------
# _dispatch – unknown function
# ---------------------------------------------------------------------------

def test_dispatch_unknown_function() -> None:
    with pytest.raises(ValueError, match="Unknown function"):
        cli._dispatch("no_such_function", {})


# ---------------------------------------------------------------------------
# main – help flag
# ---------------------------------------------------------------------------

def test_main_help_exits_zero(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0


def test_main_no_args_exits_nonzero(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# main – invalid JSON input
# ---------------------------------------------------------------------------

def test_main_invalid_json_exits_one(capsys: pytest.CaptureFixture) -> None:
    with (
        patch("sys.stdin", StringIO("not valid json")),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli.main(["get_status"])
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# main – empty stdin treated as empty params
# ---------------------------------------------------------------------------

def test_main_empty_stdin_dispatches(tmp_path: Path) -> None:
    """Empty stdin should be treated as {} parameters."""
    import git as gitpython

    repo = gitpython.Repo.init(str(tmp_path))
    with repo.config_writer() as cfg:
        cfg.set_value("user", "name", "Test")
        cfg.set_value("user", "email", "test@example.com")
    (tmp_path / "f.txt").write_text("x")
    repo.index.add(["f.txt"])
    repo.index.commit("init")

    captured = StringIO()
    with (
        patch("sys.stdin", StringIO("")),
        patch("sys.stdout", captured),
    ):
        cli.main(["get_status"])

    result = json.loads(captured.getvalue())
    assert "error" in result  # working_dir is missing → error, not crash


# ---------------------------------------------------------------------------
# main – successful dispatch to git tool
# ---------------------------------------------------------------------------

def test_main_get_status_success(tmp_path: Path) -> None:
    import git as gitpython

    repo = gitpython.Repo.init(str(tmp_path))
    with repo.config_writer() as cfg:
        cfg.set_value("user", "name", "Test")
        cfg.set_value("user", "email", "test@example.com")
    (tmp_path / "f.txt").write_text("hello")
    repo.index.add(["f.txt"])
    repo.index.commit("init")

    result = _run("get_status", {"working_dir": str(tmp_path)})
    assert "branch" in result
    assert "staged" in result


# ---------------------------------------------------------------------------
# main – tool exception is returned as error JSON, not a crash
# ---------------------------------------------------------------------------

def test_main_tool_error_returned_as_json(tmp_path: Path) -> None:
    result = _run("get_status", {"working_dir": str(tmp_path / "nonexistent")})
    assert "error" in result


# ---------------------------------------------------------------------------
# main – dispatch routes to search_tools
# ---------------------------------------------------------------------------

def test_main_dispatch_to_search_tool(mocker) -> None:
    mock_result = {"repositories": []}
    mocker.patch(
        "ado_git_skill.tools.search_tools.list_repositories",
        return_value=mock_result,
    )
    result = _run("list_repositories", {"project": "MyProject"})
    assert result == mock_result


# ---------------------------------------------------------------------------
# main – dispatch routes to pr_tools
# ---------------------------------------------------------------------------

def test_main_dispatch_to_pr_tool(mocker) -> None:
    mock_result = {"pull_requests": []}
    mocker.patch(
        "ado_git_skill.tools.pr_tools.list_pull_requests",
        return_value=mock_result,
    )
    result = _run(
        "list_pull_requests",
        {"project": "MyProject", "repository": "my-repo"},
    )
    assert result == mock_result
