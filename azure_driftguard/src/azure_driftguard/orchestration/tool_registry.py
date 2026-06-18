"""Tool registry: expose the shared Python tools to Bedrock Converse / Agents.

Each pipeline tool is a plain Python function returning a dict. This module
introspects them into Bedrock `toolSpec` entries and provides a dispatcher that
executes a tool by name with a kwargs dict. The same registry backs both the
Converse tool-use orchestrator and the Lambda action-group handler used by the
managed Bedrock Agents path.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from ..agents import (
    tools_analysis,
    tools_ingest,
    tools_jira,
    tools_judge,
    tools_pr,
    tools_relevance,
    tools_terraform,
)
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

# Master catalogue of every callable tool, keyed by name.
_CATALOGUE: dict[str, Callable[..., Any]] = {}


def _register(module: Any, names: list[str]) -> None:
    for name in names:
        fn = getattr(module, name)
        _CATALOGUE[name] = fn


_register(tools_ingest, [
    "fetch_azure_release_notes", "parse_xml_entry", "list_azure_products",
    "get_current_timestamp", "check_existing_release_note",
    "save_classification_to_database",
])
_register(tools_relevance, ["score_release_relevance"])
_register(tools_analysis, [
    "search_terraform_support", "check_org_policy_support", "fetch_webpage",
    "get_module_file", "list_module_path",
])
_register(tools_terraform, [
    "list_artifact_files", "load_artifacts", "save_artifacts_from_content",
    "get_provider_schema", "extract_resource_schema", "check_version_pin",
    "validate_hcl", "plan_hcl", "verify_patch", "search_terraform_support",
])
_register(tools_judge, ["judge_patch"])
_register(tools_jira, ["search_existing_jira", "create_jira_ticket", "add_jira_comment"])
_register(tools_pr, [
    "compute_pr_title", "find_existing_pr", "open_pull_request",
    "comment_on_existing_pr", "link_pr_to_jira",
])


def _py_type_to_json(annotation: Any) -> str:
    mapping = {int: "integer", float: "number", bool: "boolean", str: "string"}
    return mapping.get(annotation, "string")


def tool_spec(name: str) -> dict[str, Any]:
    """Build a Bedrock toolSpec for a single registered tool from its signature."""
    fn = _CATALOGUE[name]
    sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in {"self", "args", "kwargs"}:
            continue
        props[pname] = {"type": _py_type_to_json(param.annotation),
                        "description": pname.replace("_", " ")}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "toolSpec": {
            "name": name,
            "description": (fn.__doc__ or name).strip().split("\n")[0],
            "inputSchema": {"json": {
                "type": "object", "properties": props, "required": required,
            }},
        }
    }


def specs_for(names: list[str]) -> list[dict[str, Any]]:
    return [tool_spec(n) for n in names]


def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a registered tool by name. Returns its dict result (or an error)."""
    fn = _CATALOGUE.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return fn(**arguments)
    except TypeError as exc:
        logger.warning("tool %s bad args: %s", name, exc)
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:  # tool-level failures are returned, not raised
        logger.warning("tool %s failed: %s", name, exc)
        return {"error": f"{name} failed: {exc}"}


def all_tool_names() -> list[str]:
    return sorted(_CATALOGUE.keys())


def openai_tool_spec(name: str) -> dict[str, Any]:
    """Build an Azure OpenAI function-tool spec for a registered tool."""
    fn = _CATALOGUE[name]
    sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in {"self", "args", "kwargs"}:
            continue
        props[pname] = {"type": _py_type_to_json(param.annotation),
                        "description": pname.replace("_", " ")}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (fn.__doc__ or name).strip().split("\n")[0],
            "parameters": {
                "type": "object", "properties": props, "required": required,
            },
        },
    }


def openai_specs_for(names: list[str]) -> list[dict[str, Any]]:
    return [openai_tool_spec(n) for n in names]
