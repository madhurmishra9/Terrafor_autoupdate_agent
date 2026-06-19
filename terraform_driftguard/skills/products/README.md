# Product Skills — onboarding products without code changes

Each file in this directory is a **product manifest**: a declarative description
of one cloud product that DriftGuard should track and keep Terraform modules
current for. Onboarding a new product is a single file — no Python changes, no
redeploy of code (only a skills refresh / image rebuild that ships the file).

The ingest, change-analysis, and relevance stages all read these manifests
through `common/product_registry.py`, so one file keeps every stage consistent.

## How to add a product

1. Copy an existing manifest, e.g. `cloud_sql.yaml`, to `skills/products/<product>.yaml`.
2. Fill in the fields (schema below).
3. Make sure the Terraform module it references already exists in your module
   repo under one of the `module_paths`. DriftGuard updates existing modules; it
   does not scaffold new ones.
4. Ship it:
   - `SKILLS_SOURCE=github` (recommended): just commit/push the file — it is
     picked up on the next run after the cache TTL. **No rebuild, no redeploy.**
   - `SKILLS_SOURCE=local`: rebuild the image or update the ConfigMap.
   Either way, no code change.

## Manifest schema

```yaml
name: Cloud SQL                 # required — display name used everywhere
enabled: true                   # optional — set false to disable without deleting
aliases:                        # strings that identify this product in a
  - Cloud SQL                   #   release-note title/description
  - CloudSQL
  - google_sql
resources:                      # Terraform provider resources it maps to
  - google_sql_database_instance
  - google_sql_database
module_paths:                   # module dirs in the Terraform repo that use them
  - modules/cloudsql
policy_allowed: true            # true => auto-actionable; false => manual review
relevance_topics:               # extra phrases that strengthen the embedding
  - Cloud SQL data cache        #   relevance filter (stage 1)
```

## What each field drives

| Field | Stage that uses it | Effect |
|-------|--------------------|--------|
| `name` | all | canonical product identity |
| `aliases` | RequestProcessor (match), relevance | matches release-note text to this product |
| `resources` | ChangeAnalyser, Terraform | provider resources to check/patch |
| `module_paths` | DecisionMaker | which module dirs to fetch + patch |
| `policy_allowed` | ChangeAnalyser | `true` auto-patches; `false` flags for review |
| `relevance_topics` | RequestProcessor | improves early relevance filtering |
| `enabled` | all | `false` skips the product entirely |

## Notes

- `policy_allowed: false` is useful for products you want to **track** (ingest +
  classify + analyse) but **not auto-patch** yet — the pipeline flags them for
  manual review instead of opening a PR.
- The same schema is used by the AWS and Azure editions; only the `resources`
  prefixes differ (`aws_`, `azurerm_`).

## Resource families & deep resolution

A product is usually a **family** of resources, not one. Declare secondary
resources via `related_resources` (or `resources: {primary: [...], related:
[...]}`) so features that live on a secondary resource — e.g. *custom context*
on `google_storage_bucket_object`, not the bucket — are found and patched on the
right resource. ChangeAnalyser calls `resolve_attribute_owner`, which grounds
against the real provider schema and never guesses. See
`docs/RESOURCE_FAMILIES.md`.

New optional manifest fields:

| Field | Purpose |
|-------|---------|
| `related_resources` | secondary resources in the family (deep-scan set) |
| `provider` | provider these resources belong to (defaults to the cloud's) |
| `provider_version` | version constraint to ground Terraform syntax against |
| `feeds` | the product owner's own feed list (url + format) |
