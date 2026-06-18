# PRAgent

## Why this agent exists

The pipeline's terminal action is opening a pull request for the patched
Terraform and linking it back to Jira, closing the loop. This is isolated from
the TerraformAgent so that content generation and repository mutation remain
separate concerns, and from JiraAgent so ticket creation and PR creation can
fail and halt independently.

## What it does

- Reads the Jira ticket reference and classification from `jira_result`.
- Computes the PR title using the JiraAgent-owned prefix mapping (never
  re-derived here).
- Comments on an existing PR, or creates a branch, pushes patched files, and
  opens a new PR.
- Links the new PR URL back onto the Jira ticket.

## When it is invoked

- Position: Step 7 of 7, after JiraAgent. Terminal stage.
- Trigger: runs only if `pipeline_halted` is false.
- Skip: skipped when halted upstream (output stamped `[STOP]`).
- Upstream contract: requires `jira_result` and `terraform_result`.
- Downstream contract: writes `pr_result`.

## Where it lives in code

| Component | Path | Purpose |
|-----------|------|---------|
| Agent definition | `src/aws_driftguard/agents/definitions.py` | LlmAgent constructor for PRAgent |
| Skill | `skills/pr/SKILL.md` | Behaviour, title rules, linkback |
| Tools | `src/aws_driftguard/agents/tools_pr.py` | branch/push/PR/linkback tools |
| GitHub client | `src/aws_driftguard/common/github_client.py` | PAT + App auth, api/v3 |
| Artifact store | `src/aws_driftguard/agents/artifacts.py` | loads patched files |
| Connectivity guard | `src/aws_driftguard/agents/guards.py` | `github_connectivity_guard` |

## What code blocks make it up

Title computation always uses the shared mapping (`tools_pr.py`):
```python
def compute_pr_title(classification, ticket_number, short_description):
    mapping = resolve(classification)  # feat:/fix:/chore:
    return {"title": f"{mapping.pr_prefix} {ticket_number} {short_description}".strip()}
```

Linkback closes the loop (`tools_pr.py` → `link_pr_to_jira` → `add_jira_comment`).

## Inputs and outputs

- Reads from session.state: `jira_result`, `terraform_result`.
- Writes to session.state: `pr_result` (pr_url, pr_number, action,
  jira_ticket, jira_linked_back).
- External dependencies: GitHub (api/v3 or api.github.com) via PAT or GitHub
  App; Jira (for the linkback comment, reusing the recorded tier).

## Failure modes and halts

- GitHub unreachable → `github_connectivity_guard` halts with `github_unreachable`.
- `jira_result` missing or `[STOP]` → agent must not raise a PR.
- PR created but linkback failed → `jira_linked_back: false`, treated as failure.

## Tests

- `tests/test_taxonomy.py` — prefix mapping correctness (shared with JiraAgent).
- `tests/test_pr_title.py` — title format from classification.

## Cross-references

- Upstream: [JiraAgent](../jira/README.md)
- Downstream: none (terminal stage)
