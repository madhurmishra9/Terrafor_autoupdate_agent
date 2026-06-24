"""Tools for PublishAgent: branch, push patched files, open PR, link back to Jira."""
from __future__ import annotations

from typing import Any

from ..common.github_client import GitHubClient
from ..common.logging_setup import get_logger
from ..common.taxonomy import resolve
from . import artifacts
from .tools_jira import add_jira_comment

logger = get_logger(__name__)


def compute_pr_title(classification: str, ticket_number: str, short_description: str) -> dict[str, Any]:
    """Compute the PR title using the TicketAgent-owned prefix mapping."""
    mapping = resolve(classification)
    title = f"{mapping.pr_prefix} {ticket_number} {short_description}".strip()
    return {"title": title, "prefix": mapping.pr_prefix}


def branch_name_for(ticket_number: str) -> dict[str, Any]:
    return {"branch": f"tf-code-updater/{ticket_number}"}


def find_existing_pr(branch: str) -> dict[str, Any]:
    """Return an open PR for the branch if one exists."""
    prs = GitHubClient().list_pull_requests(head=branch, state="open")
    if prs:
        pr = prs[0]
        return {"exists": True, "number": pr["number"], "url": pr["html_url"]}
    return {"exists": False}


def open_pull_request(
    *, ticket_number: str, classification: str, short_description: str,
    jira_url: str, analysis_summary: str, files: list[str],
) -> dict[str, Any]:
    """Create a branch, push patched artifacts, open a PR, link back to Jira."""
    client = GitHubClient()
    branch = f"tf-code-updater/{ticket_number}"
    mapping = resolve(classification)
    title = f"{mapping.pr_prefix} {ticket_number} {short_description}".strip()

    # Create branch (ignore if it already exists)
    try:
        client.create_branch(branch)
    except Exception as exc:
        logger.info("Branch may already exist (%s): %s", branch, exc)

    # Push each patched artifact
    pushed: list[str] = []
    for name in files:
        art = artifacts.load_artifact(name)
        if not art.get("exists"):
            continue
        # Resolve existing file sha if present (update vs create)
        sha = None
        try:
            existing = client.get_file(name, ref=branch)
            sha = existing.get("sha")
        except Exception:
            sha = None
        client.create_or_update_file(
            file_path=name, content=art["content"],
            message=f"{mapping.pr_prefix} {ticket_number} update {name}",
            branch=branch, sha=sha,
        )
        pushed.append(name)

    body = (
        f"## Azure DriftGuard update\n\n"
        f"**Jira:** {jira_url}\n\n"
        f"**Change type:** `{classification}`\n\n"
        f"### Analysis\n{analysis_summary}\n\n"
        f"### Files changed\n" + "\n".join(f"- `{f}`" for f in pushed)
    )
    pr = client.create_pull_request(title=title, body=body, head=branch)
    return {
        "pr_url": pr["html_url"],
        "pr_number": pr["number"],
        "action": "created",
        "branch": branch,
        "files_pushed": pushed,
    }


def comment_on_existing_pr(number: int, message: str, timestamp: str) -> dict[str, Any]:
    """Add a timestamped comment to an existing PR."""
    client = GitHubClient()
    body = f"_Azure DriftGuard pipeline re-run at {timestamp}_\n\n{message}"
    client.comment_on_issue(number, body)
    return {"pr_number": number, "action": "commented"}


def link_pr_to_jira(ticket_number: str, pr_url: str, timestamp: str) -> dict[str, Any]:
    """Comment the PR URL back onto the Jira ticket to close the loop."""
    result = add_jira_comment(
        ticket_number,
        message="Pull request opened for this release.",
        timestamp=timestamp,
        pr_url=pr_url,
    )
    return {"jira_linked_back": "error" not in result, **result}
