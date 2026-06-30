# Accuracy & Optimisation Features

AWS DriftGuard layers several correctness and cost features on top of the
base pipeline. Each is independently toggleable via environment variables so you
can roll them out incrementally and measure impact.

## Accuracy

### 1. Provider schema grounding
**Where:** `agents/tools_terraform.py` — `get_provider_schema`,
`extract_resource_schema`.
Before generating any HCL, GenerateAgent fetches the *real* provider schema for
the exact target version. When the `terraform` binary is present it runs
`terraform providers schema -json` (authoritative); otherwise it falls back to
the Registry version metadata. The resource's argument names and required flags
are passed into the model so it generates only valid arguments instead of
recalling them from training data. Results are TTL-cached.

### 2. Self-correcting validate → plan loop
**Where:** `agents/tools_terraform.py` — `validate_hcl`, `plan_hcl`,
`verify_patch`. Skill drives the loop.
After generating a patch the agent calls `verify_patch`, which runs
`terraform fmt` → `init` → `validate`, then `terraform plan -detailed-exitcode`.
- validate error or plan exit 1 → feedback returned, agent regenerates
- plan exit 0 (no changes) → patch had no effect, regenerate
- plan exit 2 (changes) → verified
Capped at `TERRAFORM_MAX_RETRIES` (default 3). A patch that never verifies is
**not** saved and is reported as `verification_failed`.

### 3. Version-pinning gate
**Where:** `agents/tools_terraform.py` — `check_version_pin`.
Checks whether the module's current `required_providers` constraint actually
permits the version that introduces the requested feature. If not, the agent
must bump `required_providers` as part of the patch — preventing patches that
are syntactically valid but blocked by the pin.

### 4. Judge / critic pass
**Where:** `agents/tools_judge.py` — `judge_patch`.
A separate lightweight model scores the patch's *semantic* correctness against
the change requirement and the resource schema (0–100). Patches below
`JUDGE_MIN_SCORE` (default 70) are rejected and regenerated once. Catches
subtle errors that pass `validate` but don't actually satisfy the requirement.
Disable with `JUDGE_ENABLED=false`.

## Optimisation

### 5. Tiered model routing
**Where:** `agents/definitions.py`, `common/config.py`.
Ingest and Classification (parsing + bucketing) run on the cheaper
`VERTEX_MODEL_FAST` (default `gemini-2.5-flash`). Reasoning-heavy agents
(Analyze, Decide, Terraform) stay on `VERTEX_MODEL`
(`gemini-2.5-pro`). The judge uses `VERTEX_MODEL_JUDGE` (fast by default).

### 6. Embedding-based relevance filter
**Where:** `agents/tools_relevance.py` — `score_release_relevance`.
Ingest scores each GA release against the managed module surface using
text embeddings, dropping low-relevance notes before the expensive
classification + analysis stages. **Fails open**: if embeddings are unavailable
the note is kept, so releases are never silently dropped.
Disable with `RELEVANCE_FILTER_ENABLED=false`.

### 7. TTL cache for schema + registry lookups
**Where:** `common/cache.py`.
Provider schemas and Registry metadata change rarely, so they are cached for
`CACHE_TTL_SECONDS` (default 1 day). Shared across Analyze and Terraform.
For multi-replica deployments, swap the in-process `TTLCache` for a Redis- or
CloudSQL-backed implementation behind the same `get`/`set` interface.

### 8. Batched classification
**Where:** `common/config.py` — `CLASSIFICATION_BATCH_SIZE` (default 5).
Classification processes notes in small batches with per-item retry to avoid the
large-batch JSON parse failures (`Unterminated string`) seen with big payloads.

## Rollout order (recommended)

1. Provider schema grounding (#1) — removes the most common class of wrong output
2. Self-correcting validate → plan loop (#2) — guarantees only valid HCL ships
3. Tiered model routing (#5) — immediate cost cut, no accuracy loss
4. Judge pass (#4) — strongest additional accuracy gain once 1–2 are in place
5. Relevance filter (#6), caching (#7), batching (#8) — incremental optimisation

Every feature degrades gracefully: when `terraform`, the GenAI SDK, or embeddings
are unavailable, the pipeline falls back to safe behaviour rather than failing.
