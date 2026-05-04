"""
One-shot CLI entry point for the Azure DevOps Git Skill.

This module provides an alternative to running the MCP server.  Each call is a
single function invocation:

    echo '{"remote_url":"...","destination":"..."}' \\
        | copilot-ado-skills-invoke clone_repository

The function name is taken from the first positional argument.  Parameters are
read as a JSON object from *stdin*.  The result is written as a JSON object to
*stdout* so that the caller (e.g. GitHub Copilot CLI built-in skill) can parse
it directly.

Exit codes
----------
0  – success (result may still contain an ``"error"`` key if the tool itself
     returned an error)
1  – usage error (wrong number of arguments, invalid JSON input, …)

Environment variables
---------------------
AZURE_DEVOPS_ORG_URL
    Required for all Azure DevOps API tools.
AZURE_DEVOPS_PAT
    Optional PAT; falls back to ``az login`` credentials when absent.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ado_git_skill.tools import git_tools, pr_tools, search_tools


# ---------------------------------------------------------------------------
# Dispatcher (mirrors server._dispatch without the MCP dependency)
# ---------------------------------------------------------------------------

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

    raise ValueError(f"Unknown function: {name!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """CLI entry point.

    Usage::

        copilot-ado-skills-invoke <function_name>

    Parameters are read as a JSON object from *stdin*.
    """
    args = argv if argv is not None else sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: copilot-ado-skills-invoke <function_name>\n"
            "\n"
            "Reads JSON parameters from stdin, writes JSON result to stdout.\n"
            "\n"
            "Available functions:\n"
            "  clone_repository, checkout_branch, create_branch, commit_changes,\n"
            "  push_changes, pull_changes, get_status, get_diff, list_branches,\n"
            "  get_log, create_pull_request, list_pull_requests, get_pull_request,\n"
            "  get_pr_comments, reply_to_pr_comment, apply_pr_suggestion,\n"
            "  list_repositories, search_repositories, get_repository,\n"
            "  search_code, get_file_content, list_repository_items",
            file=sys.stderr,
        )
        sys.exit(0 if args and args[0] in ("-h", "--help") else 1)

    function_name = args[0]

    try:
        raw = sys.stdin.read()
        parameters: dict[str, Any] = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"Invalid JSON input: {exc}"}))
        sys.exit(1)

    try:
        result = _dispatch(function_name, parameters)
    except Exception as exc:  # noqa: BLE001
        result = {"error": str(exc)}

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
