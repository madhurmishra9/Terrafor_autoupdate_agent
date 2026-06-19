# AWS DriftGuard Agent

A **native AWS** agent pipeline (Amazon Bedrock) that keeps Terraform modules
current with AWS releases (What's New). It fetches GA release notes, classifies and stores them,
analyses Terraform-provider impact, fetches affected module files, generates
correct HCL patches, raises (or comments on) a Jira ticket, and opens a PR
linked back to that ticket.

This is the **skills-driven** build: every agent's behaviour lives in a
versioned `SKILL.md`, loaded per-invocation, not hardcoded into Python.

## Sibling editions (same architecture, different cloud)

DriftGuard ships as three cross-linked repositories that share an identical
7-agent pipeline, guard model, Jira/GitHub clients, and accuracy/optimisation
features. Each edition runs **natively on its own cloud** — the LLM, datastore,
secrets, compute, and orchestration framework differ per cloud, as does the
release-notes source, Terraform provider, and product allow-list.

| Cloud | Repo | Runtime | Release source | Provider |
|-------|------|---------|----------------|----------|
| GCP | [`terraform_driftguard`](../terraform_driftguard/README.md) | Vertex AI + CloudSQL + GKE (ADK) | GCP release notes (Atom) | `hashicorp/google` |
| **AWS** (this repo) | `aws_driftguard` | Bedrock + RDS + ECS/EKS | AWS What's New (RSS) | `hashicorp/aws` |
| Azure | [`azure_driftguard`](../azure_driftguard/README.md) | Azure OpenAI + Azure SQL + AKS | Azure Updates (RSS) | `hashicorp/azurerm` |

> Sibling links assume the three repos are checked out side by side. On GitHub, replace the relative paths with the org/repo URLs.


## Pipeline

```
RequestProcessor → Classification → ChangeAnalyser → DecisionMaker
   → Terraform → Jira → PR
```

See `docs/ARCHITECTURE.md` for the full contract and `docs/architecture.svg`
for the diagram.

## Key features

- **Skills-driven agents** — behaviour in `skills/<agent>/SKILL.md`, hot-reloadable.
- **Jira 3-tier connectivity** — `jira` library → `acli` → REST API v3, in strict
  priority order, with the working tier recorded for downstream reuse.
- **ADF everywhere** — all Jira rich text is Atlassian Document Format for
  Jira Cloud `api/v3`.
- **GitHub PAT or App auth** — works against `api.github.com` or Enterprise
  `api/v3`; App mode mints short-lived installation tokens.
- **Centralised stop-guard** — a single `pipeline_halted` flag short-circuits all
  downstream agents.
- **AWS-native runtime** — Amazon Bedrock for inference, RDS Postgres for
  storage, Secrets Manager for credentials, ECS Fargate / EKS for compute.
- **Native Bedrock orchestration** — runnable Converse tool-use orchestrator,
  plus managed Bedrock Agents (multi-agent collaboration) via CloudFormation.
- **Accuracy features** — provider schema grounding, self-correcting
  validate→plan loop, version-pinning gate, and a judge/critic pass before any
  PR. See `docs/FEATURES.md`.
- **Declarative product onboarding** — products are manifest files in
  `skills/products/*.yaml` (feeds, aliases, resource family, policy); add one to
  onboard, no code change, no redeploy with `SKILLS_SOURCE=github`.
- **Resource families + second-level resolution** — a product is a family of
  resources; a changed attribute is resolved to the resource that *actually*
  owns it via the real provider schema (no hallucinating it onto the wrong
  resource). See `docs/RESOURCE_FAMILIES.md`.
- **Scope guard** — every update is confined to the product's own resources and
  module paths; unrelated IAM/KMS/etc. in the same file are left untouched. See
  `docs/SCOPE_GUARD.md`.
- **Accuracy eval harness** — measure first-pass / verified / false-drop accuracy
  on your own modules (`docs/EVAL.md`).
- **Optimisation features** — tiered model routing (fast model for parsing,
  pro for reasoning), embedding-based relevance filtering, and a TTL cache for
  schema/registry lookups.

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill in values
python tests/test_core.py  # run unit tests (no external services needed)
python -m aws_driftguard.run
```

## Deploy (ECS / EKS)

```bash
make build push
make deploy        # applies config, skills ConfigMap, Deployment, CronJob
make logs
```

After editing any `SKILL.md`, hot-update without a rebuild:

```bash
make skills-configmap     # remounts updated skills (~90s propagation)
```

## Configuration

All configuration is environment-driven. See `.env.example` for the full list,
including Bedrock (`BEDROCK_*`), RDS (`RDS_*`), Jira, and GitHub. Secrets resolve from Secrets Manager.

## Onboarding products (no code changes)

The products DriftGuard tracks are defined declaratively in
`skills/products/*.yaml`. Each manifest describes one product: how to match its
release notes, which Terraform resources and module paths it owns, whether org
policy auto-allows it, and extra relevance phrases. The ingest, change-analysis,
and relevance stages all read these manifests through
`common/product_registry.py`, so one file keeps every stage consistent.

To onboard a product, drop in a manifest — no Python changes:

```yaml
# skills/products/myproduct.yaml
name: Amazon S3
aliases: [Amazon S3, S3]              # keywords to match in release notes
provider: aws
provider_version: ">= 6.0"               # version to ground Terraform syntax against
resources:                               # PRIMARY resource(s)
  - aws_s3_bucket
related_resources:                       # SECOND-LEVEL resources where features hide
  - aws_s3_object        # e.g. object_lock_enabled lives here, not the primary
  - aws_s3_bucket_lifecycle_configuration
module_paths: [modules/s3]              # edits are confined to these paths
policy_allowed: true                     # false => track + flag for review, don't auto-patch
feeds:                                   # the product owner's own feed(s), optional
  - url: https://aws.amazon.com/about-aws/whats-new/storage/feed/
    format: rss
relevance_topics: [S3 object lock]
```

Only `name` is required. `related_resources` declares the product's full
resource family so a feature on a secondary resource (e.g. `object_lock_enabled` on
`aws_s3_object`) is found and patched on the right resource — see
`docs/RESOURCE_FAMILIES.md`. `provider_version` grounds syntax against the exact
version. `module_paths` bound the blast radius — an update touches only the
product's own resources, never IAM/KMS/etc. in the same file (`docs/SCOPE_GUARD.md`).
`feeds` lets the owner add their own release feed (`docs/SCHEDULING.md`).

With `SKILLS_SOURCE=github` (see `docs/SKILLS_SOURCE.md`) the manifest is read
from the repo at runtime — commit it and it is live on the next run, no redeploy.
The referenced Terraform module must already exist in your module repo —
DriftGuard updates existing modules, it doesn't scaffold new ones. See
`skills/products/README.md` for the full schema. Example: `skills/products/rds.yaml`.

## Project layout

```
src/aws_driftguard/
  common/        config, logging, state, ADF, Bedrock/RDS/Secrets, Jira/GitHub clients
  agents/        tools, guards, callbacks, the 7 agent definitions
  skills_loader/ per-invocation SKILL.md loader (hot reload)
  orchestration/ stages, tool registry, Bedrock orchestrator, agents runtime
  run.py         entrypoint
skills/<agent>/  SKILL.md + README.md (+ examples/ for terraform)
deploy/k8s/      Deployment, sidecars, config, secrets, CronJob
docs/            ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, architecture.svg
tests/           unit tests (run without boto3 / cloud)
```

## Documentation

- `docs/ARCHITECTURE.md` — pipeline contract, state keys, guards, per-agent detail.
- `docs/ORCHESTRATION.md` — native orchestration modes (runnable + managed).
- `docs/FEATURES.md` — accuracy + optimisation features and how to toggle them.
- `docs/SKILLS_SOURCE.md` — serve skills from the repo at runtime (no redeploy).
- `docs/EVAL.md` — accuracy eval harness: measure first-pass / verified / false-drop.
- `docs/SCHEDULING.md` — which feeds are fetched and when the pipeline runs.
- `docs/RESOURCE_FAMILIES.md` — resource families & schema-grounded second-level resolution.
- `docs/SCOPE_GUARD.md` — confine each update to the product (strip out-of-family edits).
- `docs/IMPLEMENTATION_PLAN.md` — phased rollout, milestones, runbook.
- `skills/<agent>/README.md` — per-agent why/what/when/where.
