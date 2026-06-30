"""Pipeline stage specifications (the 7 agents as data).

This is the cloud-neutral description of the pipeline: each stage's name, model
tier, skill file, tools, output state key, and whether it needs a connectivity
guard. Both the runnable Converse orchestrator and the managed Bedrock Agents
IaC generator consume this list, so the pipeline shape is defined once.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageSpec:
    name: str
    skill: str
    output_key: str
    tools: list[str]
    model_tier: str = "pro"          # "pro" | "fast"
    guard: str = "stop"              # "stop" | "stop+github" | "stop+jira" | "none"


STAGES: list[StageSpec] = [
    StageSpec(
        name="IngestAgent",
        skill="skills/ingest/SKILL.md",
        output_key="release_notes",
        model_tier="fast",
        guard="none",
        tools=["list_feeds", "fetch_aws_release_notes", "parse_xml_entry", "list_aws_products",
               "get_current_timestamp", "score_release_relevance"],
    ),
    StageSpec(
        name="ClassifyAgent",
        skill="skills/classify/SKILL.md",
        output_key="classification_result",
        model_tier="fast",
        tools=["check_existing_release_note", "save_classification_to_database",
               "get_current_timestamp"],
    ),
    StageSpec(
        name="AnalyzeAgent",
        skill="skills/analyze/SKILL.md",
        output_key="change_analyser_result",
        tools=["search_terraform_support", "check_org_policy_support", "list_product_resources", "resolve_attribute_owner", "list_family_schema", "fetch_webpage"],
    ),
    StageSpec(
        name="DecideAgent",
        skill="skills/decide/SKILL.md",
        output_key="decision_maker_result",
        guard="stop+github",
        tools=["get_module_file", "list_module_path", "fetch_webpage"],
    ),
    StageSpec(
        name="GenerateAgent",
        skill="skills/generate/SKILL.md",
        output_key="terraform_result",
        tools=["list_artifact_files", "load_artifacts", "save_artifacts_from_content",
               "check_patch_scope", "strip_patch_scope",
               "get_provider_schema", "extract_resource_schema", "check_version_pin",
               "validate_hcl", "plan_hcl", "verify_patch", "judge_patch",
               "search_terraform_support"],
    ),
    StageSpec(
        name="TicketAgent",
        skill="skills/ticket/SKILL.md",
        output_key="jira_result",
        guard="stop+jira",
        tools=["search_existing_jira", "create_jira_ticket", "add_jira_comment",
               "get_current_timestamp"],
    ),
    StageSpec(
        name="PublishAgent",
        skill="skills/publish/SKILL.md",
        output_key="pr_result",
        guard="stop+github",
        tools=["compute_pr_title", "find_existing_pr", "open_pull_request",
               "comment_on_existing_pr", "link_pr_to_jira", "get_current_timestamp"],
    ),
]
