# TicketAgent

## Why this agent exists

A Azure DriftGuard change must be tracked in Jira before a PR is raised, so
that the PR carries a real ticket reference and the workflow is auditable. This
agent guarantees a ticket exists (created or commented) and owns the
classification → issue-type → PR-prefix mapping that PublishAgent consumes. It is a
distinct stage because Jira connectivity (3-tier) and ADF formatting are
concerns that must not leak into the Terraform or PR agents.

## What it does

- Determines release identity (product, version, release_date) and change
  classification from upstream state.
- Searches for an existing ticket for the release.
- Comments on the existing ticket, or creates a new one with an ADF description.
- Maps classification to Jira issue type (feat→Story, fix→Bug, chore→Task).
- Records which connectivity tier succeeded for downstream reuse.

## When it is invoked

- Position: Step 6 of 7, after GenerateAgent, before PublishAgent.
- Trigger: runs only if `pipeline_halted` is false.
- Skip: skipped (output stamped `[STOP]`) when the pipeline is halted upstream.
- Upstream contract: requires `release_notes` and `analyze_result`.
- Downstream contract: writes `ticket_result`.

## Where it lives in code

| Component | Path | Purpose |
|-----------|------|---------|
| Agent definition | `src/azure_driftguard/agents/definitions.py` | LlmAgent constructor for TicketAgent |
| Skill (instructions) | `skills/ticket/SKILL.md` | Behaviour, 3-tier order, ADF rules |
| Tools | `src/azure_driftguard/agents/tools_jira.py` | search/create/comment tools |
| Jira client | `src/azure_driftguard/common/jira_client.py` | 3-tier fallback implementation |
| ADF builders | `src/azure_driftguard/common/adf.py` | ADF document construction |
| Connectivity guard | `src/azure_driftguard/agents/guards.py` | `jira_connectivity_guard` |
| Taxonomy | `src/azure_driftguard/common/taxonomy.py` | classification → issue type map |

## What code blocks make it up

Agent wiring (`definitions.py`):
```python
jira = _llm_agent(
    name="TicketAgent",
    output_key=TICKET_RESULT,
    instruction=skill_instruction_provider("skills/ticket/SKILL.md"),
    before_agent_callback=chain_guards(
        make_stop_guard(TICKET_RESULT), jira_connectivity_guard),
    tools=[search_existing_jira, create_jira_ticket, add_jira_comment,
           get_current_timestamp],
)
```

Tier order (`jira_client.py`): each operation tries `_library()`, then
`_acli()`, then `_api()`, raising `JiraUnreachable` only if all fail.

## Inputs and outputs

- Reads from session.state: `release_notes`, `analyze_result`.
- Writes to session.state: `ticket_result` (ticket_number, ticket_url, action,
  classification, short_description, connectivity_tier).
- External dependencies: Jira Cloud via three mechanisms — `jira` Python
  library (tier 1), `acli` (tier 2), REST API v3 (tier 3). All rich text is ADF.

## Failure modes and halts

- All three Jira tiers fail → `jira_connectivity_guard` calls `_halt_pipeline`
  with reason `jira_unreachable`.
- A tool returning `{"error": "jira_unreachable"}` mid-run signals the same halt.

## Tests

- `tests/test_adf.py` — ADF builders produce valid document structure.
- `tests/test_jira_client.py` — tier fallback order and flattening.

## Cross-references

- Upstream: [GenerateAgent](../terraform/README.md)
- Downstream: [PublishAgent](../pr/README.md)
