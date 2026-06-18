"""Unit tests that run without ADK / external services."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from azure_driftguard.common import adf  # noqa: E402
from azure_driftguard.common import taxonomy  # noqa: E402
from azure_driftguard.common import state  # noqa: E402


def test_adf_doc_structure():
    d = adf.plain_doc("hello")
    assert d["version"] == 1
    assert d["type"] == "doc"
    assert d["content"][0]["type"] == "paragraph"


def test_adf_release_description_has_blocks():
    d = adf.release_ticket_description(
        product="Azure SQL Database", version="6.0.0", release_date="2026-01-10",
        classification="feat", summary="New cache config", analysis="Adds arg",
        release_url="https://example.com/notes",
    )
    types = [b["type"] for b in d["content"]]
    assert "heading" in types
    assert "bulletList" in types
    assert "rule" in types


def test_adf_comment_with_pr_link():
    d = adf.comment_with_timestamp("re-run", "2026-01-10T00:00:00Z",
                                   pr_url="https://github.com/o/r/pull/1")
    flat = str(d)
    assert "github.com" in flat


def test_taxonomy_mapping():
    assert taxonomy.resolve("feat").jira_issue_type == "Story"
    assert taxonomy.resolve("fix").jira_issue_type == "Bug"
    assert taxonomy.resolve("chore").jira_issue_type == "Task"
    assert taxonomy.resolve("feat").pr_prefix == "feat:"


def test_taxonomy_classify_change():
    assert taxonomy.classify_change("new_argument") == "feat"
    assert taxonomy.classify_change("deprecation") == "fix"
    assert taxonomy.classify_change("readme") == "chore"


def test_state_halt_and_clear():
    s: dict = {}
    state.halt_pipeline(s, "test_reason")
    assert state.is_halted(s)
    assert s[state.PIPELINE_HALTED]["reason"] == "test_reason"
    state.clear_pipeline_state(s)
    assert not state.is_halted(s)


def test_stop_guard_stamps_output_key():
    st: dict = {}
    assert not state.is_halted(st)
    state.halt_pipeline(st, "x")
    assert state.is_halted(st)
    if state.is_halted(st):
        st["jira_result"] = state.STOP_SENTINEL
    assert st["jira_result"] == state.STOP_SENTINEL


def test_adf_flatten_in_jira_client():
    from azure_driftguard.common.jira_client import _adf_to_text
    d = adf.doc(adf.paragraph(adf.text("line one")), adf.paragraph(adf.text("line two")))
    flat = _adf_to_text(d)
    assert "line one" in flat and "line two" in flat


if __name__ == "__main__":
    import traceback
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failures else 0)
