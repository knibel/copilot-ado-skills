"""
Azure authentication helpers for Azure DevOps connections.

Supports authentication via:
- Azure CLI credentials (az login / az devops configure)
- Personal Access Token (PAT) via AZURE_DEVOPS_PAT environment variable
- AZURE_DEVOPS_ORG_URL environment variable for the organization URL
"""

from __future__ import annotations

import base64
import os

from azure.devops.connection import Connection
from azure.identity import AzureCliCredential
from msrest.authentication import BasicAuthentication, OAuthTokenAuthentication

# Azure DevOps resource ID used when requesting tokens from Azure AD
_ADO_RESOURCE_ID = "499b84ac-1321-427f-aa17-267ca6975798"


def get_organization_url(organization_url: str | None = None) -> str:
    """Return the ADO organization URL, falling back to the environment variable."""
    url = organization_url or os.environ.get("AZURE_DEVOPS_ORG_URL")
    if not url:
        raise ValueError(
            "Azure DevOps organization URL is required. "
            "Set AZURE_DEVOPS_ORG_URL or pass organization_url explicitly."
        )
    return url.rstrip("/")


def get_credentials() -> BasicAuthentication | OAuthTokenAuthentication:
    """
    Build ADO-compatible credentials.

    Priority:
    1. AZURE_DEVOPS_PAT environment variable (PAT-based auth)
    2. Azure CLI credentials obtained via ``az login`` or ``az devops configure``
    """
    pat = os.environ.get("AZURE_DEVOPS_PAT")
    if pat:
        return BasicAuthentication("", pat)

    credential = AzureCliCredential()
    token = credential.get_token(f"{_ADO_RESOURCE_ID}/.default")
    return OAuthTokenAuthentication("", {"access_token": token.token})


def get_connection(organization_url: str | None = None) -> Connection:
    """
    Return an authenticated :class:`azure.devops.connection.Connection`.

    Parameters
    ----------
    organization_url:
        ADO organization URL, e.g. ``https://dev.azure.com/my-org``.
        Falls back to ``AZURE_DEVOPS_ORG_URL`` if not given.
    """
    url = get_organization_url(organization_url)
    creds = get_credentials()
    return Connection(base_url=url, creds=creds)


def get_git_environment(remote_url: str | None = None) -> dict[str, str]:
    """Return environment variables for non-interactive authenticated git commands."""
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
    }
    if not remote_url or not remote_url.lower().startswith(("http://", "https://")):
        return env

    creds = get_credentials()
    if isinstance(creds, BasicAuthentication):
        token = base64.b64encode(f":{creds.password}".encode()).decode()
        auth_header = f"Authorization: Basic {token}"
    else:
        token_data = getattr(creds, "token", {})
        access_token = token_data.get("access_token", "") if isinstance(token_data, dict) else ""
        if not access_token:
            raise ValueError(
                "Azure CLI credentials did not provide an Azure DevOps access token."
            )
        auth_header = f"Authorization: Bearer {access_token}"

    env.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": auth_header,
        }
    )
    return env
