"""Agent definitions: 7 LlmAgents wired with skills, tools, and guards.

Each agent loads its instruction from skills/<name>/SKILL.md via the skill
instruction provider (per-invocation read => hot reload). Behaviour lives in the
skill; this module only wires structure: name, output_key, before_cb, tools.
"""
from __future__ import annotations

from typing import Any

from ..common.config import get_config
from ..common.logging_setup import get_logger
from ..common.state import (
    CHANGE_ANALYSER_RESULT,
    CLASSIFICATION_RESULT,
    DECISION_MAKER_RESULT,
    JIRA_RESULT,
    PR_RESULT,
    RELEASE_NOTES,
    TERRAFORM_RESULT,
    chain_guards,
    make_stop_guard,
)
from ..skills_loader import skill_instruction_provider
from . import (
    tools_analysis,
    tools_ingest,
    tools_jira,
    tools_judge,
    tools_pr,
    tools_relevance,
    tools_terraform,
)
from .guards import github_connectivity_guard, jira_connectivity_guard

logger = get_logger(__name__)


def _llm_agent(**kwargs: Any) -> Any:
    """Import LlmAgent lazily so unit tests can import this module without ADK."""
    from google.adk.agents import LlmAgent  # type: ignore

    return LlmAgent(**kwargs)


def build_agents() -> list[Any]:
    cfg = get_config()
    model = cfg.gcp.model            # reasoning-heavy agents
    model_fast = cfg.gcp.model_fast  # parsing / bucketing agents (tiered routing)

    ingest = _llm_agent(
        name="IngestAgent",
        model=model_fast,
        output_key=RELEASE_NOTES,
        instruction=skill_instruction_provider("skills/ingest/SKILL.md"),
        tools=[
            tools_ingest.list_feeds,
            tools_ingest.fetch_gcp_release_notes,
            tools_ingest.parse_xml_entry,
            tools_ingest.list_gcp_products,
            tools_ingest.get_current_timestamp,
            tools_relevance.score_release_relevance,
        ],
    )

    classify = _llm_agent(
        name="ClassifyAgent",
        model=model_fast,
        output_key=CLASSIFICATION_RESULT,
        instruction=skill_instruction_provider("skills/classify/SKILL.md"),
        before_agent_callback=make_stop_guard(CLASSIFICATION_RESULT),
        tools=[
            tools_ingest.check_existing_release_note,
            tools_ingest.save_classification_to_database,
            tools_ingest.get_current_timestamp,
        ],
    )

    analyze = _llm_agent(
        name="AnalyzeAgent",
        model=model,
        output_key=CHANGE_ANALYSER_RESULT,
        instruction=skill_instruction_provider("skills/analyze/SKILL.md"),
        before_agent_callback=make_stop_guard(CHANGE_ANALYSER_RESULT),
        tools=[
            tools_analysis.search_terraform_support,
            tools_analysis.check_org_policy_support,
            tools_analysis.list_product_resources,
            tools_analysis.resolve_attribute_owner,
            tools_analysis.list_family_schema,
            tools_analysis.fetch_webpage,
        ],
    )

    decide = _llm_agent(
        name="DecideAgent",
        model=model,
        output_key=DECISION_MAKER_RESULT,
        instruction=skill_instruction_provider("skills/decide/SKILL.md"),
        before_agent_callback=chain_guards(
            make_stop_guard(DECISION_MAKER_RESULT),
            github_connectivity_guard,
        ),
        tools=[
            tools_analysis.get_module_file,
            tools_analysis.list_module_path,
            tools_analysis.fetch_webpage,
        ],
    )

    generate = _llm_agent(
        name="GenerateAgent",
        model=model,
        output_key=TERRAFORM_RESULT,
        instruction=skill_instruction_provider("skills/generate/SKILL.md"),
        before_agent_callback=make_stop_guard(TERRAFORM_RESULT),
        tools=[
            tools_terraform.list_artifact_files,
            tools_terraform.load_artifacts,
            tools_terraform.save_artifacts_from_content,
            tools_terraform.check_patch_scope,
            tools_terraform.strip_patch_scope,
            # Provider schema grounding
            tools_terraform.get_provider_schema,
            tools_terraform.extract_resource_schema,
            # Version-pinning gate
            tools_terraform.check_version_pin,
            # Self-correcting validate -> plan loop
            tools_terraform.validate_hcl,
            tools_terraform.plan_hcl,
            tools_terraform.verify_patch,
            # Judge / critic pass
            tools_judge.judge_patch,
            tools_terraform.search_terraform_support,
        ],
    )

    ticket = _llm_agent(
        name="TicketAgent",
        model=model,
        output_key=JIRA_RESULT,
        instruction=skill_instruction_provider("skills/ticket/SKILL.md"),
        before_agent_callback=chain_guards(
            make_stop_guard(JIRA_RESULT),
            jira_connectivity_guard,
        ),
        tools=[
            tools_jira.search_existing_jira,
            tools_jira.create_jira_ticket,
            tools_jira.add_jira_comment,
            tools_ingest.get_current_timestamp,
        ],
    )

    publish = _llm_agent(
        name="PublishAgent",
        model=model,
        output_key=PR_RESULT,
        instruction=skill_instruction_provider("skills/publish/SKILL.md"),
        before_agent_callback=chain_guards(
            make_stop_guard(PR_RESULT),
            github_connectivity_guard,
        ),
        tools=[
            tools_pr.compute_pr_title,
            tools_pr.find_existing_pr,
            tools_pr.open_pull_request,
            tools_pr.comment_on_existing_pr,
            tools_pr.link_pr_to_jira,
            tools_ingest.get_current_timestamp,
        ],
    )

    return [ingest, classify, analyze, decide, generate, ticket, publish]
