"""Central configuration sourced from environment variables (AWS runtime).

AWS DriftGuard runs natively on AWS: Bedrock for inference, RDS Postgres for
storage, Secrets Manager for credentials, ECS/EKS for compute, and native
Bedrock Agents for orchestration. All config is environment-driven so the same
image runs across environments by changing env vars / task definitions only.
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
class BedrockConfig:
    """Amazon Bedrock inference configuration (replaces Vertex/Gemini)."""

    region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "us-east-1"))
    # Reasoning-heavy agents (Change/Decision/Terraform).
    model: str = field(default_factory=lambda: os.getenv(
        "BEDROCK_MODEL", "anthropic.claude-sonnet-4-6-20260514-v1:0"))
    # Cheaper/faster model for parsing + bucketing (tiered routing).
    model_fast: str = field(default_factory=lambda: os.getenv(
        "BEDROCK_MODEL_FAST", "anthropic.claude-haiku-4-5-20251001-v1:0"))
    # Judge model: defaults to fast to keep the critic pass cheap.
    model_judge: str = field(default_factory=lambda: os.getenv(
        "BEDROCK_MODEL_JUDGE", "anthropic.claude-haiku-4-5-20251001-v1:0"))
    # Embedding model for the relevance filter.
    embed_model: str = field(default_factory=lambda: os.getenv(
        "BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0"))
    max_tokens: int = field(default_factory=lambda: _int("BEDROCK_MAX_TOKENS", 4096))


@dataclass(frozen=True)
class BedrockAgentsConfig:
    """Native Bedrock Agents orchestration (managed multi-agent collaboration)."""

    # When provisioned, the supervisor agent id/alias driving the 7 collaborators.
    supervisor_agent_id: str = field(default_factory=lambda: os.getenv("BEDROCK_SUPERVISOR_AGENT_ID", ""))
    supervisor_agent_alias_id: str = field(
        default_factory=lambda: os.getenv("BEDROCK_SUPERVISOR_AGENT_ALIAS_ID", "TSTALIASID"))
    # Orchestration mode: "converse" (runnable tool-use loop) or "agents" (managed).
    mode: str = field(default_factory=lambda: os.getenv("ORCHESTRATION_MODE", "converse"))


@dataclass(frozen=True)
class RdsConfig:
    """RDS Postgres configuration. Credentials come from Secrets Manager."""

    host: str = field(default_factory=lambda: os.getenv("RDS_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("RDS_PORT", 5432))
    database: str = field(default_factory=lambda: os.getenv("RDS_DATABASE", "aws_driftguard"))
    user: str = field(default_factory=lambda: os.getenv("RDS_USER", "driftguard"))
    # Either a literal password (dev) or a Secrets Manager secret id (prod).
    password: str = field(default_factory=lambda: os.getenv("RDS_PASSWORD", ""))
    password_secret_id: str = field(default_factory=lambda: os.getenv("RDS_PASSWORD_SECRET_ID", ""))

    def resolved_password(self, region: str = "") -> str:
        if self.password_secret_id:
            from .secrets_aws import get_secret_json

            bundle = get_secret_json(self.password_secret_id, region)
            return bundle.get("password", bundle.get("value", ""))
        return self.password

    def dsn(self, region: str = "") -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.resolved_password(region)}"
        )


@dataclass(frozen=True)
class JiraConfig:
    base_url: str = field(default_factory=lambda: os.getenv("JIRA_BASE_URL", ""))
    email: str = field(default_factory=lambda: os.getenv("JIRA_EMAIL", ""))
    api_token: str = field(default_factory=lambda: os.getenv("JIRA_API_TOKEN", ""))
    api_token_secret_id: str = field(default_factory=lambda: os.getenv("JIRA_API_TOKEN_SECRET_ID", ""))
    project_key: str = field(default_factory=lambda: os.getenv("JIRA_PROJECT_KEY", ""))
    acli_path: str = field(default_factory=lambda: os.getenv("JIRA_ACLI_PATH", "acli"))
    timeout_seconds: int = field(default_factory=lambda: _int("JIRA_TIMEOUT_SECONDS", 10))
    api_version: str = field(default_factory=lambda: os.getenv("JIRA_API_VERSION", "3"))

    def resolved_token(self, region: str = "") -> str:
        if self.api_token_secret_id:
            from .secrets_aws import get_secret

            return get_secret(self.api_token_secret_id, region)
        return self.api_token


@dataclass(frozen=True)
class GitHubConfig:
    api_base: str = field(default_factory=lambda: os.getenv("GITHUB_API_BASE", "https://api.github.com"))
    repo_owner: str = field(default_factory=lambda: os.getenv("GITHUB_REPO_OWNER", ""))
    repo_name: str = field(default_factory=lambda: os.getenv("GITHUB_REPO_NAME", ""))
    default_branch: str = field(default_factory=lambda: os.getenv("GITHUB_DEFAULT_BRANCH", "main"))
    auth_mode: str = field(default_factory=lambda: os.getenv("GITHUB_AUTH_MODE", "pat"))
    pat: str = field(default_factory=lambda: os.getenv("GITHUB_PAT", ""))
    pat_secret_id: str = field(default_factory=lambda: os.getenv("GITHUB_PAT_SECRET_ID", ""))
    app_id: str = field(default_factory=lambda: os.getenv("GITHUB_APP_ID", ""))
    app_installation_id: str = field(default_factory=lambda: os.getenv("GITHUB_APP_INSTALLATION_ID", ""))
    app_private_key_path: str = field(default_factory=lambda: os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", ""))
    app_private_key_secret_id: str = field(
        default_factory=lambda: os.getenv("GITHUB_APP_PRIVATE_KEY_SECRET_ID", ""))
    timeout_seconds: int = field(default_factory=lambda: _int("GITHUB_TIMEOUT_SECONDS", 20))

    def resolved_pat(self, region: str = "") -> str:
        if self.pat_secret_id:
            from .secrets_aws import get_secret

            return get_secret(self.pat_secret_id, region)
        return self.pat


@dataclass(frozen=True)
class PipelineConfig:
    capture_enabled: bool = field(default_factory=lambda: _bool("CAPTURE_ENABLED", False))
    capture_dir: str = field(default_factory=lambda: os.getenv("CAPTURE_DIR", "/tmp/aws-driftguard-eval"))
    skills_root: str = field(default_factory=lambda: os.getenv("SKILLS_ROOT", "skills"))
    skills_source: str = field(default_factory=lambda: os.getenv("SKILLS_SOURCE", "local"))
    skills_repo_owner: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_OWNER", ""))
    skills_repo_name: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_NAME", ""))
    skills_repo_ref: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_REF", ""))
    skills_repo_path: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_PATH", "skills"))
    skills_cache_ttl: int = field(default_factory=lambda: int(os.getenv("SKILLS_CACHE_TTL", "300")))
    release_feed_url: str = field(
        default_factory=lambda: os.getenv(
            "RELEASE_FEED_URL", "https://aws.amazon.com/about-aws/whats-new/recent/feed/"
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
    bedrock: BedrockConfig = field(default_factory=BedrockConfig)
    agents: BedrockAgentsConfig = field(default_factory=BedrockAgentsConfig)
    rds: RdsConfig = field(default_factory=RdsConfig)
    jira: JiraConfig = field(default_factory=JiraConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the process-wide config singleton."""
    return Config()
