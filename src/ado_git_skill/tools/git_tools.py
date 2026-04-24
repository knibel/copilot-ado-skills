"""
Local git operation tools for Azure DevOps repositories.

All tools operate on a local working directory and communicate with the
remote Azure DevOps repository through standard ``git`` commands executed
via GitPython.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import git
from git import InvalidGitRepositoryError, Repo


def _repo(working_dir: str) -> Repo:
    """Return a :class:`git.Repo` for *working_dir*, raising a clear error when missing."""
    try:
        return Repo(working_dir)
    except InvalidGitRepositoryError as exc:
        raise ValueError(f"'{working_dir}' is not a git repository.") from exc


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def clone_repository(
    remote_url: str,
    destination: str,
    branch: str | None = None,
) -> dict[str, Any]:
    """
    Clone a remote Azure DevOps git repository to a local directory.

    Parameters
    ----------
    remote_url:
        HTTPS or SSH URL of the remote repository.
    destination:
        Local path where the repository should be cloned.
    branch:
        Optional branch to check out after cloning.

    Returns
    -------
    dict
        ``{"status": "cloned", "path": destination, "branch": active_branch}``
    """
    kwargs: dict[str, Any] = {}
    if branch:
        kwargs["branch"] = branch

    repo = Repo.clone_from(remote_url, destination, **kwargs)
    try:
        active_branch = repo.active_branch.name
    except TypeError:
        active_branch = "HEAD"

    return {"status": "cloned", "path": str(destination), "branch": active_branch}


def checkout_branch(
    working_dir: str,
    branch: str,
    create: bool = False,
) -> dict[str, Any]:
    """
    Check out a branch in an existing local repository.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.
    branch:
        Branch name to check out.
    create:
        When ``True``, create the branch if it does not already exist.

    Returns
    -------
    dict
        ``{"status": "checked_out", "branch": branch}``
    """
    repo = _repo(working_dir)
    if create:
        # Create from the current HEAD if the branch does not already exist
        if branch not in [h.name for h in repo.heads]:
            repo.create_head(branch)
    repo.git.checkout(branch)
    return {"status": "checked_out", "branch": branch}


def create_branch(
    working_dir: str,
    branch: str,
    base_branch: str | None = None,
) -> dict[str, Any]:
    """
    Create a new local branch.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.
    branch:
        Name for the new branch.
    base_branch:
        Branch or commit to branch off.  Defaults to the current HEAD.

    Returns
    -------
    dict
        ``{"status": "created", "branch": branch}``
    """
    repo = _repo(working_dir)
    base = repo.heads[base_branch] if base_branch else repo.head.commit
    repo.create_head(branch, commit=base)
    return {"status": "created", "branch": branch}


def commit_changes(
    working_dir: str,
    message: str,
    add_all: bool = True,
) -> dict[str, Any]:
    """
    Stage and commit local changes.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.
    message:
        Commit message.
    add_all:
        When ``True`` (default), stage all modified and new-tracked files
        before committing (equivalent to ``git add -A``).

    Returns
    -------
    dict
        ``{"status": "committed", "sha": commit_sha, "message": message}``
    """
    repo = _repo(working_dir)
    if add_all:
        repo.git.add("-A")
    commit = repo.index.commit(message)
    return {"status": "committed", "sha": commit.hexsha, "message": message}


def push_changes(
    working_dir: str,
    remote: str = "origin",
    branch: str | None = None,
    set_upstream: bool = True,
) -> dict[str, Any]:
    """
    Push committed changes to the remote repository.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.
    remote:
        Name of the git remote (default: ``origin``).
    branch:
        Branch to push.  Defaults to the currently checked-out branch.
    set_upstream:
        When ``True``, add ``--set-upstream`` to the push command so that
        newly created local branches are tracked automatically.

    Returns
    -------
    dict
        ``{"status": "pushed", "remote": remote, "branch": branch}``
    """
    repo = _repo(working_dir)
    target_branch = branch or repo.active_branch.name
    push_args = [remote, f"refs/heads/{target_branch}:refs/heads/{target_branch}"]
    if set_upstream:
        push_args = ["-u"] + push_args
    repo.git.push(*push_args)
    return {"status": "pushed", "remote": remote, "branch": target_branch}


def pull_changes(
    working_dir: str,
    remote: str = "origin",
    branch: str | None = None,
) -> dict[str, Any]:
    """
    Pull the latest changes from the remote repository.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.
    remote:
        Name of the git remote (default: ``origin``).
    branch:
        Remote branch to pull.  Defaults to the currently checked-out branch.

    Returns
    -------
    dict
        ``{"status": "pulled", "remote": remote, "branch": branch}``
    """
    repo = _repo(working_dir)
    target_branch = branch or repo.active_branch.name
    repo.git.pull(remote, target_branch)
    return {"status": "pulled", "remote": remote, "branch": target_branch}


def get_status(working_dir: str) -> dict[str, Any]:
    """
    Return the working-tree status of the local repository.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.

    Returns
    -------
    dict
        Contains ``branch``, ``modified``, ``staged``, ``untracked`` lists.
    """
    repo = _repo(working_dir)
    try:
        branch = repo.active_branch.name
    except TypeError:
        branch = "HEAD (detached)"

    modified = [item.a_path for item in repo.index.diff(None)]
    staged = [item.a_path for item in repo.index.diff("HEAD")]
    untracked = repo.untracked_files

    return {
        "branch": branch,
        "modified": modified,
        "staged": staged,
        "untracked": list(untracked),
    }


def get_diff(
    working_dir: str,
    base: str = "HEAD",
    target: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    """
    Return a unified diff of changes in the repository.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.
    base:
        Base ref (default: ``HEAD``).
    target:
        Target ref.  When omitted, the diff is between *base* and the
        working tree.
    file_path:
        Restrict the diff to a specific file path (optional).

    Returns
    -------
    dict
        ``{"diff": "<unified diff text>"}``
    """
    repo = _repo(working_dir)
    args: list[str] = [base]
    if target:
        args.append(target)
    if file_path:
        args += ["--", file_path]
    diff_text = repo.git.diff(*args)
    return {"diff": diff_text}


def list_branches(working_dir: str) -> dict[str, Any]:
    """
    List all local and remote branches in the repository.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.

    Returns
    -------
    dict
        ``{"local": [...], "remote": [...], "current": "..."}``
    """
    repo = _repo(working_dir)
    local = [h.name for h in repo.heads]
    remote = [r.name for r in repo.remotes[0].refs] if repo.remotes else []
    try:
        current = repo.active_branch.name
    except TypeError:
        current = "HEAD (detached)"
    return {"local": local, "remote": remote, "current": current}


def get_log(
    working_dir: str,
    max_count: int = 20,
    branch: str | None = None,
) -> dict[str, Any]:
    """
    Return the recent commit log.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.
    max_count:
        Maximum number of commits to return (default: 20).
    branch:
        Branch to inspect.  Defaults to the current branch.

    Returns
    -------
    dict
        ``{"commits": [{"sha": ..., "author": ..., "message": ...}, ...]}``
    """
    repo = _repo(working_dir)
    rev = branch or (repo.active_branch.name if not repo.head.is_detached else "HEAD")
    commits = []
    for commit in repo.iter_commits(rev, max_count=max_count):
        commits.append(
            {
                "sha": commit.hexsha,
                "short_sha": commit.hexsha[:7],
                "author": str(commit.author),
                "date": commit.committed_datetime.isoformat(),
                "message": commit.message.strip(),
            }
        )
    return {"commits": commits}
