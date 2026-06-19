# Feeds & scheduling — which feeds, and when

Two separate questions: **which** release feeds the pipeline reads, and **when**
it runs. Neither requires code changes.

## Which feeds (declarative)

RequestProcessor calls `list_feeds` at the start of every run. It returns:

1. **The shared cloud feed** — `RELEASE_FEED_URL` (GCP release notes by default).
   This is the catch-all; products are matched out of it by their `aliases`.
2. **Per-product feeds** — any `feed_url` declared in a product manifest under
   `skills/products/*.yaml`. Use this when a product publishes its own dedicated
   feed, or when you want it polled separately from the shared one.

```yaml
# skills/products/alloydb.yaml
name: AlloyDB
aliases: [AlloyDB, google_alloydb]
# ...
feed_url: https://cloud.google.com/feeds/alloydb-release-notes.xml   # optional
feed_format: auto        # auto | atom | rss
```

RequestProcessor fetches the shared feed plus every per-product feed, normalises
all entries, then de-duplicates by `(product, version, release_date)`. So
onboarding a product with its own feed is — like everything else — one manifest
file, no code change. With `SKILLS_SOURCE=github` it needs no redeploy either.

### How a release is matched to a product

For entries from the **shared** feed, the product registry's `match()` resolves
the release title/description to a known product via its `aliases`. For entries
from a **per-product** feed, the product is already known (the feed belongs to
it). Either way the downstream stages see a canonical product name, and the
`policy_allowed` flag decides whether it auto-patches or is held for review.

## When it runs (scheduled trigger)

The pipeline has no internal scheduler — a single run processes the current
feeds end to end. "When" is an **external trigger**:

| Cloud | Trigger |
|-------|---------|
| GCP | Kubernetes `CronJob` (`deploy/k8s/cronjob.yaml`, daily 06:00 UTC by default) |
| AWS | EventBridge schedule → ECS scheduled task, or an EKS `CronJob` |
| Azure | AKS `CronJob`, or a Logic App / Scheduler trigger |

Change the cadence by editing the cron expression — e.g. `0 */6 * * *` for every
six hours. Each run reads everything in the feeds since it last persisted them;
already-seen releases are skipped via the `check_existing_release_note` /
dedup step against the datastore, so running more frequently is safe and just
means fresher PRs.

`list_feeds` also returns `triggered_at` (the run's start time), which flows into
the run's audit/eval artifact so you can see exactly when each run fired and what
it saw.

### Why not per-product schedules?

Per-product cadence is intentionally **not** baked into the agents — mixing
scheduling into the manifest would couple "what we track" with "how often we
poll," and the dedup step already makes frequent global polling cheap. If you do
need different cadences (e.g. poll a fast-moving product hourly but others
daily), run multiple scheduled triggers with different `MANAGED_PRODUCTS` /
manifest subsets rather than encoding time in the product files.
