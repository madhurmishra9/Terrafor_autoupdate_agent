"""Unit tests for the accuracy + optimisation features (no ADK / network)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aws_driftguard.common import cache  # noqa: E402


def test_ttl_cache_hit_and_expiry():
    c = cache.TTLCache(ttl_seconds=1)
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return "value"

    assert c.get_or_compute("k", compute) == "value"
    assert c.get_or_compute("k", compute) == "value"  # cached, no recompute
    assert calls["n"] == 1
    time.sleep(1.1)
    assert c.get_or_compute("k", compute) == "value"  # expired -> recompute
    assert calls["n"] == 2


def test_ttl_cache_clear():
    c = cache.TTLCache(ttl_seconds=100)
    c.set("a", 1)
    assert c.get("a") == 1
    c.clear()
    assert c.get("a") is None


def test_version_pin_gate_allows_satisfied():
    from aws_driftguard.agents import tools_terraform as tt

    res = tt.check_version_pin(">= 5.0", "5.10.0")
    assert res["ok"] is True
    assert res["allowed"] is True
    assert res["action"] == "none"


def test_version_pin_gate_blocks_unsatisfied():
    from aws_driftguard.agents import tools_terraform as tt

    res = tt.check_version_pin(">= 5.0, < 6.0", "6.1.0")
    assert res["ok"] is True
    assert res["allowed"] is False
    assert res["action"] == "bump_required_providers"


def test_verify_patch_skips_without_terraform(monkeypatch):
    from aws_driftguard.agents import tools_terraform as tt

    # Force terraform-unavailable path.
    monkeypatch.setattr(tt.shutil, "which", lambda _name: None)
    res = tt.verify_patch("resource \"x\" \"y\" {}", attempt=1)
    assert res["verified"] is None
    assert res["stage"] == "skipped"


def test_judge_disabled_passes(monkeypatch):
    from aws_driftguard.agents import tools_judge
    from aws_driftguard.common import config

    config.get_config.cache_clear()
    monkeypatch.setenv("JUDGE_ENABLED", "false")
    res = tools_judge.judge_patch(requirement="add arg", patch="x = 1")
    assert res["passed"] is True
    assert res["skipped"] is True
    config.get_config.cache_clear()


def test_relevance_fail_open_without_sdk(monkeypatch):
    from aws_driftguard.agents import tools_relevance
    from aws_driftguard.common import config

    config.get_config.cache_clear()
    monkeypatch.setenv("RELEVANCE_FILTER_ENABLED", "true")
    # No genai SDK in the unit env -> _embed returns None -> fail open.
    res = tools_relevance.score_release_relevance("Amazon RDS new feature", "details")
    assert res["relevant"] is True
    assert res["method"] in {"fail_open", "embedding", "disabled"}
    config.get_config.cache_clear()


def test_tiered_models_configured(monkeypatch):
    from aws_driftguard.common import config

    config.get_config.cache_clear()
    monkeypatch.setenv("BEDROCK_MODEL", "anthropic.claude-sonnet-4-6-20260514-v1:0")
    monkeypatch.setenv("BEDROCK_MODEL_FAST", "anthropic.claude-haiku-4-5-20251001-v1:0")
    cfg = config.get_config()
    assert cfg.bedrock.model == "anthropic.claude-sonnet-4-6-20260514-v1:0"
    assert cfg.bedrock.model_fast == "anthropic.claude-haiku-4-5-20251001-v1:0"
    config.get_config.cache_clear()


def test_tool_registry_specs_and_dispatch():
    from aws_driftguard.orchestration import tool_registry

    names = tool_registry.all_tool_names()
    assert "check_version_pin" in names
    spec = tool_registry.tool_spec("check_version_pin")
    assert spec["toolSpec"]["name"] == "check_version_pin"
    # dispatch a pure tool (no network)
    res = tool_registry.dispatch("check_version_pin",
                                 {"current_constraint": ">= 5.0", "required_version": "5.10.0"})
    assert res["allowed"] is True


def test_stages_shape():
    from aws_driftguard.orchestration.stages import STAGES

    assert [s.name for s in STAGES][0] == "RequestProcessorAgent"
    assert [s.name for s in STAGES][-1] == "PRAgent"
    assert len(STAGES) == 7
    # Jira stage uses the jira connectivity guard; PR + Decision use github
    by_name = {s.name: s for s in STAGES}
    assert by_name["JiraAgent"].guard == "stop+jira"
    assert by_name["PRAgent"].guard == "stop+github"


def test_product_registry_loads_and_gates():
    from aws_driftguard.common.product_registry import ProductRegistry

    reg = ProductRegistry()
    assert "Amazon RDS" in reg.names()
    assert reg.is_allowed("Amazon RDS") is True
    assert reg.is_known("Amazon DynamoDB") is True
    assert reg.is_allowed("Amazon DynamoDB") is False
    assert reg.is_known("Nonexistent Service") is False


def test_product_registry_match_and_paths():
    from aws_driftguard.common.product_registry import ProductRegistry

    reg = ProductRegistry()
    m = reg.match("Amazon RDS now supports storage autoscaling")
    assert m is not None and m.name == "Amazon RDS"
    assert "modules/rds" in reg.module_paths_for("Amazon RDS")


def test_skills_source_local_default():
    from aws_driftguard.common import skills_source

    assert skills_source.describe_source().startswith("local://")
    text = skills_source.read_text("skills/terraform/SKILL.md")
    assert "TerraformAgent" in text
    names = skills_source.list_dir("skills/products")
    assert any(n.endswith(".yaml") for n in names)


def test_skills_source_github_mode(monkeypatch):
    import base64
    from aws_driftguard.common import config, skills_source

    config.get_config.cache_clear()
    monkeypatch.setenv("SKILLS_SOURCE", "github")
    monkeypatch.setenv("SKILLS_REPO_OWNER", "org")
    monkeypatch.setenv("SKILLS_REPO_NAME", "repo")
    monkeypatch.setenv("SKILLS_REPO_REF", "main")

    def fake(path, params):
        if path.endswith("SKILL.md"):
            return {"content": base64.b64encode(b"# gh skill").decode()}
        return [{"name": "x.yaml", "type": "file"}]

    monkeypatch.setattr(skills_source, "_gh_request", fake)
    assert skills_source.describe_source() == "github://org/repo@main/skills"
    assert skills_source.read_text("skills/terraform/SKILL.md") == "# gh skill"
    assert skills_source.list_dir("skills/products") == ["x.yaml"]
    config.get_config.cache_clear()
