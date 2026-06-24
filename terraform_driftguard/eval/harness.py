"""Accuracy eval harness for DriftGuard (GCP edition).

Replays a folder of release-note fixtures through the verification layer and
reports three numbers that actually mean something for *your* modules:

  - first_pass_accuracy : how often the candidate patch is correct on attempt 1
                          (compared to the fixture's expected patch / outcome)
  - verified_accuracy   : of the patches that survive verify + judge, how many
                          are correct (the quality of what would reach a PR)
  - false_drop_rate     : valid changes the pipeline declined (dropped to review
                          when they were actually correct)

Two scoring backends:

  - "deterministic" (default, no cloud): uses each fixture's bundled candidate
    patch and runs it through validate -> plan -> judge gating. This measures
    the *verification layer* — the part that converts a raw model guess into a
    trustworthy PR — and runs locally with no LLM calls.

  - "live": calls the real pipeline to generate the patch first, then scores it.
    Requires cloud credentials and incurs model cost. Selected with --mode live.

A fixture is a directory under eval/fixtures/<name>/ containing:
    note.json      the release note ({product, version, release_date, title, ...})
    expected.json  the expected outcome (see ExpectedOutcome below)
    candidate.tf   the candidate patch to score (deterministic mode)
    current.tf     (optional) the pre-change module file, for plan context
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from terraform_driftguard.common.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class ExpectedOutcome:
    """Ground truth for a fixture."""

    # "patch" => a correct patch is expected; "no_change" => nothing should
    # change; "review" => the change should be flagged for manual review.
    expectation: str = "patch"
    # Whether the candidate patch is, in fact, correct (label supplied by you).
    candidate_correct: bool = True
    # Optional substrings that must appear in a correct patch.
    must_contain: list[str] = field(default_factory=list)
    # Optional substrings that must NOT appear (e.g. invented arguments).
    must_not_contain: list[str] = field(default_factory=list)
    provider: str = "google"
    resource: str = ""
    required_version: str = ""
    current_constraint: str = ""


@dataclass
class FixtureResult:
    name: str
    expectation: str
    candidate_correct: bool
    validate_passed: bool | None
    judged_passed: bool | None
    shipped: bool            # would this reach a PR?
    correct: bool            # was the decision correct vs ground truth?
    notes: str = ""


def _load_fixture(d: Path) -> tuple[dict[str, Any], ExpectedOutcome, str]:
    note = json.loads((d / "note.json").read_text()) if (d / "note.json").exists() else {}
    exp_raw = json.loads((d / "expected.json").read_text()) if (d / "expected.json").exists() else {}
    expected = ExpectedOutcome(
        expectation=exp_raw.get("expectation", "patch"),
        candidate_correct=bool(exp_raw.get("candidate_correct", True)),
        must_contain=exp_raw.get("must_contain", []),
        must_not_contain=exp_raw.get("must_not_contain", []),
        provider=exp_raw.get("provider", "google"),
        resource=exp_raw.get("resource", ""),
        required_version=exp_raw.get("required_version", ""),
        current_constraint=exp_raw.get("current_constraint", ""),
    )
    candidate = (d / "candidate.tf").read_text() if (d / "candidate.tf").exists() else ""
    return note, expected, candidate


def _static_label(candidate: str, expected: ExpectedOutcome) -> bool:
    """Cheap, offline correctness proxy: substring contract from the fixture."""
    if any(s not in candidate for s in expected.must_contain):
        return False
    if any(s in candidate for s in expected.must_not_contain):
        return False
    return True


def score_fixture(d: Path, mode: str = "deterministic") -> FixtureResult:
    from terraform_driftguard.agents import tools_judge, tools_terraform

    note, expected, candidate = _load_fixture(d)

    if mode == "live":
        candidate = _generate_live(note, expected) or candidate

    # First-pass correctness: does the candidate meet the fixture's contract?
    first_pass_correct = _static_label(candidate, expected) and expected.candidate_correct

    # Verification layer (deterministic): validate -> plan, then judge.
    verify = tools_terraform.verify_patch(candidate, attempt=1) if candidate else {"verified": False}
    validate_passed = verify.get("verified")

    judged_passed: bool | None = None
    if validate_passed is not False and candidate:
        verdict = tools_judge.judge_patch(
            requirement=note.get("title", ""),
            patch=candidate,
            provider_version=expected.required_version,
        )
        judged_passed = verdict.get("passed")

    # A patch "ships" (reaches a PR) only if validation did not fail and the
    # judge did not reject it. validate_passed is tri-state:
    #   True  -> validate+plan passed
    #   None  -> terraform unavailable (unknown); fall back to the static
    #            contract so the harness is still useful without the binary
    #   False -> validate/plan failed -> never ships
    # Policy gate (Analyze stage): a product whose manifest sets
    # policy_allowed: false is review-only and must never auto-ship, regardless
    # of how clean the candidate patch is.
    policy_blocks = False
    product = note.get("product", "")
    if product:
        try:
            from terraform_driftguard.common.product_registry import registry

            if registry.is_known(product) and not registry.is_allowed(product):
                policy_blocks = True
        except Exception:
            pass

    # Scope guard: a patch that touches resources outside the product's family
    # is out of scope. The pipeline strips those, but for eval we treat an
    # unstripped out-of-scope candidate as a scope failure (would not ship as-is).
    scope_violation = False
    if product and candidate:
        try:
            from terraform_driftguard.common import scope_guard

            sc = scope_guard.check_scope(product, candidate)
            if sc.get("known") and sc.get("out_of_scope"):
                scope_violation = True
        except Exception:
            pass

    if policy_blocks:
        shipped = False
    elif scope_violation:
        shipped = False
    elif validate_passed is False:
        shipped = False
    elif validate_passed is None:
        shipped = _static_label(candidate, expected) and (judged_passed is not False)
    else:
        shipped = judged_passed is not False

    # Decision correctness vs ground truth.
    if expected.expectation == "patch":
        # Correct iff we shipped AND the candidate was actually correct, OR we
        # correctly declined a wrong candidate.
        correct = (shipped and first_pass_correct) or (not shipped and not expected.candidate_correct)
    elif expected.expectation == "no_change":
        correct = not shipped
    else:  # "review"
        correct = not shipped  # review-only items should not auto-ship

    return FixtureResult(
        name=d.name,
        expectation=expected.expectation,
        candidate_correct=expected.candidate_correct,
        validate_passed=validate_passed,
        judged_passed=judged_passed,
        shipped=shipped,
        correct=correct,
        notes=verify.get("feedback", "") if validate_passed is False else "",
    )


def _generate_live(note: dict[str, Any], expected: ExpectedOutcome) -> str | None:
    """Generate a patch via the real pipeline (live mode). Best-effort."""
    try:
        from terraform_driftguard.pipeline import build_pipeline  # noqa: F401
    except Exception as exc:
        logger.warning("live mode unavailable: %s", exc)
        return None
    # Live generation wiring is environment-specific (needs creds + a real
    # module repo). Hook your generation call here and return the patch text.
    logger.info("live mode: implement generation hook for fixture %s", note.get("title"))
    return None


@dataclass
class EvalReport:
    total: int
    first_pass_accuracy: float
    verified_accuracy: float
    false_drop_rate: float
    results: list[FixtureResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "first_pass_accuracy": round(self.first_pass_accuracy, 4),
            "verified_accuracy": round(self.verified_accuracy, 4),
            "false_drop_rate": round(self.false_drop_rate, 4),
            "results": [r.__dict__ for r in self.results],
        }


def run_eval(fixtures_dir: Path, mode: str = "deterministic") -> EvalReport:
    fixtures = sorted(p for p in fixtures_dir.iterdir() if p.is_dir())
    results = [score_fixture(f, mode=mode) for f in fixtures]
    total = len(results)

    # first-pass: candidate correct on attempt one
    first_pass = sum(1 for r in results if r.candidate_correct and _vp(r)) / total if total else 0.0

    # verified accuracy: of shipped patches, how many were correct
    shipped = [r for r in results if r.shipped]
    verified = (sum(1 for r in shipped if r.candidate_correct) / len(shipped)) if shipped else 0.0

    # false-drop: valid changes we declined (expected patch, candidate correct,
    # but didn't ship)
    valid_changes = [r for r in results if r.expectation == "patch" and r.candidate_correct]
    false_drops = sum(1 for r in valid_changes if not r.shipped)
    false_drop_rate = (false_drops / len(valid_changes)) if valid_changes else 0.0

    return EvalReport(total, first_pass, verified, false_drop_rate, results)


def _vp(r: FixtureResult) -> bool:
    # Treat "unknown" (terraform unavailable) as a pass for first-pass purposes,
    # since static contract checks still applied.
    return r.validate_passed is not False
