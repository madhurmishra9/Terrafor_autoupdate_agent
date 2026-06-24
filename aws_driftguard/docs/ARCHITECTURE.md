# Architecture

## Overview

AWS DriftGuard is a native Bedrock pipeline. Seven stages run in fixed order,
orchestrated either by the runnable Converse tool-use loop or by managed Bedrock
Agents (multi-agent collaboration). Compute is ECS Fargate / EKS.
Each loads its instruction from a versioned `SKILL.md`.

```
AwsDriftGuardPipelineAgent (SequentialAgent)
├── before_agent_callback: cb_before_pipeline   (clears 9 state keys)
├── after_agent_callback:  cb_after_pipeline    (eval artifact if CAPTURE_ENABLED)
└── sub_agents:
      1 IngestAgent  → release_notes
      2 ClassifyAgent    → classification_result
      3 AnalyzeAgent    → change_analyser_result
      4 DecideAgent     → decision_maker_result
      5 GenerateAgent         → terraform_result
      6 TicketAgent              → jira_result
      7 PublishAgent                → pr_result
```

## Session-state contract

| Key | Written by | Cleared by |
|-----|-----------|-----------|
| `release_notes` | IngestAgent | cb_before_pipeline |
| `classification_result` | ClassifyAgent | cb_before_pipeline |
| `change_analyser_result` | AnalyzeAgent | cb_before_pipeline |
| `decision_maker_result` | DecideAgent | cb_before_pipeline |
| `terraform_result` | GenerateAgent | cb_before_pipeline |
| `jira_result` | TicketAgent | cb_before_pipeline |
| `pr_result` | PublishAgent | cb_before_pipeline |
| `pipeline_mode` | IngestAgent (fetch-only) | cb_before_pipeline |
| `pipeline_halted` | any agent via `halt_pipeline()` | cb_before_pipeline |

Key names are defined once in `common/state.py`. Agents import them; they never
hardcode strings.

## Stop-guard

Every downstream agent has `make_stop_guard(output_key)` as (part of) its
`before_agent_callback`. When `pipeline_halted` is set, the guard stamps the
agent's output_key with `[STOP]`, returns model content to skip the LLM call,
and the agent does nothing. Decide, Ticket, and Publish additionally chain a
connectivity guard:

- Decide, Publish → `github_connectivity_guard`
- Jira → `jira_connectivity_guard`

A connectivity guard probes its dependency and calls `halt_pipeline()` on
failure, so no agent runs without the resource it needs.

## Jira connectivity (3-tier)

`common/jira_client.py` implements a strict fallback per operation:

1. `jira` Python library (in-process, structured)
2. `acli` subprocess (Atlassian CLI)
3. REST API v3 (`requests`)

`JiraUnreachable` is raised only if all three fail. The succeeding tier is
returned on every result and recorded in `jira_result.connectivity_tier`, so
PublishAgent's linkback comment reuses the same mechanism. All rich text is ADF
(`common/adf.py`) because the target is Jira Cloud `api/v3`.

## GitHub auth (PAT or App)

`common/github_client.py` supports:

- **PAT** — static token in the Authorization header.
- **App** — RS256 JWT signed with the app private key, exchanged for an
  installation access token, refreshed before expiry.

`GITHUB_API_BASE` selects github.com (`https://api.github.com`) or Enterprise
(`https://<host>/api/v3`).

## Skills delivery and hot reload

Each agent's instruction is provided by `skill_instruction_provider(path)`,
which reads the `SKILL.md` **per invocation**. Combined with ConfigMap-mounted
skills, an edited `SKILL.md` takes effect on the next run (~90s propagation)
without a pod restart. For immutable production, bake `skills/` into the image
and accept a redeploy per change. `SKILL.md` may compose sub-files via
`@include: relative/path`.

## Deployment topology

```
Pod
├── aws-driftguard (task)       Bedrock client, orchestrator, skills
├── RDS Postgres (managed)      release-note + classification store
└── mcp-server (sidecar)           localhost:8080 → GitHub tools
```

IRSA (EKS) or the task role (ECS) grants `bedrock:InvokeModel`, RDS connect, and
`roles/aiplatform.user`. Jira and GitHub credentials come from K8s Secrets /
Secret Manager. The GitHub App private key is mounted as a file.

## Failure handling summary

| Condition | Detected by | Result |
|-----------|------------|--------|
| Feed fetch fails | Ingest `[STOP]` | halt |
| RDS down | Classification tool error | halt |
| All Jira tiers down | jira_connectivity_guard | halt (`jira_unreachable`) |
| GitHub down | github_connectivity_guard | halt (`github_unreachable`) |
| No actionable changes | Analyze `changes_required:false` | clean no-op downstream |
| fetch-only mode | Classification after marker | halt after classification |
