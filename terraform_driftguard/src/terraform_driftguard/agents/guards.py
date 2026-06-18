"""Connectivity guards used as before-agent callbacks.

Each guard probes an external dependency. On failure it halts the pipeline so a
downstream agent never runs without the resource it requires (which would
produce empty or wrong artifacts).
"""
from __future__ import annotations

from typing import Any

from ..common.github_client import GitHubClient
from ..common.jira_client import JiraClient
from ..common.logging_setup import get_logger
from ..common.state import halt_pipeline

logger = get_logger(__name__)


def jira_connectivity_guard(callback_context: Any) -> None:
    """Probe Jira across all 3 tiers; halt if none respond."""
    tier = JiraClient().probe()
    if tier is None:
        halt_pipeline(callback_context.state, "jira_unreachable")
    else:
        logger.info("Jira reachable via tier: %s", tier)


def github_connectivity_guard(callback_context: Any) -> None:
    """Probe GitHub repo access; halt if unreachable."""
    if not GitHubClient().probe():
        halt_pipeline(callback_context.state, "github_unreachable")
