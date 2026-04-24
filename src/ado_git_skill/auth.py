"""
Azure authentication helpers for Azure DevOps connections.

Supports authentication via:
- Azure CLI credentials (az login / az devops configure)
- Personal Access Token (PAT) via AZURE_DEVOPS_PAT environment variable
- AZURE_DEVOPS_ORG_URL environment variable for the organization URL
"""

from __future__ import annotations

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
