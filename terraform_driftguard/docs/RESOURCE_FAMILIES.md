# Resource families & second-level resolution (anti-hallucination)

A cloud product is rarely a single Terraform resource. **Cloud Storage** is a
family: `google_storage_bucket`, `google_storage_bucket_object`,
`google_storage_object_access_control`, `google_storage_bucket_iam_member`,
`google_storage_bucket_acl`, and more. A release-note feature often lives on a
**secondary** resource — for example *custom context* is an attribute of the
storage **object**, not the bucket.

If the agent assumes every "Cloud Storage" feature belongs to the bucket, it
hallucinates: it invents `custom_context` on `google_storage_bucket`, which
doesn't exist there. This is the failure mode this feature eliminates.

## What the product owner declares

When onboarding a product repo, the owner provides the resource **family** and
(optionally) their own feeds and the provider version to ground against:

```yaml
name: Cloud Storage
aliases: [Cloud Storage, GCS]
provider: google
provider_version: ">= 6.0"        # version to ground syntax against

resources:                         # primary resource(s)
  - google_storage_bucket
related_resources:                 # secondary resources where features live
  - google_storage_bucket_object   # custom_context lives here
  - google_storage_object_access_control
  - google_storage_bucket_iam_member

module_paths: [modules/gcs]
policy_allowed: true

feeds:                             # owner's own feeds (optional)
  - url: https://cloud.google.com/feeds/storage-release-notes.xml
    format: atom

relevance_topics: [Cloud Storage custom context, GCS object metadata]
```

`resources` may also be written as `{primary: [...], related: [...]}`, and the
flat legacy form (`resources: [a, b]`) still works (everything becomes primary).

## How the agent avoids hallucinating

ChangeAnalyser, for each feature mentioned in a release note:

1. `list_product_resources(product)` → gets the full family (primary + related).
2. `resolve_attribute_owner(product, attribute)` → **grounds against the real
   provider schema** for the pinned version and returns the resource that
   actually declares the attribute.
   - `resolved=true` → use `owner_resources` (e.g. `google_storage_bucket_object`).
   - `resolved=false` (`schema_unavailable` or `attribute_not_found`) →
     `action=flag_for_review`. The agent must **not** guess an owner.
3. `list_family_schema(product)` → optionally returns the real argument/block
   surface of every resource in the family, so the model checks against grounded
   syntax instead of memory.

The guarantee: an attribute is only attached to a resource the **schema
confirms** owns it. When the schema can't be fetched (no `terraform` binary /
provider download), the change is flagged for manual review rather than guessed
— a missed auto-patch is acceptable; a hallucinated one is not.

## Under the hood

`common/schema_index.py` fetches the provider schema for every resource in the
family once (TTL-cached), and builds an inverted index
`attribute → [resources that declare it]`. `resolve_attribute_owner` is a
deterministic lookup in that index — no LLM involved in deciding ownership, so
it cannot hallucinate. The model's job is only to *extract candidate attribute
names* from the release text; *which resource owns them* is answered by the
schema.

## Why version matters

Provider syntax changes across versions — an argument may move, get renamed, or
be added. `provider_version` (or the module's pin) is passed into the schema
fetch so resolution reflects the **exact** version being targeted, not "latest".
That is what makes the generated patch match the provider the module actually
uses.
