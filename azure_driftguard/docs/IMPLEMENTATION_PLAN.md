# Implementation Plan — Azure DriftGuard Agent (Skills Architecture)

This plan describes how to deploy, validate, and operate the skills-driven
Azure DriftGuard Agent in a production GKE environment. It assumes the code in this
repository is the starting point.

## 0. Prerequisites

- AKS cluster (Autopilot or Standard) with AKS Workload Identity enabled.
- A Google Service Account (GSA) bound to the Kubernetes Service Account (KSA)
  with roles: `Cognitive Services OpenAI User, Key Vault Secrets User`,
  `roles/secretmanager.secretAccessor`.
- A Azure SQL Database instance reachable via the Azure SQL connection.
- An MCP server image for GitHub tools (deployed as a sidecar).
- Jira Cloud site (api/v3) with an API token, plus optional `acli` binary and
  a Jira Data Center instance for fallback testing.
- A GitHub PAT **or** a GitHub App (App ID, installation ID, private key).

## 1. Phased rollout

### Phase 1 — Hybrid (GenerateAgent on skills, rest on prompts)
The recommended first step. Migrate only `GenerateAgent` to a `SKILL.md` and
leave the other six prompt-based. This proves the `load_skill` pattern, the
skill-folder layout, and the deployment story with a small blast radius.
Measure token usage and output quality over 5–10 runs.

### Phase 2 — Extend to TicketAgent
Migrate TicketAgent next. Its 3-tier connectivity rules and ADF requirements are
complex and benefit most from a versioned skill after Terraform.

### Phase 3 — Remaining agents
Analyze → Decide → Ingest → PublishAgent, in that order.
Ingest and PublishAgent have the simplest rules, so they go last.

This repository ships **all seven** agents already on skills (the Phase-3 end
state). To run a hybrid, replace a given agent's
`instruction=skill_instruction_provider(...)` with an inline `instruction="..."`.

## 2. Configuration

All configuration is environment-driven (`src/.../common/config.py`). Copy
`.env.example` to `.env` for local runs; in GKE these become a ConfigMap and a
set of Secrets. Required groups:

- **GCP:** `GOOGLE_CLOUD_PROJECT`, `VERTEX_LOCATION`, `VERTEX_MODEL`
- **CloudSQL:** `CLOUDSQL_HOST=127.0.0.1`, `CLOUDSQL_*`
- **Jira:** `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`,
  `JIRA_API_VERSION=3` (Cloud) or `2` (Data Center), `JIRA_ACLI_PATH`
- **GitHub:** `GITHUB_API_BASE` (`https://api.github.com` or
  `https://<ghe-host>/api/v3`), `GITHUB_AUTH_MODE` (`pat`|`app`), and the
  matching credentials.

Secrets (`JIRA_API_TOKEN`, `CLOUDSQL_PASSWORD`, `GITHUB_PAT` or the App private
key) must come from Secret Manager / Kubernetes Secrets — never the image.

## 3. Jira connectivity (3-tier)

Order is enforced in `common/jira_client.py`:

1. `jira` Python library (primary)
2. `acli` Atlassian CLI subprocess (backup)
3. REST API v3 with `requests` (failback)

All rich-text inputs (ticket description, comments) are **ADF documents** for
Jira Cloud api/v3. For acli (which takes plain text) ADF is flattened
automatically. To validate all three tiers:

```bash
# Tier 1: ensure `jira` is installed and JIRA_API_TOKEN is valid
# Tier 2: ensure `acli` is on PATH and configured
# Tier 3: ensure the REST endpoint is reachable
python -c "from azure_driftguard.common.jira_client import JiraClient; print(JiraClient().probe())"
```

The printed tier (`library`/`acli`/`api`) is the highest one currently working.
Disable tiers one at a time (uninstall `jira`, rename `acli`) to confirm the
fallback chain degrades gracefully.

## 4. GitHub connectivity (PAT + App)

`common/github_client.py` supports both modes against api/v3:

- **PAT:** set `GITHUB_AUTH_MODE=pat` and `GITHUB_PAT`.
- **App:** set `GITHUB_AUTH_MODE=app`, `GITHUB_APP_ID`,
  `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`. The client signs
  a short-lived RS256 JWT, exchanges it for an installation token, and caches
  the token until ~5 minutes before expiry.

Validate:
```bash
python -c "from azure_driftguard.common.github_client import GitHubClient; print(GitHubClient().probe())"
```

## 5. Database

Apply the schema before the first run:
```bash
psql "$(python -c 'from azure_driftguard.common.config import get_config; print(get_config().cloudsql.dsn)')" \
  -f deploy/schema.sql
```
(Schema is also created idempotently by `cloudsql_store.ensure_schema()` on
startup.)

## 6. Build and deploy

```bash
# Build
docker build -t REGION-docker.pkg.dev/PROJECT/azure-driftguard/agent:$(git rev-parse --short HEAD) .

# Push
docker push REGION-docker.pkg.dev/PROJECT/azure-driftguard/agent:TAG

# Configure
kubectl apply -f deploy/k8s/config-and-secrets.yaml   # edit secrets first

# Deploy (Deployment for API-driven, or CronJob for scheduled runs)
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/cronjob.yaml
```

The Pod runs three containers: the agent (main), `cloud-sql-proxy` (sidecar),
and `mcp-server` (sidecar). The agent reaches CloudSQL at `127.0.0.1:5432` and
MCP at `http://localhost:8080`.

## 7. Validation checklist

```
□ All 7 agents declare output_key matching the state-key contract
□ Stop guard stamps output_key with STOP when pipeline_halted is True
□ cb_before_pipeline clears all 9 state keys
□ Jira tools attempt library → acli → api in order; tier recorded
□ All Jira descriptions/comments are ADF (api/v3)
□ acli path flattens ADF to text correctly
□ GitHub works in both pat and app modes against api/v3
□ GenerateAgent writes only artifacts (never repo); PublishAgent does repo writes
□ PublishAgent reads classification/short_description from ticket_result (no re-derive)
□ New PR triggers add_jira_comment linkback; jira_linked_back = true
□ fetch_only mode halts cleanly after ClassifyAgent
□ terraform validate passes on patched files
□ provider schema grounding active (extract_resource_schema used before generation)
□ self-correcting validate→plan loop regenerates on failure, capped at max_retries
□ version-pinning gate bumps required_providers when the pin blocks a feature
□ judge pass rejects patches below JUDGE_MIN_SCORE
□ tiered routing: Ingest + Classification on the fast model
□ relevance filter fails open (never silently drops releases)
□ schema/registry lookups are TTL-cached
□ pytest green; ruff/mypy clean
```

## 8. Observability

- Structured logs via `common/logging_setup.py`. Authorization headers and
  tokens are never logged.
- When `CAPTURE_ENABLED=true`, `cb_after_pipeline` writes an eval artifact per
  run to `CAPTURE_DIR` for replay/regression analysis.

## 9. Rollback

Image-baked skills mean every change ships as a new image tag — roll back by
redeploying the previous tag. If skills are mounted via ConfigMap for hot
iteration, revert the ConfigMap; pods pick up the change within ~90s **only if**
the skill is read per-invocation (this repo uses a per-invocation provider).
