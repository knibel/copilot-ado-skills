"""
Tests for search_tools module.

Uses pytest-mock to stub the Azure DevOps SDK so no real network calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ado_git_skill.tools import search_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(name: str, repo_id: str = "abc123") -> MagicMock:
    r = MagicMock()
    r.id = repo_id
    r.name = name
    r.default_branch = "refs/heads/main"
    r.remote_url = f"https://dev.azure.com/org/proj/_git/{name}"
    r.ssh_url = f"git@ssh.dev.azure.com:v3/org/proj/{name}"
    r.web_url = f"https://dev.azure.com/org/proj/_git/{name}"
    r.project = MagicMock(name="proj")
    r.project.name = "proj"
    r.size = 1024
    return r


# ---------------------------------------------------------------------------
# list_repositories
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.search_tools.get_connection")
def test_list_repositories(mock_get_conn: MagicMock) -> None:
    repos = [_make_repo("repo-a"), _make_repo("repo-b")]
    git_client = MagicMock()
    git_client.get_repositories.return_value = repos
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = search_tools.list_repositories(project="MyProject")

    assert len(result["repositories"]) == 2
    names = [r["name"] for r in result["repositories"]]
    assert "repo-a" in names
    assert "repo-b" in names


@patch("ado_git_skill.tools.search_tools.get_connection")
def test_list_repositories_empty(mock_get_conn: MagicMock) -> None:
    git_client = MagicMock()
    git_client.get_repositories.return_value = []
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = search_tools.list_repositories(project="Empty")
    assert result["repositories"] == []


# ---------------------------------------------------------------------------
# search_repositories
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.search_tools.get_connection")
def test_search_repositories_matches(mock_get_conn: MagicMock) -> None:
    repos = [_make_repo("service-xyz"), _make_repo("other-service"), _make_repo("XYZ-api")]
    git_client = MagicMock()
    git_client.get_repositories.return_value = repos
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = search_tools.search_repositories(project="P", query="xyz")

    names = [r["name"] for r in result["repositories"]]
    assert "service-xyz" in names
    assert "XYZ-api" in names
    assert "other-service" not in names


@patch("ado_git_skill.tools.search_tools.get_connection")
def test_search_repositories_no_match(mock_get_conn: MagicMock) -> None:
    repos = [_make_repo("repo-one"), _make_repo("repo-two")]
    git_client = MagicMock()
    git_client.get_repositories.return_value = repos
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = search_tools.search_repositories(project="P", query="nonexistent")
    assert result["repositories"] == []


# ---------------------------------------------------------------------------
# get_repository
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.search_tools.get_connection")
def test_get_repository(mock_get_conn: MagicMock) -> None:
    repo = _make_repo("my-service")
    git_client = MagicMock()
    git_client.get_repository.return_value = repo
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = search_tools.get_repository(project="P", repository="my-service")

    assert result["name"] == "my-service"
    assert result["default_branch"] == "main"


# ---------------------------------------------------------------------------
# search_code  (uses requests, not the SDK client)
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.search_tools.get_credentials")
@patch("ado_git_skill.tools.search_tools.get_organization_url")
@patch("ado_git_skill.tools.search_tools.requests")
def test_search_code(
    mock_requests: MagicMock,
    mock_org_url: MagicMock,
    mock_get_creds: MagicMock,
) -> None:
    mock_org_url.return_value = "https://dev.azure.com/my-org"

    from msrest.authentication import BasicAuthentication

    mock_get_creds.return_value = BasicAuthentication("", "fake-pat")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "count": 1,
        "results": [
            {
                "path": "src/client.py",
                "repository": {"name": "service-xyz"},
                "project": {"name": "MyProject"},
                "branch": "main",
                "contentId": "https://dev.azure.com/...",
                "matches": {
                    "content": [
                        {"charOffset": 10, "line": "    def call_xyz():"}
                    ]
                },
            }
        ],
    }
    mock_response.raise_for_status = MagicMock()
    mock_requests.post.return_value = mock_response

    result = search_tools.search_code(project="MyProject", query="call_xyz")

    assert result["count"] == 1
    assert result["results"][0]["file"] == "src/client.py"
    assert result["results"][0]["repository"] == "service-xyz"
    assert result["results"][0]["matches"][0]["snippet"] == "    def call_xyz():"


# ---------------------------------------------------------------------------
# get_file_content
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.search_tools.get_connection")
def test_get_file_content(mock_get_conn: MagicMock) -> None:
    git_client = MagicMock()
    # Simulate streaming bytes
    git_client.get_item_content.return_value = iter([b"def hello():\n    pass\n"])
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = search_tools.get_file_content(
        project="P",
        repository="R",
        file_path="src/hello.py",
        branch="main",
    )

    assert result["file_path"] == "src/hello.py"
    assert "def hello()" in result["content"]


# ---------------------------------------------------------------------------
# list_repository_items
# ---------------------------------------------------------------------------


@patch("ado_git_skill.tools.search_tools.get_connection")
def test_list_repository_items(mock_get_conn: MagicMock) -> None:
    item_src = MagicMock()
    item_src.path = "/src"
    item_src.is_folder = True
    item_src.url = "https://dev.azure.com/..."
    item_src.object_id = "abc"

    item_file = MagicMock()
    item_file.path = "/src/main.py"
    item_file.is_folder = False
    item_file.url = "https://dev.azure.com/..."
    item_file.object_id = "def"

    git_client = MagicMock()
    git_client.get_items.return_value = [item_src, item_file]
    mock_get_conn.return_value.clients.get_git_client.return_value = git_client

    result = search_tools.list_repository_items(project="P", repository="R")

    assert len(result["items"]) == 2
    assert result["items"][0]["is_folder"] is True
    assert result["items"][1]["path"] == "/src/main.py"
