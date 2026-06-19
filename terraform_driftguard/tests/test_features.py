"""Unit tests for the accuracy + optimisation features (no ADK / network)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from terraform_driftguard.common import cache  # noqa: E402


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
    from terraform_driftguard.agents import tools_terraform as tt

    res = tt.check_version_pin(">= 5.0", "5.10.0")
    assert res["ok"] is True
    assert res["allowed"] is True
    assert res["action"] == "none"


def test_version_pin_gate_blocks_unsatisfied():
    from terraform_driftguard.agents import tools_terraform as tt

    res = tt.check_version_pin(">= 5.0, < 6.0", "6.1.0")
    assert res["ok"] is True
    assert res["allowed"] is False
    assert res["action"] == "bump_required_providers"


def test_verify_patch_skips_without_terraform(monkeypatch):
    from terraform_driftguard.agents import tools_terraform as tt

    # Force terraform-unavailable path.
    monkeypatch.setattr(tt.shutil, "which", lambda _name: None)
    res = tt.verify_patch("resource \"x\" \"y\" {}", attempt=1)
    assert res["verified"] is None
    assert res["stage"] == "skipped"


def test_judge_disabled_passes(monkeypatch):
    from terraform_driftguard.agents import tools_judge
    from terraform_driftguard.common import config

    config.get_config.cache_clear()
    monkeypatch.setenv("JUDGE_ENABLED", "false")
    res = tools_judge.judge_patch(requirement="add arg", patch="x = 1")
    assert res["passed"] is True
    assert res["skipped"] is True
    config.get_config.cache_clear()


def test_relevance_fail_open_without_sdk(monkeypatch):
    from terraform_driftguard.agents import tools_relevance
    from terraform_driftguard.common import config

    config.get_config.cache_clear()
    monkeypatch.setenv("RELEVANCE_FILTER_ENABLED", "true")
    # No genai SDK in the unit env -> _embed returns None -> fail open.
    res = tools_relevance.score_release_relevance("Cloud SQL new feature", "details")
    assert res["relevant"] is True
    assert res["method"] in {"fail_open", "embedding", "disabled"}
    config.get_config.cache_clear()


def test_tiered_models_configured(monkeypatch):
    from terraform_driftguard.common import config

    config.get_config.cache_clear()
    monkeypatch.setenv("VERTEX_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("VERTEX_MODEL_FAST", "gemini-2.5-flash")
    cfg = config.get_config()
    assert cfg.gcp.model == "gemini-2.5-pro"
    assert cfg.gcp.model_fast == "gemini-2.5-flash"
    config.get_config.cache_clear()


def test_product_registry_loads_and_gates():
    from terraform_driftguard.common.product_registry import ProductRegistry

    reg = ProductRegistry()
    names = reg.names()
    assert "Cloud SQL" in names
    # policy gating: Cloud SQL auto-allowed, Spanner known but review-only
    assert reg.is_allowed("Cloud SQL") is True
    assert reg.is_known("Cloud Spanner") is True
    assert reg.is_allowed("Cloud Spanner") is False
    # unknown product
    assert reg.is_known("Nonexistent Service") is False
    assert reg.is_allowed("Nonexistent Service") is False


def test_product_registry_match_and_paths():
    from terraform_driftguard.common.product_registry import ProductRegistry

    reg = ProductRegistry()
    m = reg.match("Cloud SQL now supports data cache")
    assert m is not None and m.name == "Cloud SQL"
    assert "modules/cloudsql" in reg.module_paths_for("Cloud SQL")
    topics = reg.relevance_topics()
    assert any("Cloud SQL" in t for t in topics)


def test_skills_source_local_default():
    from terraform_driftguard.common import skills_source

    # Default is local; describe_source reflects it.
    assert skills_source.describe_source().startswith("local://")
    text = skills_source.read_text("skills/terraform/SKILL.md")
    assert "TerraformAgent" in text
    names = skills_source.list_dir("skills/products")
    assert any(n.endswith(".yaml") for n in names)


def test_skills_source_github_mode(monkeypatch):
    import base64
    from terraform_driftguard.common import config, skills_source

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


def test_eval_harness_scores_fixtures():
    from pathlib import Path

    from eval.harness import run_eval

    fixtures = Path(__file__).resolve().parents[1] / "eval" / "fixtures"
    report = run_eval(fixtures, mode="deterministic")
    assert report.total == 4
    # All four fixtures should be scored correctly by the verification + policy layer.
    by_name = {r.name: r for r in report.results}
    assert by_name["feat-add-argument"].shipped is True
    assert by_name["fix-deprecated"].shipped is True
    assert by_name["review-only-spanner"].shipped is False   # policy_allowed:false
    assert by_name["wrong-invented-arg"].shipped is False    # caught by contract
    assert all(r.correct for r in report.results)
    # Verified accuracy = of shipped, how many correct = 100% here.
    assert report.verified_accuracy == 1.0
    assert report.false_drop_rate == 0.0


def test_list_feeds_includes_shared_and_product_feeds(monkeypatch):
    from terraform_driftguard.common.product_registry import ProductRegistry

    reg = ProductRegistry()
    # Shared feed always present.
    feeds = reg.feeds(shared_feed_url="https://example.com/shared.xml")
    urls = [f["url"] for f in feeds]
    assert "https://example.com/shared.xml" in urls
    # Shared feed entry has empty product; product feeds carry their name.
    shared = [f for f in feeds if f["product"] == ""]
    assert len(shared) == 1


def test_list_feeds_tool_returns_trigger_time():
    from terraform_driftguard.agents import tools_ingest

    result = tools_ingest.list_feeds()
    assert "feeds" in result and "triggered_at" in result
    assert result["count"] >= 1


def test_product_family_parsing():
    from terraform_driftguard.common.product_registry import ProductRegistry

    reg = ProductRegistry()
    p = reg.get("Cloud Storage")
    assert p is not None
    # Family = primary + related, with the object resource present.
    assert "google_storage_bucket" in p.family
    assert "google_storage_bucket_object" in p.related_resources
    assert "google_storage_bucket_object" in p.family
    assert p.provider == "google"


def test_resolve_attribute_owner_picks_related_not_primary(monkeypatch):
    from terraform_driftguard.agents import tools_terraform
    from terraform_driftguard.common import schema_index

    def fake_extract(provider, resource, version=""):
        if resource == "google_storage_bucket":
            return {"ok": True, "arguments": {"name": {}, "location": {}}, "block_types": []}
        if resource == "google_storage_bucket_object":
            return {"ok": True, "arguments": {"name": {}, "custom_context": {}}, "block_types": []}
        return {"ok": True, "arguments": {"name": {}}, "block_types": []}

    monkeypatch.setattr(tools_terraform, "extract_resource_schema", fake_extract)
    schema_index.schema_cache.clear()

    family = ["google_storage_bucket", "google_storage_bucket_object"]
    res = schema_index.resolve_owner("google", family, "custom_context")
    assert res["resolved"] is True
    assert res["owner_resources"] == ["google_storage_bucket_object"]
    schema_index.schema_cache.clear()


def test_resolve_attribute_owner_flags_when_schema_unavailable(monkeypatch):
    from terraform_driftguard.agents import tools_terraform
    from terraform_driftguard.common import schema_index

    # Schema not grounded -> must NOT guess; flag for review.
    monkeypatch.setattr(tools_terraform, "extract_resource_schema",
                        lambda p, r, version="": {"ok": False})
    schema_index.schema_cache.clear()
    res = schema_index.resolve_owner("google", ["google_storage_bucket"], "custom_context")
    assert res["resolved"] is False
    assert res["action"] == "flag_for_review"
    schema_index.schema_cache.clear()


def test_resolve_attribute_owner_not_found(monkeypatch):
    from terraform_driftguard.agents import tools_terraform
    from terraform_driftguard.common import schema_index

    monkeypatch.setattr(tools_terraform, "extract_resource_schema",
                        lambda p, r, version="": {"ok": True, "arguments": {"name": {}}, "block_types": []})
    schema_index.schema_cache.clear()
    res = schema_index.resolve_owner("google", ["google_storage_bucket"], "nonexistent_attr")
    assert res["resolved"] is False
    assert res["reason"] == "attribute_not_found"
    assert res["action"] == "flag_for_review"
    schema_index.schema_cache.clear()


_SPANNER_MIXED_HCL = '''
resource "google_spanner_instance" "main" {
  name      = "main-instance"
  num_nodes = 1
}

resource "google_kms_crypto_key" "key" {
  name     = "spanner-cmek"
  key_ring = "ring"
}

resource "google_project_iam_member" "admin" {
  project = "p"
  role    = "roles/spanner.admin"
  member  = "user:a@b.com"
}

variable "region" { default = "us-central1" }
'''


def test_scope_guard_identifies_in_and_out_of_family():
    from terraform_driftguard.common import scope_guard

    res = scope_guard.check_scope("Cloud Spanner", _SPANNER_MIXED_HCL,
                                  file_path="modules/spanner/main.tf")
    in_types = {r["type"] for r in res["in_scope"]}
    out_types = {r["type"] for r in res["out_of_scope"]}
    assert "google_spanner_instance" in in_types
    assert "google_kms_crypto_key" in out_types
    assert "google_project_iam_member" in out_types
    assert res["path_in_scope"] is True
    assert res["ok"] is False  # has out-of-scope resources


def test_scope_guard_strips_out_of_family_keeps_rest():
    from terraform_driftguard.common import scope_guard

    out = scope_guard.strip_out_of_scope("Cloud Spanner", _SPANNER_MIXED_HCL)
    content = out["content"]
    # Spanner resource and the variable survive; KMS + IAM are removed.
    assert "google_spanner_instance" in content
    assert 'variable "region"' in content
    assert "google_kms_crypto_key" not in content
    assert "google_project_iam_member" not in content
    stripped = {r["type"] for r in out["stripped"]}
    assert stripped == {"google_kms_crypto_key", "google_project_iam_member"}


def test_scope_guard_path_confinement():
    from terraform_driftguard.common import scope_guard

    # A file outside the product's module_paths is flagged.
    res = scope_guard.check_scope("Cloud Spanner",
                                  'resource "google_spanner_instance" "m" {}',
                                  file_path="modules/iam/main.tf")
    assert res["path_in_scope"] is False
    assert res["ok"] is False


def test_scope_guard_spanner_own_iam_is_in_family():
    from terraform_driftguard.common import scope_guard

    hcl = 'resource "google_spanner_database_iam_member" "x" {}'
    res = scope_guard.check_scope("Cloud Spanner", hcl)
    # Spanner's OWN iam resource is in-family (it is Spanner config); only
    # generic non-Spanner resources are out of scope.
    assert {r["type"] for r in res["in_scope"]} == {"google_spanner_database_iam_member"}
    assert res["out_of_scope"] == []
