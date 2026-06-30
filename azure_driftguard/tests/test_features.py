"""Unit tests for the accuracy + optimisation features (no ADK / network)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from azure_driftguard.common import cache  # noqa: E402


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
    from azure_driftguard.agents import tools_terraform as tt

    res = tt.check_version_pin(">= 5.0", "5.10.0")
    assert res["ok"] is True
    assert res["allowed"] is True
    assert res["action"] == "none"


def test_version_pin_gate_blocks_unsatisfied():
    from azure_driftguard.agents import tools_terraform as tt

    res = tt.check_version_pin(">= 5.0, < 6.0", "6.1.0")
    assert res["ok"] is True
    assert res["allowed"] is False
    assert res["action"] == "bump_required_providers"


def test_verify_patch_skips_without_terraform(monkeypatch):
    from azure_driftguard.agents import tools_terraform as tt

    # Force terraform-unavailable path.
    monkeypatch.setattr(tt.shutil, "which", lambda _name: None)
    res = tt.verify_patch("resource \"x\" \"y\" {}", attempt=1)
    assert res["verified"] is None
    assert res["stage"] == "skipped"


def test_judge_disabled_passes(monkeypatch):
    from azure_driftguard.agents import tools_judge
    from azure_driftguard.common import config

    config.get_config.cache_clear()
    monkeypatch.setenv("JUDGE_ENABLED", "false")
    res = tools_judge.judge_patch(requirement="add arg", patch="x = 1")
    assert res["passed"] is True
    assert res["skipped"] is True
    config.get_config.cache_clear()


def test_relevance_fail_open_without_sdk(monkeypatch):
    from azure_driftguard.agents import tools_relevance
    from azure_driftguard.common import config

    config.get_config.cache_clear()
    monkeypatch.setenv("RELEVANCE_FILTER_ENABLED", "true")
    # No genai SDK in the unit env -> _embed returns None -> fail open.
    res = tools_relevance.score_release_relevance("Azure SQL Database new feature", "details")
    assert res["relevant"] is True
    assert res["method"] in {"fail_open", "embedding", "disabled"}
    config.get_config.cache_clear()


def test_tiered_models_configured(monkeypatch):
    from azure_driftguard.common import config

    config.get_config.cache_clear()
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-4o-mini")
    cfg = config.get_config()
    assert cfg.openai.deployment == "gpt-4o"
    assert cfg.openai.deployment_fast == "gpt-4o-mini"
    config.get_config.cache_clear()


def test_tool_registry_specs_and_dispatch():
    from azure_driftguard.orchestration import tool_registry

    names = tool_registry.all_tool_names()
    assert "check_version_pin" in names
    spec = tool_registry.openai_tool_spec("check_version_pin")
    assert spec["function"]["name"] == "check_version_pin"
    res = tool_registry.dispatch("check_version_pin",
                                 {"current_constraint": ">= 5.0", "required_version": "5.10.0"})
    assert res["allowed"] is True


def test_stages_shape():
    from azure_driftguard.orchestration.stages import STAGES

    assert [s.name for s in STAGES][0] == "IngestAgent"
    assert [s.name for s in STAGES][-1] == "PublishAgent"
    assert len(STAGES) == 7
    by_name = {s.name: s for s in STAGES}
    assert by_name["TicketAgent"].guard == "stop+jira"
    assert by_name["PublishAgent"].guard == "stop+github"


def test_product_registry_loads_and_gates():
    from azure_driftguard.common.product_registry import ProductRegistry

    reg = ProductRegistry()
    assert "Azure SQL Database" in reg.names()
    assert reg.is_allowed("Azure SQL Database") is True
    assert reg.is_known("Azure Cosmos DB") is True
    assert reg.is_allowed("Azure Cosmos DB") is False
    assert reg.is_known("Nonexistent Service") is False


def test_product_registry_match_and_paths():
    from azure_driftguard.common.product_registry import ProductRegistry

    reg = ProductRegistry()
    m = reg.match("Azure SQL Database serverless GA")
    assert m is not None and m.name == "Azure SQL Database"
    assert "modules/azure_sql" in reg.module_paths_for("Azure SQL Database")


def test_skills_source_local_default():
    from azure_driftguard.common import skills_source

    assert skills_source.describe_source().startswith("local://")
    text = skills_source.read_text("skills/generate/SKILL.md")
    assert "GenerateAgent" in text
    names = skills_source.list_dir("skills/products")
    assert any(n.endswith(".yaml") for n in names)


def test_skills_source_github_mode(monkeypatch):
    import base64
    from azure_driftguard.common import config, skills_source

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
    assert skills_source.read_text("skills/generate/SKILL.md") == "# gh skill"
    assert skills_source.list_dir("skills/products") == ["x.yaml"]
    config.get_config.cache_clear()


def test_eval_harness_scores_fixtures():
    from pathlib import Path

    from eval.harness import run_eval

    fixtures = Path(__file__).resolve().parents[1] / "eval" / "fixtures"
    report = run_eval(fixtures, mode="deterministic")
    assert report.total == 4
    by_name = {r.name: r for r in report.results}
    assert by_name["feat-add-argument"].shipped is True
    assert by_name["fix-deprecated"].shipped is True
    assert by_name["review-only-cosmos"].shipped is False
    assert by_name["wrong-invented-arg"].shipped is False
    assert all(r.correct for r in report.results)
    assert report.verified_accuracy == 1.0
    assert report.false_drop_rate == 0.0


def test_list_feeds_tool_returns_trigger_time():
    from azure_driftguard.agents import tools_ingest

    result = tools_ingest.list_feeds()
    assert "feeds" in result and "triggered_at" in result
    assert result["count"] >= 1


def test_product_family_parsing():
    from azure_driftguard.common.product_registry import ProductRegistry

    p = ProductRegistry().get("Azure Blob Storage")
    assert p is not None
    assert "azurerm_storage_account" in p.family
    assert "azurerm_storage_blob" in p.related_resources
    assert p.provider == "azurerm"


def test_resolve_attribute_owner_picks_related(monkeypatch):
    from azure_driftguard.agents import tools_terraform
    from azure_driftguard.common import schema_index

    def fake_extract(provider, resource, version=""):
        if resource == "azurerm_storage_account":
            return {"ok": True, "arguments": {"name": {}}, "block_types": []}
        if resource == "azurerm_storage_blob":
            return {"ok": True, "arguments": {"name": {}, "cache_control": {}}, "block_types": []}
        return {"ok": True, "arguments": {"name": {}}, "block_types": []}

    monkeypatch.setattr(tools_terraform, "extract_resource_schema", fake_extract)
    schema_index.schema_cache.clear()
    res = schema_index.resolve_owner("azurerm", ["azurerm_storage_account", "azurerm_storage_blob"], "cache_control")
    assert res["resolved"] is True
    assert res["owner_resources"] == ["azurerm_storage_blob"]
    schema_index.schema_cache.clear()


def test_resolve_flags_when_schema_unavailable(monkeypatch):
    from azure_driftguard.agents import tools_terraform
    from azure_driftguard.common import schema_index

    monkeypatch.setattr(tools_terraform, "extract_resource_schema",
                        lambda p, r, version="": {"ok": False})
    schema_index.schema_cache.clear()
    res = schema_index.resolve_owner("azurerm", ["azurerm_storage_account"], "cache_control")
    assert res["resolved"] is False
    assert res["action"] == "flag_for_review"
    schema_index.schema_cache.clear()


_MIXED_HCL = '''
resource "azurerm_storage_account" "main" {
  name = "x"
}

resource "azurerm_key_vault_key" "key" {
  name = "k"
}

resource "azurerm_role_assignment" "role" {
  name = "r"
}

variable "region" { default = "us" }
'''


def test_scope_guard_identifies_in_and_out_of_family():
    from azure_driftguard.common import scope_guard

    res = scope_guard.check_scope("Azure Blob Storage", _MIXED_HCL, file_path="modules/storage/main.tf")
    in_types = {r["type"] for r in res["in_scope"]}
    out_types = {r["type"] for r in res["out_of_scope"]}
    assert "azurerm_storage_account" in in_types
    assert "azurerm_key_vault_key" in out_types
    assert "azurerm_role_assignment" in out_types
    assert res["path_in_scope"] is True
    assert res["ok"] is False


def test_scope_guard_strips_out_of_family_keeps_rest():
    from azure_driftguard.common import scope_guard

    out = scope_guard.strip_out_of_scope("Azure Blob Storage", _MIXED_HCL)
    content = out["content"]
    assert "azurerm_storage_account" in content
    assert 'variable "region"' in content
    assert "azurerm_key_vault_key" not in content
    assert "azurerm_role_assignment" not in content
    assert {r["type"] for r in out["stripped"]} == {"azurerm_key_vault_key", "azurerm_role_assignment"}


def test_scope_guard_path_confinement():
    from azure_driftguard.common import scope_guard

    res = scope_guard.check_scope("Azure Blob Storage",
                                  'resource "azurerm_storage_account" "m" {}',
                                  file_path="modules/iam/main.tf")
    assert res["path_in_scope"] is False
    assert res["ok"] is False
