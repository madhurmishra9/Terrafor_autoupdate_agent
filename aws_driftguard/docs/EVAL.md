# Accuracy eval harness

There is no universal "accuracy %" for generated Terraform — it depends on your
model, your modules, and the complexity of the changes. This harness lets you
measure it **for your own setup** by replaying release-note fixtures through the
verification layer and reporting three concrete numbers.

## The three metrics

- **first-pass accuracy** — how often the candidate patch is correct on the
  first attempt (before any retry). This is closest to the raw model quality.
- **verified accuracy** — of the patches that would actually reach a PR (after
  validate→plan and the judge gate, and after the product policy gate), how many
  are correct. This is the quality of what a reviewer sees.
- **false-drop rate** — valid changes the pipeline declined (held for review when
  they were actually correct). The cost of being conservative.

Together they capture the real trade-off: the verification layers raise
*verified* accuracy by dropping uncertain patches, which can raise the
*false-drop* rate. You want high verified accuracy and a low false-drop rate.

## Running it

```bash
# Offline: scores each fixture's bundled candidate.tf through the
# verification + policy layer. No cloud, no model cost.
PYTHONPATH=src python -m eval --fixtures-dir eval/fixtures --mode deterministic

# Write the full JSON report as well:
PYTHONPATH=src python -m eval --json eval-report.json
```

If the `terraform` binary is present, `validate`/`plan` run for real and the
`validate` column shows yes/no. Without it, validation is `n/a` and the harness
falls back to the fixture's static contract (`must_contain` / `must_not_contain`)
so it is still useful in CI without Terraform installed.

## What a fixture is

Each fixture is a directory under `eval/fixtures/<name>/`:

| File | Purpose |
|------|---------|
| `note.json` | the release note (`product`, `version`, `title`, …) |
| `expected.json` | ground truth (see below) |
| `candidate.tf` | the patch to score in deterministic mode |
| `current.tf` | optional pre-change file, for plan context |

`expected.json` fields:

```json
{
  "expectation": "patch",          // "patch" | "no_change" | "review"
  "candidate_correct": true,        // is the bundled candidate actually correct?
  "provider": "aws",
  "resource": "aws_db_instance",
  "required_version": "6.1.0",
  "current_constraint": ">= 6.0, < 7.0",
  "must_contain": ["storage_throughput"],
  "must_not_contain": ["invented_arg"]
}
```

The four shipped fixtures illustrate the cases the harness must get right:
a correct feature add, a correct deprecation fix, a **review-only** product
(`policy_allowed: false` in its manifest — must not auto-ship), and a patch with
an **invented argument** (must be caught, must not ship).

## Building a real number for your modules

1. Collect 30–50 historical release notes that affected your modules.
2. For each, create a fixture: drop in the note, the patch you'd accept as
   correct, and label `candidate_correct`.
3. Run the harness. The three metrics now reflect *your* modules and change mix.
4. Re-run whenever you change the model, provider versions, or add module types.

## Live mode

`--mode live` calls the real pipeline to generate the patch before scoring it.
It needs cloud credentials and a reachable module repo, and incurs model cost.
The generation hook in `eval/harness.py::_generate_live` is where you wire your
environment's generation call; deterministic mode needs no such wiring.
