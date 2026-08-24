# Production Rollout & Rollback Runbook

Phase 8 deliverable per implementation-plan.md. This is the procedure a human
operator follows for a real rollout — see that file's Phase 8 section for
which parts of this phase a local repository can and cannot execute.

The "Auth service and web UI rollout" section below is Phase 9's deliverable
per ui-implementation-plan.md, covering the Google-sign-in auth service
(`authn/`), the sharing/drafts/tenant/PAT API surface added to this repo,
and the Next.js web UI (the independent sibling repo `jaas_ui`) built on
top of it.

## Why rollback is low-risk here

The registry is stateless compute over immutable, append-only storage
(design.md §2.1.1-2). A rollout only ever changes the *code* serving requests;
it never migrates or rewrites on-disk data. Concretely:

- Every published skill is stored under a content-addressed blob key
  (`blobs/<digest>`) and an immutable tag key (`tags/<id>/<version>/...`) —
  neither is ever overwritten by any code version, old or new.
- Any service instance — old build or new — that bootstraps against the same
  storage root produces an identical index (`bootstrap_index`, design.md
  §8.2.1). This is the property that makes "redeploy the previous image" a
  complete rollback, with no data migration step.
- There is no delete or in-place edit path in the API. A bad publish during a
  rollout window is not undone by rolling back; it is superseded by
  publishing a corrected version under a new SemVer.

`tests/resilience/test_rollback_dry_run.py` verifies this property directly:
data published while one "version" of the code is running is fully and
identically servable by a freshly constructed instance afterward.

## Pre-rollout checklist

Use implementation-plan.md §8 "Final Readiness Checklist" — critical test
suites green, SLO dashboards/alerts active (design.md §10, `alerts.py`),
security sign-off documented, on-call handoff complete.

## Canary procedure

1. Deploy the new build to a small subset of replicas behind the existing
   load balancer / ingress (design.md §11.2).
2. Route a small percentage of traffic to the canary subset.
3. Compare canary vs. baseline on the Phase 6 metrics (design.md §10.1),
   scraped from each fleet's `/metrics`:
   - `jaas_request_latency_seconds` p95 per endpoint, against the §9.1 SLOs.
   - 5xx share of `jaas_request_total` (same computation as
     `alerts.evaluate_error_rate_spike`).
   - `jaas_authz_denied_total` rate — a spike suggests a policy or JWT config
     regression in the new build, not real attack traffic, if it correlates
     with the canary specifically.
   - `jaas_signature_verification_failures_total` — any increase at all is a
     promotion blocker; see `alerts.evaluate_signature_verification_anomaly`.
   - `jaas_index_event_apply_lag_seconds` — confirms the new build's event
     consumer keeps up.
4. Promote (see below) only if canary metrics are within baseline tolerance
   on all of the above for the full observation window.

## Promotion

Expand the canary's traffic share gradually (e.g. 5% → 25% → 50% → 100%),
re-checking the same KPIs at each step before continuing.

## Rollback

1. Shift traffic weight for the canary subset back to 0%.
2. Terminate the canary replicas; the baseline fleet (previous image) is
   already serving 100% of traffic and requires no changes — it was never
   pointed anywhere else.
3. No data rollback step exists or is needed (see "Why rollback is low-risk
   here"). Confirm the baseline fleet still serves correctly post-rollback by
   re-running the standard health checks (`/api/v1/skills`, `/metrics`).
4. If the canary build published any skills during its window, they remain
   valid, immutable, and servable — rolling back the code does not need to
   (and cannot) retract them. If one was published in error, publish a
   corrected version; do not attempt to delete or overwrite it.

## Rollback dry run

`tests/resilience/test_rollback_dry_run.py` is the executable form of this
runbook's core safety property. A full dry run against real infrastructure
(shift traffic to a canary, then verify shifting it back is a no-op)
additionally requires a real load balancer and fleet, which is outside what
this repository can exercise on its own.

## Auth service and web UI rollout

### Why this is still low-risk

Everything added for Google sign-in, sharing, drafts, tenants, and PATs
(`authn/`, `sharing/`, `drafts/`, the `pat_id` JWT claim) is **additive**:
new routes under `/api/v1/auth`, `/api/v1/drafts`, `/api/v1/tenants`,
`/api/v1/account`, and new optional response fields (`visibility`,
`ownerUser`, `ownerTenant`) on the existing search/metadata endpoints. No
existing endpoint, request shape, or on-disk layout for previously-published
skills changes. Each new store (`UserStore`, `TenantStore`, `GrantStore`,
`DraftStore`, `PatStore`, `InviteStore`) follows the same file-backed,
one-file-per-entity pattern as the original registry (design.md §2.1.1-2)
under its own subdirectory of `policy_dir` — nothing is shared with or
overwrites the existing `blobs/`/`tags/` storage root, so the rollback
argument above ("no data migration step") applies unchanged.

There is intentionally **no feature flag** gating any of this (see
ui-implementation-plan.md's Phase 9 note for the reasoning): `common/
config.py`'s `FeatureFlags` pattern gates behavior inside one FastAPI
process, but the web UI is a separately deployed Next.js app (its own
repo, `jaas_ui`) calling this API over HTTP — there's no in-process branch
for a flag to control. The equivalent lever is simply whether `jaas_ui` is
deployed and routable; the backend additions here are safe to deploy
unconditionally ahead of that, since a client that never calls the new
routes is unaffected by their existence.

### Canary procedure (backend additions)

Deploy the backend build carrying `authn/`/`sharing/`/`drafts/` the same way
as any other backend change (see "Canary procedure" above), with two
additions to the standard metric comparison:
- `jaas_authz_denied_total` on the new routes specifically — a spike here
  most often means `JAAS_GOOGLE_CLIENT_ID` doesn't match the OAuth client
  `jaas_ui`'s users are signing in through, not real attack traffic.
- Search/metadata p95 stays within the visibility-filter budget documented
  in ui-implementation-plan.md's Phase 2 note (150ms → 160ms budget change),
  since every search request now evaluates `can_view` per non-public entry.

### Deploying `jaas_ui`

`jaas_ui` is a wholly separate repo/deploy from this one, with no canary
mechanism of its own described here (no fleet, no load balancer) — treat
"deploy `jaas_ui`" itself as the staged step, analogous to widening a
feature flag: point a small internal group at it first (e.g. an internal
hostname or allowlist at the reverse proxy), confirm sign-in and the
golden paths from ui-implementation-plan.md Phase 8 work end-to-end, then
open it up.

Required configuration before any `jaas_ui` deploy:
- `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` (jaas_ui) and
  `JAAS_GOOGLE_CLIENT_ID` (this backend) must reference the *same* Google
  OAuth client — a mismatch fails every sign-in with
  `INVALID_GOOGLE_TOKEN`, not a partial failure.
- `AUTH_SECRET` must be a freshly generated production secret, never the
  placeholder from `jaas_ui`'s `.env.local.example`.
- `JAAS_API_URL` (in `jaas_ui`) must point at the backend fleet the
  canary/promotion step above is targeting, not a dev/staging backend.

### Rollback

Undeploying `jaas_ui` (or reverting the backend build) follows the same
rollback procedure as above — shift traffic back, terminate, no data
rollback step. One addition specific to this surface: personal access
tokens minted during the window stay valid and revocable (`PatStore` is
unaffected by a code rollback) exactly like published skills stay valid and
servable; do not attempt to invalidate them as part of a rollback unless a
specific token is known to be compromised, in which case revoke it
individually via `DELETE /api/v1/account/tokens/{id}`.

## Guardrails service rollout

The publish-time content-safety scan (design.md §4.5) is a **third,
independently deployed service** —
[jaas-guardrails-catalog](https://github.com/balakrishna-maduru/jaas-guardrails-catalog)
— not part of this repo's build or release. It has its own repo, its own
CI, its own container image, and its own rollout cadence, entirely
decoupled from this app's.

### Why this is low-risk to deploy independently

This app never imports that service's code and never caches its catalog
beyond a single request — `api/deps.py::get_guardrail_catalog` fetches
fresh per request. That means:
- Deploying a new guardrails-service version never requires a coordinated
  deploy of this app. A rule change, threshold retune, or new check kind
  ships on the guardrails repo's own release, and this app picks it up on
  the very next request that needs it.
- If the guardrails service is down, degraded, or being deployed at that
  moment, this app's unrelated routes (search, sharing, auth, skill
  metadata) are entirely unaffected — only draft validate/publish, the
  tenant guardrail-policy endpoints, and `/api/v1/guardrails` return
  `503 GUARDRAILS_SERVICE_UNAVAILABLE` for that window, with a clear
  message naming the unreachable URL. There is no cascading failure and
  no need to fail this app's own health check because of it.

### Required configuration

- `JAAS_GUARDRAILS_SERVICE_URL` (this app) must point at wherever the
  guardrails service is actually running — `http://127.0.0.1:8028` is
  only the local-dev default `run.sh` wires up. A production deploy needs
  this set explicitly to the guardrails service's real address.
- The guardrails service itself takes no configuration beyond its bind
  host/port (`JAAS_GUARDRAILS_HOST`/`JAAS_GUARDRAILS_PORT`) — it has no
  database, no secrets, and no dependency on this app's `policy_dir` or
  any other state this app owns.

### Canary procedure

Because the two services are independently deployed, canary each
separately:
- **Guardrails service**: deploy the new version behind its own canary
  slice (or just a second instance on a second port during local/small-
  scale rollout), confirm `GET /healthz` and `GET /catalog` respond
  correctly, then point `JAAS_GUARDRAILS_SERVICE_URL` at it.
- **This app**: a build that only changes `guardrails/client.py` or
  `guardrails/policy.py` follows the standard backend canary procedure
  above, watching `jaas_authz_denied_total` is unaffected (guardrails
  routes have their own auth path, unrelated to this metric) and that
  `GUARDRAILS_SERVICE_UNAVAILABLE` responses stay at zero (a nonzero rate
  means the configured URL is wrong or that service is unreachable from
  the new canary instances specifically — a networking issue, not a code
  regression).

### Rollback

Rolling back either service independently is safe: this app has no
persisted state tied to a specific guardrails-service version (tenant
guardrail policies just name check ids as strings — `guardrails/
policy.py`'s `GuardrailPolicyStore.put()` validates ids against whatever
catalog is live *at write time*, so an id introduced by a newer catalog
version and then rolled back simply becomes "unknown" and is rejected on
the next write, not silently corrupted). Rolling back this app never
requires rolling back the guardrails service, and vice versa.
