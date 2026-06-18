"""Azure Key Vault access.

Resolves secret values (Azure SQL password, Jira token, GitHub PAT / App key)
from Key Vault. Values are cached in-process. Never logs secret values. Uses
DefaultAzureCredential so it works with managed identity (AKS workload identity),
environment credentials, or az login locally.
"""
from __future__ import annotations

from functools import lru_cache

from .logging_setup import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=64)
def get_secret(vault_url: str, secret_name: str) -> str:
    """Return a secret value from Key Vault by name. Cached per process."""
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
    secret = client.get_secret(secret_name)
    logger.info("Resolved secret %s from Key Vault", secret_name)
    return secret.value or ""
