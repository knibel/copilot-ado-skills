"""
MCP server entry point for the Azure DevOps Git Skill.

Run with:
    python -m ado_git_skill.server
or (after ``pip install -e .``):
    copilot-ado-skills

Environment variables
---------------------
AZURE_DEVOPS_ORG_URL
    Required.  ADO organization URL, e.g. ``https://dev.azure.com/my-org``.
AZURE_DEVOPS_PAT
    Optional.  Personal Access Token.  When absent the skill uses the
    credentials from ``az login`` / ``az devops configure``.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from ado_git_skill.tools import git_tools, pr_tools, search_tools

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

server = Server("copilot-ado-skills")

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOLS: list[types.Tool] = [
    # ── Git operations ──────────────────────────────────────────────────────
    types.Tool(
        name="clone_repository",
        description=(
            "Clone an Azure DevOps git repository to a local directory. "
            "Returns the local path and active branch."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "remote_url": {
                    "type": "string",
                    "description": "HTTPS or SSH URL of the remote ADO repository.",
                },
                "destination": {
                    "type": "string",
                    "description": "Local filesystem path to clone into.",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to check out after cloning (optional).",
                },
            },
            "required": ["remote_url", "destination"],
        },
    ),
    types.Tool(
        name="checkout_branch",
        description=(
            "Check out a branch in an existing local git repository. "
            "Optionally create the branch if it does not exist."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string", "description": "Local repo path."},
                "branch": {"type": "string", "description": "Branch to check out."},
                "create": {
                    "type": "boolean",
                    "description": "Create branch if it does not exist.",
                    "default": False,
                },
            },
            "required": ["working_dir", "branch"],
        },
    ),
    types.Tool(
        name="create_branch",
        description="Create a new git branch in a local repository.",
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "branch": {"type": "string", "description": "Name for the new branch."},
                "base_branch": {
                    "type": "string",
                    "description": "Branch to base the new branch on (defaults to HEAD).",
                },
            },
            "required": ["working_dir", "branch"],
        },
    ),
    types.Tool(
        name="commit_changes",
        description="Stage and commit local changes in a git repository.",
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "message": {"type": "string", "description": "Commit message."},
                "add_all": {
                    "type": "boolean",
                    "description": "Stage all changes before committing.",
                    "default": True,
                },
            },
            "required": ["working_dir", "message"],
        },
    ),
    types.Tool(
        name="push_changes",
        description=(
            "Push committed changes to the Azure DevOps remote repository."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "remote": {"type": "string", "default": "origin"},
                "branch": {
                    "type": "string",
                    "description": "Branch to push (defaults to current branch).",
                },
                "set_upstream": {
                    "type": "boolean",
                    "default": True,
                    "description": "Set the upstream tracking branch.",
                },
            },
            "required": ["working_dir"],
        },
    ),
    types.Tool(
        name="pull_changes",
        description="Pull the latest changes from the Azure DevOps remote repository.",
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "remote": {"type": "string", "default": "origin"},
                "branch": {
                    "type": "string",
                    "description": "Remote branch to pull (defaults to current).",
                },
            },
            "required": ["working_dir"],
        },
    ),
    types.Tool(
        name="get_status",
        description=(
            "Return the working-tree status of a local git repository: "
            "current branch, modified, staged, and untracked files."
        ),
        inputSchema={
            "type": "object",
            "properties": {"working_dir": {"type": "string"}},
            "required": ["working_dir"],
        },
    ),
    types.Tool(
        name="get_diff",
        description="Return a unified diff of changes in a local git repository.",
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "base": {
                    "type": "string",
                    "default": "HEAD",
                    "description": "Base ref to diff from.",
                },
                "target": {
                    "type": "string",
                    "description": "Target ref (omit to diff against working tree).",
                },
                "file_path": {
                    "type": "string",
                    "description": "Restrict diff to this file (optional).",
                },
            },
            "required": ["working_dir"],
        },
    ),
    types.Tool(
        name="list_branches",
        description="List local and remote branches in a git repository.",
        inputSchema={
            "type": "object",
            "properties": {"working_dir": {"type": "string"}},
            "required": ["working_dir"],
        },
    ),
    types.Tool(
        name="get_log",
        description="Return the recent commit log of a git repository.",
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "max_count": {"type": "integer", "default": 20},
                "branch": {"type": "string"},
            },
            "required": ["working_dir"],
        },
    ),
    # ── Pull requests ────────────────────────────────────────────────────────
    types.Tool(
        name="create_pull_request",
        description=(
            "Create a pull request in Azure DevOps. "
            "Defaults to targeting the 'main' branch."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "ADO project name or ID.",
                },
                "repository": {
                    "type": "string",
                    "description": "Repository name or ID.",
                },
                "title": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "source_branch": {
                    "type": "string",
                    "description": "Source branch (must already exist on remote).",
                },
                "target_branch": {
                    "type": "string",
                    "default": "main",
                    "description": "Target branch (default: main).",
                },
                "organization_url": {"type": "string"},
                "auto_complete": {"type": "boolean", "default": False},
                "draft": {"type": "boolean", "default": False},
            },
            "required": ["project", "repository", "title", "source_branch"],
        },
    ),
    types.Tool(
        name="list_pull_requests",
        description="List pull requests in an Azure DevOps repository.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "repository": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "abandoned", "all"],
                    "default": "active",
                },
                "organization_url": {"type": "string"},
                "top": {"type": "integer", "default": 50},
            },
            "required": ["project", "repository"],
        },
    ),
    types.Tool(
        name="get_pull_request",
        description="Get details of a specific pull request.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "repository": {"type": "string"},
                "pull_request_id": {"type": "integer"},
                "organization_url": {"type": "string"},
            },
            "required": ["project", "repository", "pull_request_id"],
        },
    ),
    types.Tool(
        name="get_pr_comments",
        description=(
            "Retrieve all comment threads on a pull request, including "
            "inline (file-level) threads with line context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "repository": {"type": "string"},
                "pull_request_id": {"type": "integer"},
                "organization_url": {"type": "string"},
            },
            "required": ["project", "repository", "pull_request_id"],
        },
    ),
    types.Tool(
        name="reply_to_pr_comment",
        description="Post a reply to an existing pull request comment thread.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "repository": {"type": "string"},
                "pull_request_id": {"type": "integer"},
                "thread_id": {"type": "integer"},
                "content": {"type": "string"},
                "organization_url": {"type": "string"},
            },
            "required": [
                "project",
                "repository",
                "pull_request_id",
                "thread_id",
                "content",
            ],
        },
    ),
    types.Tool(
        name="apply_pr_suggestion",
        description=(
            "Apply an inline code suggestion from a PR review to the local "
            "working tree and commit it.  Replaces lines start_line–end_line "
            "(1-based, inclusive) in file_path with suggested_content."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "file_path": {
                    "type": "string",
                    "description": "Repo-relative path of the file to modify.",
                },
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "suggested_content": {"type": "string"},
                "commit_message": {
                    "type": "string",
                    "default": "Apply inline PR suggestion",
                },
            },
            "required": [
                "working_dir",
                "file_path",
                "start_line",
                "end_line",
                "suggested_content",
            ],
        },
    ),
    # ── Repository & code search ─────────────────────────────────────────────
    types.Tool(
        name="list_repositories",
        description="List all git repositories in an Azure DevOps project.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "organization_url": {"type": "string"},
            },
            "required": ["project"],
        },
    ),
    types.Tool(
        name="search_repositories",
        description=(
            "Search for repositories by name within an Azure DevOps project "
            "(case-insensitive substring match)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "query": {"type": "string"},
                "organization_url": {"type": "string"},
            },
            "required": ["project", "query"],
        },
    ),
    types.Tool(
        name="get_repository",
        description="Get details of a specific Azure DevOps repository.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "repository": {"type": "string"},
                "organization_url": {"type": "string"},
            },
            "required": ["project", "repository"],
        },
    ),
    types.Tool(
        name="search_code",
        description=(
            "Search source code across Azure DevOps repositories using the "
            "ADO Search API.  Useful for understanding existing implementations "
            "before making changes (e.g. finding the service XYZ REST client). "
            "Supports ADO search operators: ext:py, file:main.py, repo:my-repo."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "query": {
                    "type": "string",
                    "description": "Search query (ADO code search syntax).",
                },
                "organization_url": {"type": "string"},
                "repository": {
                    "type": "string",
                    "description": "Restrict search to this repository (optional).",
                },
                "top": {"type": "integer", "default": 25},
            },
            "required": ["project", "query"],
        },
    ),
    types.Tool(
        name="get_file_content",
        description=(
            "Retrieve the raw content of a file from an Azure DevOps "
            "repository without cloning it locally."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "repository": {"type": "string"},
                "file_path": {"type": "string"},
                "branch": {"type": "string", "default": "main"},
                "organization_url": {"type": "string"},
            },
            "required": ["project", "repository", "file_path"],
        },
    ),
    types.Tool(
        name="list_repository_items",
        description="List files and directories in a repository path.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "repository": {"type": "string"},
                "path": {"type": "string", "default": "/"},
                "branch": {"type": "string", "default": "main"},
                "recursive": {"type": "boolean", "default": False},
                "organization_url": {"type": "string"},
            },
            "required": ["project", "repository"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return _TOOLS


@server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Dispatch a tool call to the appropriate implementation."""

    try:
        result = _dispatch(name, arguments)
    except Exception as exc:  # noqa: BLE001
        result = {"error": str(exc)}

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, indent=2, default=str),
        )
    ]


def _dispatch(name: str, args: dict[str, Any]) -> Any:  # noqa: PLR0912, C901
    # ── Git tools ────────────────────────────────────────────────────────────
    if name == "clone_repository":
        return git_tools.clone_repository(**args)
    if name == "checkout_branch":
        return git_tools.checkout_branch(**args)
    if name == "create_branch":
        return git_tools.create_branch(**args)
    if name == "commit_changes":
        return git_tools.commit_changes(**args)
    if name == "push_changes":
        return git_tools.push_changes(**args)
    if name == "pull_changes":
        return git_tools.pull_changes(**args)
    if name == "get_status":
        return git_tools.get_status(**args)
    if name == "get_diff":
        return git_tools.get_diff(**args)
    if name == "list_branches":
        return git_tools.list_branches(**args)
    if name == "get_log":
        return git_tools.get_log(**args)

    # ── PR tools ─────────────────────────────────────────────────────────────
    if name == "create_pull_request":
        return pr_tools.create_pull_request(**args)
    if name == "list_pull_requests":
        return pr_tools.list_pull_requests(**args)
    if name == "get_pull_request":
        return pr_tools.get_pull_request(**args)
    if name == "get_pr_comments":
        return pr_tools.get_pr_comments(**args)
    if name == "reply_to_pr_comment":
        return pr_tools.reply_to_pr_comment(**args)
    if name == "apply_pr_suggestion":
        return pr_tools.apply_pr_suggestion(**args)

    # ── Search tools ─────────────────────────────────────────────────────────
    if name == "list_repositories":
        return search_tools.list_repositories(**args)
    if name == "search_repositories":
        return search_tools.search_repositories(**args)
    if name == "get_repository":
        return search_tools.get_repository(**args)
    if name == "search_code":
        return search_tools.search_code(**args)
    if name == "get_file_content":
        return search_tools.get_file_content(**args)
    if name == "list_repository_items":
        return search_tools.list_repository_items(**args)

    raise ValueError(f"Unknown tool: {name!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _amain() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="copilot-ado-skills",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    """CLI entry point."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
