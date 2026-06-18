"""Central configuration sourced from environment variables (Azure runtime).

Azure DriftGuard runs natively on Azure: Azure OpenAI for inference, Azure SQL
Database for storage, Key Vault for credentials, AKS for compute, and the Azure
AI Agent Service (Azure AI Foundry) for native agent orchestration.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class AzureOpenAIConfig:
    """Azure OpenAI inference configuration (replaces Vertex/Gemini)."""

    endpoint: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", ""))
    api_version: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"))
    api_key: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY", ""))
    api_key_secret_name: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY_SECRET", ""))
    # Deployment names (not model names) for each tier.
    deployment: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"))
    deployment_fast: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-4o-mini"))
    deployment_judge: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT_JUDGE", "gpt-4o-mini"))
    embed_deployment: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-small"))
    max_tokens: int = field(default_factory=lambda: _int("AZURE_OPENAI_MAX_TOKENS", 4096))


@dataclass(frozen=True)
class AIAgentServiceConfig:
    """Azure AI Agent Service (Azure AI Foundry) orchestration."""

    project_endpoint: str = field(default_factory=lambda: os.getenv("AZURE_AI_PROJECT_ENDPOINT", ""))
    # Orchestration mode: "sdk" (runnable Agent Service SDK) or "connected" (managed connected agents).
    mode: str = field(default_factory=lambda: os.getenv("ORCHESTRATION_MODE", "sdk"))


@dataclass(frozen=True)
class KeyVaultConfig:
    vault_url: str = field(default_factory=lambda: os.getenv("AZURE_KEYVAULT_URL", ""))


@dataclass(frozen=True)
class AzureSqlConfig:
    """Azure SQL Database configuration. Password via Key Vault in prod."""

    server: str = field(default_factory=lambda: os.getenv("AZURE_SQL_SERVER", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("AZURE_SQL_PORT", 1433))
    database: str = field(default_factory=lambda: os.getenv("AZURE_SQL_DATABASE", "azure_driftguard"))
    user: str = field(default_factory=lambda: os.getenv("AZURE_SQL_USER", "driftguard"))
    password: str = field(default_factory=lambda: os.getenv("AZURE_SQL_PASSWORD", ""))
    password_secret_name: str = field(default_factory=lambda: os.getenv("AZURE_SQL_PASSWORD_SECRET", ""))
    driver: str = field(default_factory=lambda: os.getenv("AZURE_SQL_ODBC_DRIVER", "ODBC Driver 18 for SQL Server"))

    def resolved_password(self, vault_url: str = "") -> str:
        if self.password_secret_name and vault_url:
            from .secrets_azure import get_secret

            return get_secret(vault_url, self.password_secret_name)
        return self.password

    def connection_string(self, vault_url: str = "") -> str:
        pwd = self.resolved_password(vault_url)
        return (
            f"DRIVER={{{self.driver}}};SERVER={self.server},{self.port};"
            f"DATABASE={self.database};UID={self.user};PWD={pwd};"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )


@dataclass(frozen=True)
class JiraConfig:
    base_url: str = field(default_factory=lambda: os.getenv("JIRA_BASE_URL", ""))
    email: str = field(default_factory=lambda: os.getenv("JIRA_EMAIL", ""))
    api_token: str = field(default_factory=lambda: os.getenv("JIRA_API_TOKEN", ""))
    api_token_secret_name: str = field(default_factory=lambda: os.getenv("JIRA_API_TOKEN_SECRET", ""))
    project_key: str = field(default_factory=lambda: os.getenv("JIRA_PROJECT_KEY", ""))
    acli_path: str = field(default_factory=lambda: os.getenv("JIRA_ACLI_PATH", "acli"))
    timeout_seconds: int = field(default_factory=lambda: _int("JIRA_TIMEOUT_SECONDS", 10))
    api_version: str = field(default_factory=lambda: os.getenv("JIRA_API_VERSION", "3"))

    def resolved_token(self, vault_url: str = "") -> str:
        if self.api_token_secret_name and vault_url:
            from .secrets_azure import get_secret

            return get_secret(vault_url, self.api_token_secret_name)
        return self.api_token


@dataclass(frozen=True)
class GitHubConfig:
    api_base: str = field(default_factory=lambda: os.getenv("GITHUB_API_BASE", "https://api.github.com"))
    repo_owner: str = field(default_factory=lambda: os.getenv("GITHUB_REPO_OWNER", ""))
    repo_name: str = field(default_factory=lambda: os.getenv("GITHUB_REPO_NAME", ""))
    default_branch: str = field(default_factory=lambda: os.getenv("GITHUB_DEFAULT_BRANCH", "main"))
    auth_mode: str = field(default_factory=lambda: os.getenv("GITHUB_AUTH_MODE", "pat"))
    pat: str = field(default_factory=lambda: os.getenv("GITHUB_PAT", ""))
    pat_secret_name: str = field(default_factory=lambda: os.getenv("GITHUB_PAT_SECRET", ""))
    app_id: str = field(default_factory=lambda: os.getenv("GITHUB_APP_ID", ""))
    app_installation_id: str = field(default_factory=lambda: os.getenv("GITHUB_APP_INSTALLATION_ID", ""))
    app_private_key_path: str = field(default_factory=lambda: os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", ""))
    app_private_key_secret_name: str = field(default_factory=lambda: os.getenv("GITHUB_APP_PRIVATE_KEY_SECRET", ""))
    timeout_seconds: int = field(default_factory=lambda: _int("GITHUB_TIMEOUT_SECONDS", 20))

    def resolved_pat(self, vault_url: str = "") -> str:
        if self.pat_secret_name and vault_url:
            from .secrets_azure import get_secret

            return get_secret(vault_url, self.pat_secret_name)
        return self.pat


@dataclass(frozen=True)
class PipelineConfig:
    capture_enabled: bool = field(default_factory=lambda: _bool("CAPTURE_ENABLED", False))
    capture_dir: str = field(default_factory=lambda: os.getenv("CAPTURE_DIR", "/tmp/azure-driftguard-eval"))
    skills_root: str = field(default_factory=lambda: os.getenv("SKILLS_ROOT", "skills"))
    skills_source: str = field(default_factory=lambda: os.getenv("SKILLS_SOURCE", "local"))
    skills_repo_owner: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_OWNER", ""))
    skills_repo_name: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_NAME", ""))
    skills_repo_ref: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_REF", ""))
    skills_repo_path: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_PATH", "skills"))
    skills_cache_ttl: int = field(default_factory=lambda: int(os.getenv("SKILLS_CACHE_TTL", "300")))
    release_feed_url: str = field(
        default_factory=lambda: os.getenv(
            "RELEASE_FEED_URL", "https://www.microsoft.com/releasecommunications/api/v2/azure/rss"
        )
    )
    terraform_module_path: str = field(
        default_factory=lambda: os.getenv("TERRAFORM_MODULE_PATH", "modules")
    )
    terraform_max_retries: int = field(default_factory=lambda: _int("TERRAFORM_MAX_RETRIES", 3))
    judge_enabled: bool = field(default_factory=lambda: _bool("JUDGE_ENABLED", True))
    judge_min_score: int = field(default_factory=lambda: _int("JUDGE_MIN_SCORE", 70))
    cache_ttl_seconds: int = field(default_factory=lambda: _int("CACHE_TTL_SECONDS", 86400))
    relevance_filter_enabled: bool = field(default_factory=lambda: _bool("RELEVANCE_FILTER_ENABLED", True))
    classification_batch_size: int = field(default_factory=lambda: _int("CLASSIFICATION_BATCH_SIZE", 5))


@dataclass(frozen=True)
class Config:
    openai: AzureOpenAIConfig = field(default_factory=AzureOpenAIConfig)
    agents: AIAgentServiceConfig = field(default_factory=AIAgentServiceConfig)
    keyvault: KeyVaultConfig = field(default_factory=KeyVaultConfig)
    sql: AzureSqlConfig = field(default_factory=AzureSqlConfig)
    jira: JiraConfig = field(default_factory=JiraConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
