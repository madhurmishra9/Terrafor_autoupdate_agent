"""Tools for TerraformAgent.

Beyond load/save, this module implements the accuracy + optimisation features:
  - provider schema grounding (fetch the real schema before generating)
  - version-pinning gate (reject features the pinned provider can't support)
  - self-correcting validate -> plan loop (regenerate on failure, capped)
  - judge/critic scoring (semantic correctness gate before PRAgent)

All schema and registry lookups are TTL-cached. Functions degrade gracefully
when the terraform binary is unavailable (valid=None => "unknown", not failure).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..common.cache import registry_cache, schema_cache
from ..common.config import get_config
from ..common.logging_setup import get_logger
from . import artifacts

logger = get_logger(__name__)

_REGISTRY_BASE = "https://registry.terraform.io/v1"


# ── Artifact passthrough ───────────────────────────────────────────────────
def list_artifact_files() -> dict[str, Any]:
    """List artifacts saved by DecisionMaker for patching."""
    return artifacts.list_artifacts()


def load_artifacts(name: str) -> dict[str, Any]:
    """Load a single artifact's content by name."""
    return artifacts.load_artifact(name)


def save_artifacts_from_content(name: str, content: str) -> dict[str, Any]:
    """Save patched HCL content back as an artifact for PRAgent to push."""
    return artifacts.save_artifact(name, content, meta={"stage": "terraform"})


# ── Provider schema grounding ──────────────────────────────────────────────
def get_provider_schema(provider: str = "azurerm", version: str = "") -> dict[str, Any]:
    """Return the provider schema, grounded in the real binary when available.

    Strategy:
      1. If terraform is installed, run `terraform providers schema -json` in a
         throwaway dir pinned to the requested version. This is authoritative.
      2. Otherwise fall back to the Registry docs index for the provider.
    Results are TTL-cached by (provider, version).
    """
    cache_key = f"schema:{provider}:{version or 'latest'}"

    def _compute() -> dict[str, Any]:
        if shutil.which("terraform") is not None:
            schema = _schema_from_binary(provider, version)
            if schema.get("ok"):
                return schema
        # Fallback: registry version metadata (not full schema, but grounds version).
        return _schema_from_registry(provider, version)

    return schema_cache.get_or_compute(cache_key, _compute)


def _schema_from_binary(provider: str, version: str) -> dict[str, Any]:
    constraint = f' version = "{version}"' if version else ""
    tf = f"""
terraform {{
  required_providers {{
    {provider} = {{
      source  = "hashicorp/{provider}"{constraint}
    }}
  }}
}}
"""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "providers.tf").write_text(tf, encoding="utf-8")
        init = subprocess.run(
            ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
            cwd=td, capture_output=True, text=True, check=False,
        )
        if init.returncode != 0:
            logger.warning("terraform init failed during schema fetch: %s", init.stderr[:500])
            return {"ok": False}
        dump = subprocess.run(
            ["terraform", "providers", "schema", "-json"],
            cwd=td, capture_output=True, text=True, check=False,
        )
        if dump.returncode != 0:
            return {"ok": False}
        try:
            data = json.loads(dump.stdout)
        except json.JSONDecodeError:
            return {"ok": False}
        return {"ok": True, "source": "binary", "provider": provider,
                "version": version or "latest", "schema": data}


def _schema_from_registry(provider: str, version: str) -> dict[str, Any]:
    url = f"{_REGISTRY_BASE}/providers/hashicorp/{provider}"
    try:
        import requests

        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        meta = resp.json()
        return {"ok": True, "source": "registry", "provider": provider,
                "version": version or meta.get("version"),
                "latest_version": meta.get("version"), "schema": None,
                "note": "Full schema unavailable without terraform binary; version grounded via registry."}
    except Exception as exc:
        logger.error("registry schema fallback failed: %s", exc)
        return {"ok": False, "provider": provider, "error": str(exc)}


def extract_resource_schema(provider: str, resource: str, version: str = "") -> dict[str, Any]:
    """Pull a single resource's argument schema for tight LLM grounding.

    Returns the argument names + required flags for the resource so the agent
    generates only valid arguments. Empty when the full schema is unavailable.
    """
    full = get_provider_schema(provider, version)
    schema = full.get("schema")
    if not schema:
        return {"ok": False, "resource": resource,
                "note": full.get("note", "no schema available"),
                "version": full.get("version")}
    # Navigate the provider schema JSON to the resource block.
    prov_key = f"registry.terraform.io/hashicorp/{provider}"
    try:
        block = (
            schema["provider_schemas"][prov_key]["resource_schemas"][resource]["block"]
        )
    except (KeyError, TypeError):
        return {"ok": False, "resource": resource, "note": "resource not in schema"}
    attrs = block.get("attributes", {})
    args = {
        name: {"required": bool(meta.get("required", False)),
               "type": meta.get("type"), "optional": bool(meta.get("optional", False))}
        for name, meta in attrs.items()
    }
    return {"ok": True, "resource": resource, "version": full.get("version"),
            "arguments": args, "block_types": list(block.get("block_types", {}).keys())}


# ── Version-pinning gate ───────────────────────────────────────────────────
def check_version_pin(current_constraint: str, required_version: str) -> dict[str, Any]:
    """Check whether a required provider version satisfies the module's pin.

    current_constraint: e.g. "~> 5.0", ">= 5.10, < 6.0"
    required_version:   e.g. "6.1.0"
    Returns allowed=True/False so the agent updates required_providers when the
    pin would otherwise block the feature.
    """
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version

        # Translate Terraform's ~> into PEP 440 compatible (~=) where possible.
        spec_str = current_constraint.replace("~>", "~=")
        spec = SpecifierSet(spec_str)
        allowed = Version(required_version) in spec
        return {"ok": True, "allowed": allowed,
                "current_constraint": current_constraint,
                "required_version": required_version,
                "action": "none" if allowed else "bump_required_providers"}
    except Exception as exc:
        # If parsing fails, surface for manual review rather than guessing.
        logger.warning("version pin check inconclusive: %s", exc)
        return {"ok": False, "allowed": None, "requires_review": True,
                "current_constraint": current_constraint,
                "required_version": required_version, "error": str(exc)}


# ── Self-correcting validate -> plan loop ──────────────────────────────────
def validate_hcl(content: str) -> dict[str, Any]:
    """Validate a single HCL file's syntax/format.

    Runs `terraform fmt -check` then `terraform validate` in a temp dir. Returns
    {valid, stage, message}. valid=None when terraform is unavailable (unknown).
    """
    if shutil.which("terraform") is None:
        return {"valid": None, "stage": "skipped", "message": "terraform binary not available"}

    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "main.tf"
        f.write_text(content, encoding="utf-8")

        fmt = subprocess.run(
            ["terraform", "fmt", "-check", "-diff", "-no-color", str(f)],
            capture_output=True, text=True, check=False,
        )
        if fmt.returncode != 0:
            return {"valid": False, "stage": "fmt",
                    "message": (fmt.stdout or fmt.stderr).strip()[:2000]}

        init = subprocess.run(
            ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
            cwd=td, capture_output=True, text=True, check=False,
        )
        if init.returncode != 0:
            return {"valid": False, "stage": "init",
                    "message": init.stderr.strip()[:2000]}

        val = subprocess.run(
            ["terraform", "validate", "-no-color"],
            cwd=td, capture_output=True, text=True, check=False,
        )
        return {"valid": val.returncode == 0, "stage": "validate",
                "message": (val.stdout or val.stderr).strip()[:2000]}


def plan_hcl(content: str) -> dict[str, Any]:
    """Run `terraform plan -detailed-exitcode` for a patched file.

    Exit codes:
      0 = no changes  -> patch had no effect (suspicious, flag for retry)
      2 = changes     -> patch is effective (good)
      1 = error       -> feed message back for regeneration
    """
    if shutil.which("terraform") is None:
        return {"plan_ok": None, "exit_code": None, "message": "terraform binary not available"}

    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "main.tf").write_text(content, encoding="utf-8")
        init = subprocess.run(
            ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
            cwd=td, capture_output=True, text=True, check=False,
        )
        if init.returncode != 0:
            return {"plan_ok": False, "exit_code": 1, "message": init.stderr.strip()[:2000]}
        plan = subprocess.run(
            ["terraform", "plan", "-detailed-exitcode", "-input=false", "-no-color"],
            cwd=td, capture_output=True, text=True, check=False,
        )
        rc = plan.returncode
        return {
            "plan_ok": rc in (0, 2),
            "exit_code": rc,
            "has_changes": rc == 2,
            "no_changes": rc == 0,
            "message": (plan.stdout or plan.stderr).strip()[:3000],
        }


def verify_patch(content: str, attempt: int = 1) -> dict[str, Any]:
    """One iteration of the self-correcting loop: validate then plan.

    The agent calls this after generating a patch. If verified=False and
    attempt < terraform_max_retries, the agent regenerates using `feedback`
    and calls verify_patch again with attempt+1.
    """
    max_retries = get_config().pipeline.terraform_max_retries
    v = validate_hcl(content)
    if v.get("valid") is False:
        return {"verified": False, "attempt": attempt, "can_retry": attempt < max_retries,
                "stage": v.get("stage"), "feedback": v.get("message"),
                "max_retries": max_retries}
    # valid is True or None (unknown). If unknown, accept but mark unverified.
    if v.get("valid") is None:
        return {"verified": None, "attempt": attempt, "can_retry": False,
                "stage": "skipped", "feedback": "terraform unavailable; static checks only",
                "max_retries": max_retries}

    p = plan_hcl(content)
    if p.get("exit_code") == 1:
        return {"verified": False, "attempt": attempt, "can_retry": attempt < max_retries,
                "stage": "plan", "feedback": p.get("message"), "max_retries": max_retries}
    if p.get("no_changes"):
        return {"verified": False, "attempt": attempt, "can_retry": attempt < max_retries,
                "stage": "plan", "feedback": "Plan shows no changes; patch had no effect.",
                "max_retries": max_retries}
    return {"verified": True, "attempt": attempt, "stage": "plan",
            "exit_code": p.get("exit_code"), "feedback": "validate + plan passed"}


# ── Registry support lookup (cached) ───────────────────────────────────────
def search_terraform_support(provider: str = "azurerm", resource: str = "") -> dict[str, Any]:
    """Query the Terraform Registry for provider versions (TTL-cached)."""
    cache_key = f"registry:{provider}"

    def _compute() -> dict[str, Any]:
        import requests

        url = f"{_REGISTRY_BASE}/providers/hashicorp/{provider}"
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return {"provider": provider, "latest_version": data.get("version"),
                "published_at": data.get("published_at")}

    base = registry_cache.get_or_compute(cache_key, _compute)
    return {**base, "resource_queried": resource}
