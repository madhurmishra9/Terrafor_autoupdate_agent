# Skills source — repo as single source of truth (no redeploy)

Skills (agent `SKILL.md` files and product manifests under `skills/products/`)
can be served two ways, selected by `SKILLS_SOURCE`.

## `local` (default)

Skills are read from the local `skills/` tree — baked into the image or mounted
via a volume. Simple and dependency-free, but changing a skill means shipping a
new image (or updating a ConfigMap).

## `github` — the repo is the single source of truth

Skills are fetched directly from the GitHub repository at runtime via the
contents API. Adding, editing, or removing a skill — or onboarding a product by
dropping a YAML manifest — takes effect on the **next pipeline run** (after the
cache TTL), with **no rebuild and no redeploy**.

Configure:

```bash
SKILLS_SOURCE=github
SKILLS_REPO_OWNER=your-org          # defaults to the module repo owner
SKILLS_REPO_NAME=terraform-modules  # defaults to the module repo name
SKILLS_REPO_REF=main                # branch, tag, or SHA (defaults to default branch)
SKILLS_REPO_PATH=skills             # path to the skills tree in the repo
SKILLS_CACHE_TTL=300                # seconds; how long fetched skills are cached
```

Auth reuses the pipeline's existing GitHub credentials (PAT or GitHub App), so
no extra secret is needed. You can keep skills in the **same** repo as your
Terraform modules, or point at a **dedicated** skills repo.

### How it works

`common/skills_source.py` abstracts both modes behind `read_text(path)` and
`list_dir(path)`. The skill loader and the product registry call only that
abstraction, so the rest of the pipeline is identical regardless of source.
Fetches are TTL-cached (`SKILLS_CACHE_TTL`) to avoid hitting the API on every
call. The product registry refreshes on the same TTL, so a new product manifest
in the repo appears automatically.

### Failure behaviour

- A skill that fails to load surfaces a clear error (the agent can't run without
  its instructions).
- The product registry **fails open** to an empty set if the products directory
  can't be listed, so a transient GitHub error degrades gracefully rather than
  crashing the pipeline.

### Recommended setup

- **Dev / fast iteration:** `SKILLS_SOURCE=github` with a short TTL (e.g. 60s) so
  edits show up almost immediately.
- **Prod:** `SKILLS_SOURCE=github` pinned to a tag or release branch
  (`SKILLS_REPO_REF=release`) for controlled rollout, or `local` if you prefer
  skills versioned lockstep with the image. Pinning to a SHA gives full
  reproducibility.
