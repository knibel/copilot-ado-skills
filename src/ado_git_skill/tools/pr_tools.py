"""
Azure DevOps pull-request tools.

Provides helpers to create PRs, list PRs, read PR threads/comments, and
apply inline code suggestions left by reviewers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import git as gitpython

from azure.devops.v7_1.git.models import (
    Comment,
    CommentThread,
    GitPullRequest,
    GitPullRequestCompletionOptions,
    IdentityRefWithVote,
)

from ado_git_skill.auth import get_connection


# ---------------------------------------------------------------------------
# Pull-request CRUD
# ---------------------------------------------------------------------------


def create_pull_request(
    project: str,
    repository: str,
    title: str,
    description: str = "",
    source_branch: str | None = None,
    target_branch: str = "main",
    organization_url: str | None = None,
    auto_complete: bool = False,
    draft: bool = False,
) -> dict[str, Any]:
    """
    Create a pull request in Azure DevOps.

    Parameters
    ----------
    project:
        ADO project name or ID.
    repository:
        Repository name or ID.
    title:
        PR title.
    description:
        Optional PR description / body.
    source_branch:
        Source branch name (without ``refs/heads/`` prefix).
        Must already exist on the remote.
    target_branch:
        Target branch (default: ``main``).
    organization_url:
        ADO organization URL.  Falls back to ``AZURE_DEVOPS_ORG_URL``.
    auto_complete:
        Set the PR to auto-complete after all policies pass.
    draft:
        Create the PR as a draft.

    Returns
    -------
    dict
        Key fields: ``pull_request_id``, ``title``, ``status``, ``url``.
    """
    if not source_branch:
        raise ValueError("source_branch is required to create a pull request.")

    connection = get_connection(organization_url)
    git_client = connection.clients.get_git_client()

    pr_to_create = GitPullRequest(
        title=title,
        description=description,
        source_ref_name=f"refs/heads/{source_branch}",
        target_ref_name=f"refs/heads/{target_branch}",
        is_draft=draft,
    )

    if auto_complete:
        pr_to_create.completion_options = GitPullRequestCompletionOptions(
            delete_source_branch=False,
            squash_merge=False,
        )

    pr = git_client.create_pull_request(
        git_pull_request_to_create=pr_to_create,
        repository_id=repository,
        project=project,
    )

    if auto_complete:
        # Set the PR's auto-complete by updating with the creator's identity
        git_client.update_pull_request(
            git_pull_request_to_update=GitPullRequest(
                auto_complete_set_by=pr.created_by,
                completion_options=pr_to_create.completion_options,
            ),
            repository_id=repository,
            pull_request_id=pr.pull_request_id,
            project=project,
        )

    return _pr_to_dict(pr)


def list_pull_requests(
    project: str,
    repository: str,
    status: str = "active",
    organization_url: str | None = None,
    top: int = 50,
) -> dict[str, Any]:
    """
    List pull requests in a repository.

    Parameters
    ----------
    project:
        ADO project name or ID.
    repository:
        Repository name or ID.
    status:
        Filter by PR status: ``active``, ``completed``, ``abandoned``, or
        ``all`` (default: ``active``).
    organization_url:
        ADO organization URL.
    top:
        Maximum number of PRs to return (default: 50).

    Returns
    -------
    dict
        ``{"pull_requests": [...]}``
    """
    from azure.devops.v7_1.git.models import GitPullRequestSearchCriteria

    connection = get_connection(organization_url)
    git_client = connection.clients.get_git_client()

    search_criteria = GitPullRequestSearchCriteria(status=status)
    prs = git_client.get_pull_requests(
        repository_id=repository,
        search_criteria=search_criteria,
        project=project,
        top=top,
    )
    return {"pull_requests": [_pr_to_dict(pr) for pr in (prs or [])]}


def get_pull_request(
    project: str,
    repository: str,
    pull_request_id: int,
    organization_url: str | None = None,
) -> dict[str, Any]:
    """
    Get details of a specific pull request.

    Parameters
    ----------
    project:
        ADO project name or ID.
    repository:
        Repository name or ID.
    pull_request_id:
        Numeric ID of the pull request.
    organization_url:
        ADO organization URL.

    Returns
    -------
    dict
        PR details including ``title``, ``status``, ``description``, ``url``.
    """
    connection = get_connection(organization_url)
    git_client = connection.clients.get_git_client()
    pr = git_client.get_pull_request(
        repository_id=repository,
        pull_request_id=pull_request_id,
        project=project,
    )
    return _pr_to_dict(pr)


# ---------------------------------------------------------------------------
# Comments / threads
# ---------------------------------------------------------------------------


def get_pr_comments(
    project: str,
    repository: str,
    pull_request_id: int,
    organization_url: str | None = None,
) -> dict[str, Any]:
    """
    Retrieve all comment threads on a pull request.

    Parameters
    ----------
    project:
        ADO project name or ID.
    repository:
        Repository name or ID.
    pull_request_id:
        Numeric ID of the pull request.
    organization_url:
        ADO organization URL.

    Returns
    -------
    dict
        ``{"threads": [...]}`` where each thread includes its comments and
        optional file-path/line context for inline threads.
    """
    connection = get_connection(organization_url)
    git_client = connection.clients.get_git_client()

    threads = git_client.get_threads(
        repository_id=repository,
        pull_request_id=pull_request_id,
        project=project,
    )
    return {"threads": [_thread_to_dict(t) for t in (threads or [])]}


def reply_to_pr_comment(
    project: str,
    repository: str,
    pull_request_id: int,
    thread_id: int,
    content: str,
    organization_url: str | None = None,
) -> dict[str, Any]:
    """
    Post a reply to an existing comment thread.

    Parameters
    ----------
    project:
        ADO project name or ID.
    repository:
        Repository name or ID.
    pull_request_id:
        Numeric ID of the pull request.
    thread_id:
        ID of the thread to reply to.
    content:
        Text of the reply.
    organization_url:
        ADO organization URL.

    Returns
    -------
    dict
        The new comment as a dict.
    """
    connection = get_connection(organization_url)
    git_client = connection.clients.get_git_client()

    new_comment = Comment(content=content, comment_type=1)  # 1 = text
    created = git_client.create_comment(
        comment=new_comment,
        repository_id=repository,
        pull_request_id=pull_request_id,
        thread_id=thread_id,
        project=project,
    )
    return _comment_to_dict(created)


def apply_pr_suggestion(
    working_dir: str,
    file_path: str,
    start_line: int,
    end_line: int,
    suggested_content: str,
    commit_message: str = "Apply inline PR suggestion",
) -> dict[str, Any]:
    """
    Apply an inline code suggestion from a PR review to the local working tree.

    This replaces lines *start_line* through *end_line* (1-based, inclusive)
    in *file_path* with *suggested_content* and commits the change.

    Parameters
    ----------
    working_dir:
        Path to the local git repository.
    file_path:
        Repository-relative path of the file to modify.
    start_line:
        First line to replace (1-based, inclusive).
    end_line:
        Last line to replace (1-based, inclusive).
    suggested_content:
        New content to substitute for lines ``start_line``–``end_line``.
        May span multiple lines.
    commit_message:
        Commit message for the applied suggestion.

    Returns
    -------
    dict
        ``{"status": "applied", "file": file_path, "sha": commit_sha}``
    """
    full_path = (
        Path(working_dir) / file_path
        if not os.path.isabs(file_path)
        else Path(file_path)
    )

    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {full_path}")

    lines = full_path.read_text(encoding="utf-8").splitlines(keepends=True)

    # Validate line range
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        raise ValueError(
            f"Invalid line range {start_line}-{end_line} for file with "
            f"{len(lines)} lines."
        )

    # Build replacement: ensure the suggestion ends with a newline if the
    # original block did.
    replacement = suggested_content
    if lines[end_line - 1].endswith("\n") and not replacement.endswith("\n"):
        replacement += "\n"

    new_lines = (
        lines[: start_line - 1]
        + [replacement]
        + lines[end_line:]
    )
    full_path.write_text("".join(new_lines), encoding="utf-8")

    # Stage the modified file and commit
    repo = gitpython.Repo(working_dir)
    relative = str(full_path.relative_to(working_dir))
    repo.index.add([relative])
    commit = repo.index.commit(commit_message)
    return {"status": "applied", "file": file_path, "sha": commit.hexsha}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _pr_to_dict(pr: GitPullRequest) -> dict[str, Any]:
    org_url = ""
    if pr.repository and pr.repository.remote_url:
        # Derive a web URL from the remote URL (best-effort)
        remote = pr.repository.remote_url.rstrip("/")
        org_url = f"{remote}/pullrequest/{pr.pull_request_id}"

    return {
        "pull_request_id": pr.pull_request_id,
        "title": pr.title,
        "description": pr.description or "",
        "status": pr.status,
        "source_branch": (pr.source_ref_name or "").replace("refs/heads/", ""),
        "target_branch": (pr.target_ref_name or "").replace("refs/heads/", ""),
        "created_by": str(pr.created_by) if pr.created_by else "",
        "url": org_url,
        "is_draft": pr.is_draft or False,
    }


def _thread_to_dict(thread: CommentThread) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if thread.thread_context:
        tc = thread.thread_context
        context = {
            "file_path": tc.file_path,
            "right_file_start": (
                {"line": tc.right_file_start.line, "offset": tc.right_file_start.offset}
                if tc.right_file_start
                else None
            ),
            "right_file_end": (
                {"line": tc.right_file_end.line, "offset": tc.right_file_end.offset}
                if tc.right_file_end
                else None
            ),
        }
    return {
        "thread_id": thread.id,
        "status": thread.status,
        "is_deleted": thread.is_deleted or False,
        "thread_context": context,
        "comments": [_comment_to_dict(c) for c in (thread.comments or [])],
    }


def _comment_to_dict(comment: Comment) -> dict[str, Any]:
    return {
        "comment_id": comment.id,
        "author": str(comment.author) if comment.author else "",
        "content": comment.content or "",
        "comment_type": comment.comment_type,
        "published_date": (
            comment.published_date.isoformat() if comment.published_date else None
        ),
    }
