# Scope guard — confining the change to one product

When DriftGuard updates a product, the patch must touch **only that product's
resources** — never the IAM, KMS, networking, or other resources that happen to
live in the same module file. A Spanner run changes Spanner resources; an S3 run
changes S3 resources; nothing else moves. This is the single biggest lever for
update accuracy: the tighter the blast radius, the fewer chances to edit the
wrong thing.

This is enforced **deterministically**, not just requested in the skill.

## How it works

After GenerateAgent generates and verifies a patch, before saving it:

1. `check_patch_scope(product, content, file_path)` parses every
   `resource "<type>" "<name>"` block and classifies each as **in-family** or
   **out-of-family**, using the product's manifest `resources` +
   `related_resources` (strict — no inference). It also checks the file is under
   the product's `module_paths`.
2. If any block is out-of-family, `strip_patch_scope(product, content)` removes
   those blocks and returns a patch containing only the product's own
   resources. In-family resources and all non-resource content (variables,
   locals, outputs) are left exactly as they were.
3. If the file is outside the product's `module_paths`, the patch is not saved
   and is flagged for review.

## Worked example — Spanner module with IAM + KMS

A real Spanner module often also contains a CMEK key and IAM bindings:

```hcl
resource "google_spanner_instance"   "main" { ... }   # in family
resource "google_spanner_database"   "db"   { ... }   # in family
resource "google_kms_crypto_key"     "key"  { ... }   # OUT of family -> untouched
resource "google_project_iam_member" "admin"{ ... }   # OUT of family -> untouched
variable "region" { ... }                              # not a resource -> kept
```

A Spanner update sees only `google_spanner_instance` and `google_spanner_database`
as eligible. The KMS and generic IAM blocks are stripped from the change set and
left as they were. The variable is kept.

### Product-owned vs generic resources

A product's **own** sub-resources are in-family when you list them. Spanner's own
IAM resources belong to Spanner:

```yaml
resources:
  - google_spanner_instance
  - google_spanner_database
related_resources:
  - google_spanner_database_iam_member   # Spanner's own IAM -> in family
  - google_spanner_instance_iam_member
```

But a generic `google_project_iam_member` is not Spanner-specific, so it stays
out of scope. The family list is the contract: declare every resource that is
genuinely part of the product, and only those are eligible for edits.

## Why strip rather than reject

You chose **strip** over reject: a patch that correctly updates Spanner but also
nudged an unrelated KMS block should still deliver the Spanner fix — minus the
out-of-scope edit — rather than being thrown away. The reviewer gets a clean,
product-scoped PR. (Path violations are still rejected, since editing the wrong
file is not something to silently trim.)

## Eval

The accuracy harness counts an out-of-scope candidate as not-shipped, so scope
discipline is measured alongside first-pass / verified accuracy. See
`docs/EVAL.md`.
