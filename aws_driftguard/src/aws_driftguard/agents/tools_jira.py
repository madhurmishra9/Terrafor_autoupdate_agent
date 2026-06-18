"""Tools for JiraAgent: search, create, comment — ADF, 3-tier connectivity."""
from __future__ import annotations

from typing import Any

from ..common import adf
from ..common.jira_client import JiraClient, JiraUnreachable
from ..common.logging_setup import get_logger
from ..common.taxonomy import resolve

logger = get_logger(__name__)


def search_existing_jira(product: str, version: str, release_date: str) -> dict[str, Any]:
    """Search for an existing ticket for this release by JQL."""
    from ..common.config import get_config

    project = get_config().jira.project_key
    summary_token = f"{product} {version}".strip()
    jql = (
        f'project = "{project}" AND summary ~ "{summary_token}" '
        f'ORDER BY created DESC'
    )
    try:
        result = JiraClient().search_issue(jql)
        return {
            "found": bool(result.data.get("key")),
            "ticket_number": result.data.get("key", ""),
            "ticket_url": result.data.get("url", ""),
            "connectivity_tier": result.tier,
        }
    except JiraUnreachable as exc:
        logger.error("Jira search unreachable: %s", exc)
        return {"found": False, "error": "jira_unreachable"}


def create_jira_ticket(
    *, product: str, version: str, release_date: str, classification: str,
    short_description: str, summary_text: str, analysis_text: str, release_url: str = "",
) -> dict[str, Any]:
    """Create a Jira ticket with an ADF description and the correct issue type."""
    mapping = resolve(classification)
    description = adf.release_ticket_description(
        product=product, version=version, release_date=release_date,
        classification=classification, summary=summary_text, analysis=analysis_text,
        release_url=release_url or None,
    )
    summary = f"[Evergreen] {product} {version} — {short_description}".strip()
    try:
        result = JiraClient().create_issue(
            summary=summary,
            description_adf=description,
            issue_type=mapping.jira_issue_type,
            labels=["aws-driftguard", "auto-generated", classification],
        )
        return {
            "ticket_number": result.data.get("key", ""),
            "ticket_url": result.data.get("url", ""),
            "action": "created",
            "classification": classification,
            "short_description": short_description[:50],
            "connectivity_tier": result.tier,
        }
    except JiraUnreachable as exc:
        logger.error("Jira create unreachable: %s", exc)
        return {"error": "jira_unreachable"}


def add_jira_comment(issue_key: str, message: str, timestamp: str, pr_url: str = "") -> dict[str, Any]:
    """Add an ADF comment to a ticket, with session timestamp and optional PR link."""
    body = adf.comment_with_timestamp(message, timestamp, pr_url=pr_url or None)
    try:
        result = JiraClient().add_comment(issue_key, body)
        return {
            "ticket_number": issue_key,
            "action": "commented",
            "connectivity_tier": result.tier,
        }
    except JiraUnreachable as exc:
        logger.error("Jira comment unreachable: %s", exc)
        return {"error": "jira_unreachable"}
