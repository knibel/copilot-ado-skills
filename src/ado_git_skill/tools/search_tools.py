"""
Repository and code search tools for Azure DevOps.

Provides helpers to:
- List all git repositories in an ADO project
- Search for repositories by name
- Search source code across repositories using the ADO Search API
"""

from __future__ import annotations

from typing import Any

import requests

from ado_git_skill.auth import (
    get_connection,
    get_credentials,
    get_oauth_access_token,
    get_organization_url,
)


# ---------------------------------------------------------------------------
# Repository search
# ---------------------------------------------------------------------------


def list_repositories(
    project: str,
    organization_url: str | None = None,
) -> dict[str, Any]:
    """
    List all git repositories in an Azure DevOps project.

    Parameters
    ----------
    project:
        ADO project name or ID.
    organization_url:
        ADO organization URL.  Falls back to ``AZURE_DEVOPS_ORG_URL``.

    Returns
    -------
    dict
        ``{"repositories": [{"id": ..., "name": ..., "remote_url": ...}, ...]}``
    """
    connection = get_connection(organization_url)
    git_client = connection.clients.get_git_client()
    repos = git_client.get_repositories(project=project)
    return {
        "repositories": [
            {
                "id": r.id,
                "name": r.name,
                "default_branch": (r.default_branch or "").replace("refs/heads/", ""),
                "remote_url": r.remote_url,
                "ssh_url": r.ssh_url,
                "web_url": r.web_url,
                "project": r.project.name if r.project else project,
                "size": r.size,
            }
            for r in (repos or [])
        ]
    }


def search_repositories(
    project: str,
    query: str,
    organization_url: str | None = None,
) -> dict[str, Any]:
    """
    Search for repositories by name within an Azure DevOps project.

    Performs a case-insensitive substring match on the repository name.

    Parameters
    ----------
    project:
        ADO project name or ID.
    query:
        Search string to match against repository names.
    organization_url:
        ADO organization URL.

    Returns
    -------
    dict
        ``{"repositories": [...]}`` – same shape as :func:`list_repositories`.
    """
    result = list_repositories(project=project, organization_url=organization_url)
    q_lower = query.lower()
    filtered = [
        r for r in result["repositories"] if q_lower in r["name"].lower()
    ]
    return {"repositories": filtered}


def get_repository(
    project: str,
    repository: str,
    organization_url: str | None = None,
) -> dict[str, Any]:
    """
    Get details of a specific repository.

    Parameters
    ----------
    project:
        ADO project name or ID.
    repository:
        Repository name or ID.
    organization_url:
        ADO organization URL.

    Returns
    -------
    dict
        Repository details.
    """
    connection = get_connection(organization_url)
    git_client = connection.clients.get_git_client()
    r = git_client.get_repository(repository_id=repository, project=project)
    return {
        "id": r.id,
        "name": r.name,
        "default_branch": (r.default_branch or "").replace("refs/heads/", ""),
        "remote_url": r.remote_url,
        "ssh_url": r.ssh_url,
        "web_url": r.web_url,
        "project": r.project.name if r.project else project,
        "size": r.size,
    }


# ---------------------------------------------------------------------------
# Code search
# ---------------------------------------------------------------------------


def search_code(
    project: str,
    query: str,
    organization_url: str | None = None,
    repository: str | None = None,
    top: int = 25,
) -> dict[str, Any]:
    """
    Search source code across Azure DevOps repositories using the Search API.

    Parameters
    ----------
    project:
        ADO project name or ID.
    query:
        Free-text search query.  Supports ADO code-search operators such as
        ``ext:py``, ``file:main.py``, ``repo:my-repo``.
    organization_url:
        ADO organization URL.
    repository:
        Restrict the search to this repository name (optional).
    top:
        Maximum number of results to return (default: 25, max: 1000).

    Returns
    -------
    dict
        ``{"count": int, "results": [{"file": ..., "repository": ...,
        "project": ..., "matches": [...], "url": ...}, ...]}``

    Notes
    -----
    The ADO Search API is a separate service from the core DevOps API and
    requires the ``vssps.visualstudio.com`` endpoint.  The
    ``azure-devops`` Python SDK does not expose a dedicated client for it,
    so this function calls the REST endpoint directly using the OAuth token
    retrieved by :func:`~ado_git_skill.auth.get_credentials`.
    """
    import json

    from msrest.authentication import BasicAuthentication, OAuthTokenAuthentication

    org_url = get_organization_url(organization_url)
    # Strip trailing /DefaultCollection for on-prem ADO
    org_name = org_url.rstrip("/").split("/")[-1]
    if org_name.lower() == "defaultcollection":
        org_url_base = "/".join(org_url.rstrip("/").split("/")[:-1])
    else:
        org_url_base = org_url

    search_url = (
        f"{org_url_base}/_apis/search/codesearchresults?api-version=7.1-preview.1"
    )

    # Build filters
    filters: dict[str, list[str]] = {"Project": [project]}
    if repository:
        filters["Repository"] = [repository]

    payload = {
        "$top": min(top, 1000),
        "searchText": query,
        "filters": filters,
        "includeSuggestions": False,
        "$skip": 0,
    }

    # Resolve auth headers
    creds = get_credentials()
    if isinstance(creds, BasicAuthentication):
        import base64

        token = base64.b64encode(f":{creds.password}".encode()).decode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}",
        }
    else:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {get_oauth_access_token(creds)}",
        }

    response = requests.post(search_url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("results", []):
        matches = []
        for hit in item.get("matches", {}).get("content", []):
            matches.append(
                {
                    "line": hit.get("charOffset"),
                    "snippet": hit.get("line", ""),
                }
            )
        results.append(
            {
                "file": item.get("path", ""),
                "repository": item.get("repository", {}).get("name", ""),
                "project": item.get("project", {}).get("name", project),
                "branch": item.get("branch", ""),
                "matches": matches,
                "url": item.get("contentId", ""),
            }
        )

    return {"count": data.get("count", len(results)), "results": results}


def get_file_content(
    project: str,
    repository: str,
    file_path: str,
    branch: str = "main",
    organization_url: str | None = None,
) -> dict[str, Any]:
    """
    Retrieve the raw content of a file from an Azure DevOps repository.

    Parameters
    ----------
    project:
        ADO project name or ID.
    repository:
        Repository name or ID.
    file_path:
        Path to the file within the repository (e.g. ``src/main.py``).
    branch:
        Branch to read from (default: ``main``).
    organization_url:
        ADO organization URL.

    Returns
    -------
    dict
        ``{"file_path": ..., "branch": ..., "content": "<file content>"}``
    """
    connection = get_connection(organization_url)
    git_client = connection.clients.get_git_client()

    # Use version descriptor to target a branch
    from azure.devops.v7_1.git.models import GitVersionDescriptor

    version_descriptor = GitVersionDescriptor(
        version=branch,
        version_type="branch",
    )
    stream = git_client.get_item_content(
        repository_id=repository,
        path=file_path,
        project=project,
        version_descriptor=version_descriptor,
        download=True,
    )
    content = b"".join(stream).decode("utf-8", errors="replace")
    return {"file_path": file_path, "branch": branch, "content": content}


def list_repository_items(
    project: str,
    repository: str,
    path: str = "/",
    branch: str = "main",
    recursive: bool = False,
    organization_url: str | None = None,
) -> dict[str, Any]:
    """
    List files and directories in a repository path.

    Parameters
    ----------
    project:
        ADO project name or ID.
    repository:
        Repository name or ID.
    path:
        Directory path to list (default: repository root ``/``).
    branch:
        Branch to inspect (default: ``main``).
    recursive:
        When ``True``, list all files recursively under *path*.
    organization_url:
        ADO organization URL.

    Returns
    -------
    dict
        ``{"items": [{"path": ..., "is_folder": ..., "url": ...}, ...]}``
    """
    connection = get_connection(organization_url)
    git_client = connection.clients.get_git_client()

    from azure.devops.v7_1.git.models import GitVersionDescriptor

    version_descriptor = GitVersionDescriptor(version=branch, version_type="branch")
    items = git_client.get_items(
        repository_id=repository,
        scope_path=path,
        project=project,
        recursion_level="full" if recursive else "oneLevel",
        version_descriptor=version_descriptor,
    )
    return {
        "items": [
            {
                "path": i.path,
                "is_folder": i.is_folder or False,
                "url": i.url,
                "object_id": i.object_id,
            }
            for i in (items or [])
        ]
    }
