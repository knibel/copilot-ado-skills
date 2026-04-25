"""
Tests for git_tools module.

All tests use temporary directories and do NOT require a remote repository.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import git as gitpython

from ado_git_skill.tools import git_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo_dir(tmp_path: Path) -> Path:
    """Create a temporary git repository with an initial commit."""
    repo = gitpython.Repo.init(str(tmp_path))
    # Configure identity so commits work in CI
    with repo.config_writer() as cfg:
        cfg.set_value("user", "name", "Test User")
        cfg.set_value("user", "email", "test@example.com")

    readme = tmp_path / "README.md"
    readme.write_text("# Test repo\n")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    return tmp_path


# ---------------------------------------------------------------------------
# clone_repository
# ---------------------------------------------------------------------------


def test_clone_repository(repo_dir: Path, tmp_path: Path) -> None:
    dest = str(tmp_path / "clone")
    result = git_tools.clone_repository(str(repo_dir), dest)
    assert result["status"] == "cloned"
    assert Path(result["path"]).exists()
    assert "branch" in result


@patch("ado_git_skill.tools.git_tools.Repo.clone_from")
@patch("ado_git_skill.tools.git_tools.get_git_environment")
def test_clone_repository_uses_noninteractive_git_env(
    mock_get_git_environment: MagicMock,
    mock_clone_from: MagicMock,
    tmp_path: Path,
) -> None:
    dest = str(tmp_path / "clone")
    mock_get_git_environment.return_value = {
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
    }
    repo = MagicMock()
    repo.active_branch.name = "main"
    mock_clone_from.return_value = repo

    git_tools.clone_repository("https://dev.azure.com/org/project/_git/repo", dest)

    mock_get_git_environment.assert_called_once_with(
        "https://dev.azure.com/org/project/_git/repo"
    )
    mock_clone_from.assert_called_once_with(
        "https://dev.azure.com/org/project/_git/repo",
        dest,
        env=mock_get_git_environment.return_value,
    )


# ---------------------------------------------------------------------------
# checkout_branch / create_branch
# ---------------------------------------------------------------------------


def test_checkout_branch_creates_new(repo_dir: Path) -> None:
    result = git_tools.checkout_branch(str(repo_dir), "feature/test", create=True)
    assert result["status"] == "checked_out"
    assert result["branch"] == "feature/test"


def test_create_branch(repo_dir: Path) -> None:
    result = git_tools.create_branch(str(repo_dir), "dev")
    assert result["status"] == "created"
    assert result["branch"] == "dev"


def test_checkout_nonexistent_raises(repo_dir: Path) -> None:
    with pytest.raises(gitpython.GitCommandError):
        git_tools.checkout_branch(str(repo_dir), "does-not-exist", create=False)


# ---------------------------------------------------------------------------
# commit_changes
# ---------------------------------------------------------------------------


def test_commit_changes(repo_dir: Path) -> None:
    new_file = repo_dir / "hello.txt"
    new_file.write_text("hello\n")
    result = git_tools.commit_changes(str(repo_dir), "Add hello.txt")
    assert result["status"] == "committed"
    assert len(result["sha"]) == 40
    assert result["message"] == "Add hello.txt"


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


def test_get_status_clean(repo_dir: Path) -> None:
    result = git_tools.get_status(str(repo_dir))
    assert "branch" in result
    assert isinstance(result["modified"], list)
    assert isinstance(result["untracked"], list)


def test_get_status_untracked(repo_dir: Path) -> None:
    (repo_dir / "untracked.txt").write_text("hi\n")
    result = git_tools.get_status(str(repo_dir))
    assert "untracked.txt" in result["untracked"]


# ---------------------------------------------------------------------------
# get_diff
# ---------------------------------------------------------------------------


def test_get_diff_empty_on_clean_repo(repo_dir: Path) -> None:
    result = git_tools.get_diff(str(repo_dir))
    assert result["diff"] == ""


def test_get_diff_shows_changes(repo_dir: Path) -> None:
    (repo_dir / "README.md").write_text("# Changed\n")
    result = git_tools.get_diff(str(repo_dir))
    assert "README.md" in result["diff"]


# ---------------------------------------------------------------------------
# list_branches
# ---------------------------------------------------------------------------


def test_list_branches(repo_dir: Path) -> None:
    git_tools.create_branch(str(repo_dir), "feature/x")
    result = git_tools.list_branches(str(repo_dir))
    assert "feature/x" in result["local"]
    assert "current" in result


# ---------------------------------------------------------------------------
# get_log
# ---------------------------------------------------------------------------


def test_get_log(repo_dir: Path) -> None:
    result = git_tools.get_log(str(repo_dir), max_count=5)
    assert len(result["commits"]) >= 1
    commit = result["commits"][0]
    assert "sha" in commit
    assert "message" in commit


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------


def test_invalid_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a git repository"):
        git_tools.get_status(str(tmp_path))
