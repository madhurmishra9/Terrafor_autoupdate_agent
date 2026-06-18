"""Central configuration sourced from environment variables.

All runtime configuration is read from the environment so the same image runs
across local, dev, and prod by changing env vars / K8s Secrets only. No values
are hardcoded.
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


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return val


@dataclass(frozen=True)
class GcpConfig:
    project: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    location: str = field(default_factory=lambda: os.getenv("VERTEX_LOCATION", "us-central1"))
    # Default ("pro") model used for reasoning-heavy agents.
    model: str = field(default_factory=lambda: os.getenv("VERTEX_MODEL", "gemini-2.5-pro"))
    # Cheaper/faster model for parsing + bucketing agents (tiered routing).
    model_fast: str = field(default_factory=lambda: os.getenv("VERTEX_MODEL_FAST", "gemini-2.5-flash"))
    # Judge model: defaults to fast to keep the extra critic pass cheap.
    model_judge: str = field(default_factory=lambda: os.getenv("VERTEX_MODEL_JUDGE", "gemini-2.5-flash"))


@dataclass(frozen=True)
class CloudSqlConfig:
    host: str = field(default_factory=lambda: os.getenv("CLOUDSQL_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("CLOUDSQL_PORT", "5432")))
    database: str = field(default_factory=lambda: os.getenv("CLOUDSQL_DATABASE", "terraform_driftguard"))
    user: str = field(default_factory=lambda: os.getenv("CLOUDSQL_USER", "terraform_driftguard"))
    password: str = field(default_factory=lambda: os.getenv("CLOUDSQL_PASSWORD", ""))

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )


@dataclass(frozen=True)
class JiraConfig:
    base_url: str = field(default_factory=lambda: os.getenv("JIRA_BASE_URL", ""))
    email: str = field(default_factory=lambda: os.getenv("JIRA_EMAIL", ""))
    api_token: str = field(default_factory=lambda: os.getenv("JIRA_API_TOKEN", ""))
    project_key: str = field(default_factory=lambda: os.getenv("JIRA_PROJECT_KEY", ""))
    acli_path: str = field(default_factory=lambda: os.getenv("JIRA_ACLI_PATH", "acli"))
    timeout_seconds: int = field(default_factory=lambda: int(os.getenv("JIRA_TIMEOUT_SECONDS", "10")))
    # api/v3 is Jira Cloud (ADF body). api/v2 is Server/DC (wiki markup).
    api_version: str = field(default_factory=lambda: os.getenv("JIRA_API_VERSION", "3"))


@dataclass(frozen=True)
class GitHubConfig:
    # Base for GitHub Enterprise Server is like https://ghe.corp/api/v3
    # For github.com it is https://api.github.com
    api_base: str = field(default_factory=lambda: os.getenv("GITHUB_API_BASE", "https://api.github.com"))
    repo_owner: str = field(default_factory=lambda: os.getenv("GITHUB_REPO_OWNER", ""))
    repo_name: str = field(default_factory=lambda: os.getenv("GITHUB_REPO_NAME", ""))
    default_branch: str = field(default_factory=lambda: os.getenv("GITHUB_DEFAULT_BRANCH", "main"))
    # Auth mode: "pat" or "app"
    auth_mode: str = field(default_factory=lambda: os.getenv("GITHUB_AUTH_MODE", "pat"))
    # PAT mode
    pat: str = field(default_factory=lambda: os.getenv("GITHUB_PAT", ""))
    # GitHub App mode
    app_id: str = field(default_factory=lambda: os.getenv("GITHUB_APP_ID", ""))
    app_installation_id: str = field(default_factory=lambda: os.getenv("GITHUB_APP_INSTALLATION_ID", ""))
    app_private_key_path: str = field(default_factory=lambda: os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", ""))
    timeout_seconds: int = field(default_factory=lambda: int(os.getenv("GITHUB_TIMEOUT_SECONDS", "20")))


@dataclass(frozen=True)
class PipelineConfig:
    capture_enabled: bool = field(default_factory=lambda: _bool("CAPTURE_ENABLED", False))
    capture_dir: str = field(default_factory=lambda: os.getenv("CAPTURE_DIR", "/tmp/terraform-driftguard-eval"))
    skills_root: str = field(default_factory=lambda: os.getenv("SKILLS_ROOT", "skills"))
    # Skills source: "local" (image-baked / mounted) or "github" (repo as the
    # single source of truth, fetched at runtime — no redeploy to change skills).
    skills_source: str = field(default_factory=lambda: os.getenv("SKILLS_SOURCE", "local"))
    # GitHub location of the skills tree when skills_source == "github".
    # Defaults reuse the module repo + a "skills" subdir on the default branch,
    # but can point at a dedicated skills repo / branch / path.
    skills_repo_owner: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_OWNER", ""))
    skills_repo_name: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_NAME", ""))
    skills_repo_ref: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_REF", ""))
    skills_repo_path: str = field(default_factory=lambda: os.getenv("SKILLS_REPO_PATH", "skills"))
    # TTL for the runtime skills cache (seconds). 0 disables caching.
    skills_cache_ttl: int = field(default_factory=lambda: int(os.getenv("SKILLS_CACHE_TTL", "300")))
    # Release-notes feed
    release_feed_url: str = field(
        default_factory=lambda: os.getenv(
            "GCP_RELEASE_FEED_URL", "https://cloud.google.com/feeds/gcp-release-notes.xml"
        )
    )
    terraform_module_path: str = field(
        default_factory=lambda: os.getenv("TERRAFORM_MODULE_PATH", "modules")
    )
    # ── Accuracy / optimisation feature toggles ────────────────────────────
    # Self-correcting validate->plan loop: max regeneration attempts.
    terraform_max_retries: int = field(
        default_factory=lambda: int(os.getenv("TERRAFORM_MAX_RETRIES", "3"))
    )
    # Judge/critic pass after generation. Patches must score >= threshold.
    judge_enabled: bool = field(default_factory=lambda: _bool("JUDGE_ENABLED", True))
    judge_min_score: int = field(
        default_factory=lambda: int(os.getenv("JUDGE_MIN_SCORE", "70"))
    )
    # TTL cache for provider schema + registry lookups (seconds).
    cache_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "86400"))
    )
    # Embedding-based relevance filter to skip irrelevant releases early.
    relevance_filter_enabled: bool = field(
        default_factory=lambda: _bool("RELEVANCE_FILTER_ENABLED", True)
    )
    # Batch size for classification calls (avoids large-batch JSON errors).
    classification_batch_size: int = field(
        default_factory=lambda: int(os.getenv("CLASSIFICATION_BATCH_SIZE", "5"))
    )


@dataclass(frozen=True)
class Config:
    gcp: GcpConfig = field(default_factory=GcpConfig)
    cloudsql: CloudSqlConfig = field(default_factory=CloudSqlConfig)
    jira: JiraConfig = field(default_factory=JiraConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the process-wide config singleton."""
    return Config()
