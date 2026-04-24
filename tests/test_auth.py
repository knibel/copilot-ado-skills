"""
Tests for the auth module.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from ado_git_skill import auth


# ---------------------------------------------------------------------------
# get_organization_url
# ---------------------------------------------------------------------------


def test_get_organization_url_from_arg() -> None:
    url = auth.get_organization_url("https://dev.azure.com/my-org")
    assert url == "https://dev.azure.com/my-org"


def test_get_organization_url_strips_trailing_slash() -> None:
    url = auth.get_organization_url("https://dev.azure.com/my-org/")
    assert url == "https://dev.azure.com/my-org"


def test_get_organization_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_ORG_URL", "https://dev.azure.com/env-org")
    url = auth.get_organization_url()
    assert url == "https://dev.azure.com/env-org"


def test_get_organization_url_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_DEVOPS_ORG_URL", raising=False)
    with pytest.raises(ValueError, match="AZURE_DEVOPS_ORG_URL"):
        auth.get_organization_url()


# ---------------------------------------------------------------------------
# get_credentials
# ---------------------------------------------------------------------------


def test_get_credentials_uses_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "my-secret-token")
    from msrest.authentication import BasicAuthentication

    creds = auth.get_credentials()
    assert isinstance(creds, BasicAuthentication)
    assert creds.password == "my-secret-token"


@patch("ado_git_skill.auth.AzureCliCredential")
def test_get_credentials_uses_azure_cli(
    mock_cli_cred: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    mock_token = MagicMock()
    mock_token.token = "cli-access-token"
    mock_cli_cred.return_value.get_token.return_value = mock_token

    from msrest.authentication import OAuthTokenAuthentication

    creds = auth.get_credentials()
    assert isinstance(creds, OAuthTokenAuthentication)


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------


@patch("ado_git_skill.auth.get_credentials")
@patch("ado_git_skill.auth.Connection")
def test_get_connection(
    mock_connection: MagicMock,
    mock_get_creds: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_DEVOPS_ORG_URL", "https://dev.azure.com/org")
    mock_get_creds.return_value = MagicMock()

    conn = auth.get_connection()

    mock_connection.assert_called_once_with(
        base_url="https://dev.azure.com/org",
        creds=mock_get_creds.return_value,
    )
