"""Eval CLI: replay fixtures and print accuracy metrics.

Usage:
    PYTHONPATH=src python -m eval --fixtures-dir eval/fixtures --mode deterministic
    PYTHONPATH=src python -m eval --mode live --json report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the package importable when run as `python -m eval` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eval.harness import run_eval  # noqa: E402


def _fmt_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description="DriftGuard accuracy eval")
    ap.add_argument("--fixtures-dir", default="eval/fixtures",
                    help="directory of fixture subfolders")
    ap.add_argument("--mode", choices=["deterministic", "live"], default="deterministic",
                    help="deterministic (offline, scores bundled candidate.tf) or live")
    ap.add_argument("--json", default="", help="optional path to write the full JSON report")
    args = ap.parse_args()

    fixtures_dir = Path(args.fixtures_dir)
    if not fixtures_dir.exists():
        print(f"fixtures dir not found: {fixtures_dir}", file=sys.stderr)
        return 2

    report = run_eval(fixtures_dir, mode=args.mode)
    if report.total == 0:
        print(f"no fixtures found in {fixtures_dir}", file=sys.stderr)
        return 2

    # Per-fixture table.
    name_w = max(len(r.name) for r in report.results)
    print(f"\nDriftGuard eval — mode={args.mode}, fixtures={report.total}\n")
    print(f"  {'fixture'.ljust(name_w)}  expect      validate  judge   shipped  correct")
    print(f"  {'-' * name_w}  ----------  --------  ------  -------  -------")
    for r in report.results:
        print(f"  {r.name.ljust(name_w)}  "
              f"{r.expectation.ljust(10)}  "
              f"{_b(r.validate_passed).ljust(8)}  "
              f"{_b(r.judged_passed).ljust(6)}  "
              f"{_b(r.shipped).ljust(7)}  "
              f"{_b(r.correct)}")

    print("\n  Metrics")
    print(f"    first-pass accuracy : {_fmt_pct(report.first_pass_accuracy)}  "
          "(candidate correct on attempt 1)")
    print(f"    verified accuracy   : {_fmt_pct(report.verified_accuracy)}  "
          "(of patches that would reach a PR)")
    print(f"    false-drop rate     : {_fmt_pct(report.false_drop_rate)}  "
          "(valid changes declined to review)")
    print()

    if args.json:
        Path(args.json).write_text(json.dumps(report.to_dict(), indent=2))
        print(f"  wrote {args.json}\n")
    return 0


def _b(v: object) -> str:
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return "n/a"


if __name__ == "__main__":
    raise SystemExit(main())
