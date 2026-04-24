"""
Tests for pr_tools module.

Uses pytest-mock to stub the Azure DevOps SDK so no real network calls are made.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ado_git_skill.tools import pr_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pr(
    pr_id: int = 1,
    title: str = "My PR",
    status: str = "active",
    source: str = "refs/heads/feature",
    target: str = "refs/heads/main",
    is_draft: bool = False,
) -> MagicMock:
    pr = MagicMock()
    pr.pull_request_id = pr_id
    pr.title = title
    pr.description = "A description"
    pr.status = status
    pr.source_ref_name = source
    pr.target_ref_name = target
    pr.is_draft = is_draft
    pr.created_by = MagicMock(__str__=lambda s: "User A")
    pr.repository = MagicMock(remote_url="https://dev.azure.com/org/proj/_git/repo")
    return pr


def _make_thread(
    thread_id: int = 10,
    content: str = "Please fix this.",
    file_path: str = "src/main.py",
    start_line: int = 5,
) -> MagicMock:
    comment = MagicMock()
    comment.id = 1
    comment.author = MagicMock(__str__=lambda s: "Reviewer")
    comment.content = content
    comment.comment_type = 1
    comment.published_date = None

    thread = MagicMock()
    thread.id = thread_id
    thread.status = "active"
    thread.is_deleted = False
    thread.comments = [comment]

    tc = MagicMock()
    tc.file_path = file_path
    tc.right_file_start = MagicMock(line=start_line, offset=0)
    tc.right_file_end = MagicMock(line=start_line, offset=10)
    thread.thread_context = tc
    return thread


# ---------------------------------------------------------------------------
# create_pull_request
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.pr_tools.get_connection")
def test_create_pull_request(mock_get_conn: MagicMock) -> None:
    pr = _make_pr()
    git_client = MagicMock()
    git_client.create_pull_request.return_value = pr
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = pr_tools.create_pull_request(
        project="MyProject",
        repository="my-repo",
        title="My PR",
        source_branch="feature",
        target_branch="main",
    )

    assert result["pull_request_id"] == 1
    assert result["title"] == "My PR"
    assert result["source_branch"] == "feature"
    assert result["target_branch"] == "main"
    git_client.create_pull_request.assert_called_once()


@patch("ado_git_skill.tools.pr_tools.get_connection")
def test_create_pull_request_no_source_raises(mock_get_conn: MagicMock) -> None:
    with pytest.raises(ValueError, match="source_branch"):
        pr_tools.create_pull_request(
            project="P",
            repository="R",
            title="T",
        )


# ---------------------------------------------------------------------------
# list_pull_requests
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.pr_tools.get_connection")
def test_list_pull_requests(mock_get_conn: MagicMock) -> None:
    prs = [_make_pr(1), _make_pr(2, title="Second PR")]
    git_client = MagicMock()
    git_client.get_pull_requests.return_value = prs
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = pr_tools.list_pull_requests(project="P", repository="R")

    assert len(result["pull_requests"]) == 2
    assert result["pull_requests"][0]["title"] == "My PR"
    assert result["pull_requests"][1]["title"] == "Second PR"


# ---------------------------------------------------------------------------
# get_pull_request
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.pr_tools.get_connection")
def test_get_pull_request(mock_get_conn: MagicMock) -> None:
    pr = _make_pr(42, title="Special PR")
    git_client = MagicMock()
    git_client.get_pull_request.return_value = pr
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = pr_tools.get_pull_request(project="P", repository="R", pull_request_id=42)

    assert result["pull_request_id"] == 42
    assert result["title"] == "Special PR"


# ---------------------------------------------------------------------------
# get_pr_comments
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.pr_tools.get_connection")
def test_get_pr_comments(mock_get_conn: MagicMock) -> None:
    threads = [_make_thread()]
    git_client = MagicMock()
    git_client.get_threads.return_value = threads
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = pr_tools.get_pr_comments(project="P", repository="R", pull_request_id=1)

    assert len(result["threads"]) == 1
    thread = result["threads"][0]
    assert thread["thread_id"] == 10
    assert thread["thread_context"]["file_path"] == "src/main.py"
    assert thread["comments"][0]["content"] == "Please fix this."


# ---------------------------------------------------------------------------
# reply_to_pr_comment
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.pr_tools.get_connection")
def test_reply_to_pr_comment(mock_get_conn: MagicMock) -> None:
    reply = MagicMock()
    reply.id = 2
    reply.author = MagicMock(__str__=lambda s: "Agent")
    reply.content = "Done, fixed!"
    reply.comment_type = 1
    reply.published_date = None

    git_client = MagicMock()
    git_client.create_comment.return_value = reply
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = pr_tools.reply_to_pr_comment(
        project="P",
        repository="R",
        pull_request_id=1,
        thread_id=10,
        content="Done, fixed!",
    )

    assert result["comment_id"] == 2
    assert result["content"] == "Done, fixed!"


# ---------------------------------------------------------------------------
# apply_pr_suggestion
# ---------------------------------------------------------------------------


def test_apply_pr_suggestion(tmp_path: Path) -> None:
    import git as gitpython

    repo = gitpython.Repo.init(str(tmp_path))
    with repo.config_writer() as cfg:
        cfg.set_value("user", "name", "Test")
        cfg.set_value("user", "email", "t@t.com")

    source = tmp_path / "src" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text("def foo():\n    pass\n\ndef bar():\n    return 1\n")
    repo.index.add(["src/main.py"])
    repo.index.commit("Initial")

    result = pr_tools.apply_pr_suggestion(
        working_dir=str(tmp_path),
        file_path="src/main.py",
        start_line=2,
        end_line=2,
        suggested_content="    return 42",
        commit_message="Apply suggestion",
    )

    assert result["status"] == "applied"
    assert result["file"] == "src/main.py"
    assert "sha" in result
    # Verify the file was actually changed
    content = source.read_text()
    assert "return 42" in content


def test_apply_pr_suggestion_invalid_range(tmp_path: Path) -> None:
    import git as gitpython

    repo = gitpython.Repo.init(str(tmp_path))
    with repo.config_writer() as cfg:
        cfg.set_value("user", "name", "Test")
        cfg.set_value("user", "email", "t@t.com")

    f = tmp_path / "f.py"
    f.write_text("line1\nline2\n")
    repo.index.add(["f.py"])
    repo.index.commit("Initial")

    with pytest.raises(ValueError, match="Invalid line range"):
        pr_tools.apply_pr_suggestion(
            working_dir=str(tmp_path),
            file_path="f.py",
            start_line=10,
            end_line=20,
            suggested_content="x",
        )
