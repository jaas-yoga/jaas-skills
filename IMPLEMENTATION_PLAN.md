# JaaS Skills Roadmap — Implementation Plan (All Phases)

## Context

`jaas-skills/ROADMAP.md` (Sept 2026) audited all three JaaS repos — `jaas-ui`
(Next.js frontend), `jaas-skills` (the `jaas-registry` FastAPI backend under
`src/jaas_registry`), and `jaas-guardrails` (standalone scanning service) —
against where the agent-skills ecosystem is moving. It lays out four
phases. This plan turns that into an executable sequence: a full outline of
all 16 items across all 4 phases, and a concrete, code-verified design for
Phase 1 (0–4 weeks), which implementation starts on immediately after this
plan is approved.

Every claim under Phase 1 was checked directly against the code by two
Explore agents and one Plan agent — file paths, current behavior, and
architectural constraints are verified, not assumed. Four product
judgment calls the design surfaced were resolved with the user (see
"Resolved judgment calls"). Phases 2–4 are scoped from the roadmap audit
and this session's own findings about shared subsystems, but **not** yet
verified line-by-line the way Phase 1 is — each should get its own
Explore→Plan pass when its horizon arrives; treat their "impacted areas"
as a reliable starting map, not a final file list.

For every item below: **what it does**, **breaking-change risk**,
**what it improves**, and **impacted areas** (files/endpoints/components
touched).

**Tracking:** once approved, this document is committed as
`jaas-skills/IMPLEMENTATION_PLAN.md` (alongside `ROADMAP.md`, which it
derives from) as the first action, so phase/item progress has a durable,
version-controlled home in the repo rather than living only in local
Claude Code plan state.

---

## Phase 1 — Harden the foundation (0–4 weeks) — implementing now

### 1.1 — Frontend test suite (Playwright + component tests) · `jaas-ui`

**What we're building:** The app currently has zero automated test
coverage — no test runner, no config, no test files (verified: no `"test"`
script in `package.json`, no jest/vitest/playwright installed, no
`*.test.*`/`*.spec.*` anywhere). We add two layers: Vitest + React Testing
Library for component-level tests of the draft/publish workspace's
client-side pieces, and Playwright for real end-to-end browser tests that
drive the app against a live backend using the existing `dev-login`
credentials provider. Plus a new CI workflow that actually runs them on
every PR (today, nothing runs on PRs except a post-*approval* build).

**Does it break anything?** No runtime/production risk — this is purely
additive tooling, config, and test files. The one place existing component
code might need a small touch: if a component's DOM structure makes an
interaction hard to target reliably (e.g. an icon-only button with no
accessible name), we may add a `data-testid` or `aria-label` to that
element. That's the only category of change to shipped component code —
no logic changes, no behavior changes. CI gets slower (a new job that
boots the backend for E2E), which is a cost, not a break — flagged in the
resolved judgment calls as accepted.

**What it improves:** Turns the draft/publish workspace — described in the
roadmap as "the product's core interaction" with today "zero automated
coverage, a regression currently ships silently" — into a covered path.
Concretely: the autosave-debounce logic, the Save/Validate/Publish button
states, and the git-merge-conflict error surface all become regression-
tested instead of relying on someone noticing a break by hand.

**Impacted areas:**
- New: `playwright.config.ts`, `vitest.config.ts`, `src/test/setup.ts`,
  `e2e/*.spec.ts`, `e2e/auth.setup.ts`, `.github/workflows/ci.yml`.
- New test files co-located with: `src/components/drafts/draft-workspace.tsx`,
  `publish-dialog.tsx`, `validation-results-panel.tsx`.
- `package.json` — new `devDependencies` and `test`/`test:e2e` scripts.
- Possible minor, additive-only edits (test hooks/labels) to the same
  `src/components/drafts/*.tsx` files — no behavior change.
- **Not touched:** `src/lib/jaas-api.ts`, `src/auth.ts`, any Server Action
  logic in `src/lib/actions.ts`, any backend code. Existing workflows
  `build-on-approval.yml` and `docker-publish.yml` stay exactly as-is.

---

### 1.2 — Real Sigstore/Cosign signing · `jaas-skills`

**What we're building:** Today, every publish path (CLI, web UI, and the
CI `/release` endpoint) signs artifacts server-side with an in-process
RSA-2048 keypair — the code's own docstring calls this "a local-dev
stand-in, not production signing." We replace the CI release path's
signing with real Sigstore keyless signing: `jaasctl release`, running
inside a GitHub Actions job, signs the artifact digest itself using its
ambient OIDC identity (no secrets, no long-lived keys — a Fulcio-issued
short-lived cert plus a public Rekor transparency-log entry). The registry
server's job changes from "sign" to "verify that signature against
Fulcio/Rekor." The existing RSA path stays, unchanged, for `jaasctl
publish` and the web-UI publish button, since neither has a CI OIDC
identity to sign with.

**Does it break anything?**
- **Existing published artifacts:** No re-signing, no backfill, no
  behavior change — old tags have no `signature_kind` field; its absence
  is treated as `"dev-rsa"` and verifies exactly as it does today.
- **Existing CI consumers who haven't upgraded `jaasctl`:** Not broken —
  the new `sigstore_signing_required` flag defaults to `False`, so
  `/release` still accepts and dev-RSA-signs a release with no Sigstore
  bundle attached, same as today. Nothing is enforced until an operator
  explicitly opts in per-tenant.
- **API contract change:** `ReleaseRequest` gains one new **optional**
  field (`sigstoreBundle`) — additive, not a breaking schema change; old
  clients omitting it behave exactly as before.
- **One real risk to design around:** `jaasctl release` run **outside**
  GitHub Actions (e.g. a developer testing the release command locally)
  has no ambient OIDC token to sign with. The plan must make this fail
  clearly (a specific error telling the user this command requires a CI
  OIDC context, or falls back to dev-RSA with a loud warning) rather than
  crash unhelpfully — this is an implementation detail to nail down, not
  yet fully specified, and worth confirming before coding: **should local
  `jaasctl release` runs fall back to dev-RSA signing (with a warning), or
  hard-fail?** Recommend hard-fail with a clear message, since `/release`
  is specifically the CI-trust-chain path per the design doc — silently
  downgrading its security guarantee is worse than refusing.
- **Storage/index schema change:** the manifest/index record gains a
  `signature_kind` field. Same additive-with-default pattern as visibility
  and other historically-added fields elsewhere in this file — verified
  the codebase already has a safe precedent for this (`parse_published_record`
  defaults missing fields today).

**What it improves:** Closes the roadmap's top-named security gap —
unsigned/weakly-signed skill packages are called out industry-wide as an
active attack surface (the roadmap cites a real supply-chain incident:
84 malicious npm package versions across 42 packages in a six-minute
window, one with forged-looking provenance). This moves the CI release
path onto the same keyless-signing model the rest of the package-registry
industry (npm, PyPI Trusted Publishing) is converging on.

**Impacted areas:**
- Backend: `src/jaas_registry/artifact/signing.py`, `verify.py`, `trust.py`
  (new `SigstoreTrustPolicy` alongside the unchanged RSA one),
  `artifact/publish.py` (accepts either signing path), `api/schemas.py`
  (`ReleaseRequest` new optional field), `api/release_routes.py`,
  `common/config.py` (new `sigstore_signing_required` flag + Fulcio/Rekor
  settings), `pyproject.toml` (new `sigstore-python` dependency),
  `index/models.py`/`index/ingest.py` (new `signature_kind` field, default
  handling).
- CLI: `cli.py`'s `release` command gains the client-side signing step.
- CI reference workflow: `examples/ci/github-actions-release.yml` — no new
  secrets, existing `permissions: id-token: write` is sufficient; comments
  updated to explain the implicit Sigstore token request.
- **Not touched:** `jaasctl publish`, web-UI draft-publish
  (`api/draft_routes.py`), or anything in `jaas-ui` — those paths keep
  dev-RSA signing unconditionally, just with a clearer "not Sigstore"
  label in their output.

---

### 1.3 — Version deprecation / "yank" mechanism · `jaas-skills`

**What we're building:** Today, once a version is published there is no
way to flag it as insecure/broken after the fact — certification is
computed once at publish time and never revisited. We add a reversible
`yank`/`unyank` action: a maintainer (owner or tenant admin) can mark a
version yanked with an optional reason; yanked versions are skipped by
default resolution (`latest`, version ranges, default search) but remain
directly accessible by an exact version pin, with a `status` field exposed
in the API/UI so consumers see a warning.

**Does it break anything?**
- **Immutability guarantee stays intact.** The core design principle —
  published artifacts are content-addressed and immutable — is not
  touched. Yank status lives in a brand-new sidecar file next to the
  manifest, never inside or overwriting it. The manifest a client already
  has cached/downloaded is byte-for-byte unchanged.
- **`ObjectStore` protocol change:** adding `write_object()` to the
  `Protocol` in `storage/base.py` means **both** existing implementations
  (`LocalFilesystemStore`, `S3ObjectStore`) must implement it in the same
  change — if only one gets it, the other silently violates the protocol
  contract at runtime (Python `Protocol`s aren't enforced until called).
  This is a real thing to get right in one PR, not two.
- **`IndexEntry` field addition:** `status: str = "active"` — has a
  default, so every existing call site, fixture, and serialized record
  keeps working unchanged. Low risk, same pattern this dataclass already
  uses for prior additive fields.
- **Event-bus signature change:** `new_index_update_event()` needs a new
  parameter to avoid the event-ID collision bug this exploration found
  (yank and publish would otherwise generate the identical `event_id` and
  the yank event would be silently dropped by the consumer's dedup logic —
  confirmed by reading `index/consumer.py` directly). The new parameter
  must default to today's "publish" behavior so the **existing publish
  call sites need zero changes** — this is a backward-compatible signature
  extension, not a breaking one, as long as it's implemented with a
  default.
- **Read-path behavior change:** `InMemoryIndex.get_resolved()` gains
  yank-aware filtering. This changes what `latest`/range resolution
  returns *if* a version is yanked (by design — that's the feature) but
  does not change resolution for any version that isn't yanked, i.e. zero
  behavior change for the entire existing catalog on day one.
- **Certification is explicitly NOT touched** — yank doesn't trigger
  re-scans or mutate `guardrail_certified_level`, so the guardrails engine
  and its existing tests are unaffected.

**What it improves:** Closes the loop the roadmap calls out directly:
"certification is point-in-time only" with "nothing today lets a
maintainer flag a version as insecure after the fact." Gives operators a
real incident-response lever without violating the platform's immutability
principle.

**Impacted areas:**
- New: `src/jaas_registry/artifact/status.py`,
  `tests/integration/test_yank.py`, `tests/unit/test_artifact_status.py`.
- Modified: `storage/base.py` (Protocol), `storage/local_filesystem.py`,
  `storage/s3_store.py` (implement `write_object` in both — this file now
  exists, per Phase 2.3 below, landed 2026-09-02),
  `index/models.py` (`IndexEntry.status` field), `index/bootstrap.py` and
  `index/consumer.py` (sidecar overlay on entry construction),
  `index/events.py` (event kind/discriminator), `index/store.py`
  (`get_resolved` filtering), `index/query.py` (search exclusion),
  `api/routes.py` (new `/yank`, `/unyank` routes + generalized
  `_require_share_management_access`), `api/schemas.py`
  (`YankRequest`/`YankResponse`, `status` field on
  `SkillMetadataResponse`/`SearchResultItem`).
- **jaas-ui is NOT touched in this item** — surfacing the yanked-status
  warning banner in the skill detail page is explicitly deferred (noted as
  a Phase 3.4-adjacent follow-up, since 3.4 is already "ship missing UI
  surfaces"). Phase 1.3 is backend-only; the API returns `status`, nothing
  in the frontend reads it yet.

---

## Phase 1 sequencing & landing order

All three items are independent (different repos/subsystems) and can be
built in parallel. One coordination note: 1.2 and 1.3 both add a field to
the same `IndexEntry` dataclass and touch `index/ingest.py`'s parse/
serialize pair — land 1.3 first (smaller, self-contained), then rebase 1.2
past it, or combine the two field additions into one small shared PR if
worked concurrently. Recommend landing order: **1.3 → 1.1 (parallel,
independent) → 1.2** (1.2 has the most operational surface — CI OIDC
behavior — worth landing last so it can lean on the new CI test workflow
from 1.1 to validate itself).

### Resolved judgment calls (confirmed with user)
- Yank is reversible — both `/yank` and `/unyank`.
- Resolution semantics: excluded-but-pinnable (PyPI/npm-style).
- Yank authorization: owner or tenant admin, reusing the `/shares`
  authorization tier.
- Frontend E2E: full scope including cross-repo CI backend bootstrap.

### Open item to confirm before coding 1.2
- Local (non-CI) `jaasctl release` runs have no OIDC identity to sign
  with. Recommend **hard-fail with a clear message** (this command
  requires a CI OIDC context) rather than silently falling back to dev-RSA
  signing under the CI-trust-chain endpoint. Flag if a silent fallback is
  preferred instead.

---

## Phase 2 — Interoperate with the standard (1–3 months)

### 2.1 — SKILL.md / agentskills.io import & export · `jaas-registry` + `jaas-ui`

**What we're building:** A bidirectional mapping between this registry's
internal manifest format and the open `agentskills.io` `SKILL.md` +
frontmatter format, so skills published here can be pulled by any of the
~40 tools reading that standard (Claude Code, Cursor, Copilot, etc.), and
external `SKILL.md` packages can be imported as drafts here.

**Breaking-change risk:** Low if scoped as pure import/export converters —
the internal manifest model and storage format are not proposed to change,
only a new translation layer sitting alongside them. Real risk area: if
the internal manifest has fields with no `SKILL.md` equivalent (or vice
versa), export is lossy — needs an explicit decision (documented, not
silently dropped) on what's preserved vs. what only round-trips within
this registry.

**What it improves:** Highest-leverage item on the roadmap — turns every
published skill from "usable in this registry only" into portable across
the open standard's whole tool ecosystem, with no extra authoring work.

**Impacted areas (preliminary):** new serialization module in
`src/jaas_registry` (likely `artifact/skillmd.py` or similar — not yet
verified against actual manifest model internals), a new API
endpoint/CLI path for import, and a jaas-ui UI surface in the draft
workspace (`src/components/drafts/`) for "export as SKILL.md" /
"import from SKILL.md." Needs its own Explore pass on the manifest model
(`artifact/manifest.py` or equivalent) before a real plan.

### 2.2 — `jaasctl search / pull / install` · `jaas-registry` CLI

**What we're building:** New CLI subcommands so `jaasctl` behaves like a
package manager (search the registry, pull a skill's files, install it
into a local agent's skill directory), not just publish/validate.

**Breaking-change risk:** Very low — additive CLI subcommands against
existing read APIs (search, metadata, artifact download all already
exist per the roadmap audit). No server-side changes expected.

**What it improves:** Every current framework integration is hand-rolled
REST calls; this gives a real command-line consumption path.

**Impacted areas (preliminary):** `cli.py` only, client-side. Needs
confirmation that the artifact-download API already returns everything
`pull`/`install` need (likely yes, not yet verified).

### 2.3 — Object storage backend (S3/MinIO) · `jaas-registry` — ✅ DONE (2026-09-02)

**Status: landed ahead of schedule**, out of sequence with the rest of the
roadmap — this was already built and sitting uncommitted in the working
tree when Phase 1 kicked off; reviewed (12/12 tests pass, full suite green
apart from one pre-existing unrelated perf-test flake, `ruff` clean) and
committed as its own change in both repos rather than rebuilt.

**What was built:** `S3ObjectStore` (`storage/s3_store.py`) implements the
existing `ObjectStore` protocol against any S3-compatible endpoint (OCI
Object Storage's S3 Compatibility API, MinIO, AWS S3), selected via a new
`storage/factory.py::build_store()` + `Settings.storage_backend` config
(`"local"` default, `"s3"` opt-in). Immutability for `write_tag_if_absent`
uses a conditional PUT (`IfNoneMatch="*"`) — the S3-native equivalent of
the local store's `O_EXCL` create. Deploy-side: `jaas-ui/deploy/`
(`docker-compose.yml`, `.env.example`, `README.md`) and both repos'
`docker-publish.yml` were updated to pass the new `JAAS_STORAGE_S3_*` env
vars through CD.

**Breaking-change risk:** None realized — local filesystem stays the
default, existing deployments are unaffected unless `JAAS_STORAGE_BACKEND=s3`
is explicitly set.

**What it improved:** The interface was already built swappable; this is
the item separating "prototype" from "deployable at real scale."

**Impacted areas (actual):** `src/jaas_registry/storage/s3_store.py`,
`storage/factory.py` (new), `common/config.py` (new `storage_backend`/
`storage_s3_*` settings), `cli.py` (`cmd_publish`/`cmd_serve` use
`build_store()`), `pyproject.toml` (`boto3`, `moto[s3]` dev dep),
`tests/unit/test_storage_s3_store.py`, `tests/unit/test_storage_factory.py`,
both repos' `.github/workflows/docker-publish.yml`, `jaas-ui/deploy/*`.
Commits: `0ad5aa9` (jaas-skills), `97e1611` (jaas-ui).

**Follow-up still open:** Phase 1.3's new `write_object()` method must be
added to this `S3ObjectStore`, not just `LocalFilesystemStore` — noted in
1.3's impacted-areas above.

### 2.4 — Wire up the existing event-bus index sync · `jaas-registry`

**What we're building:** The multi-replica index-sync consumer/event-bus
machinery already exists in the codebase (the same `IndexEventConsumer`
touched by Phase 1.3's yank event) but is never actually invoked from
`create_app()` — so multi-replica deployments don't stay in sync today.
This wires the existing machinery in.

**Breaking-change risk:** Low, but not zero — turning on previously-dead
sync code for the first time can surface latent bugs in code paths that
have never run in production. Needs a real multi-replica test, not just
unit tests. Cheapest item on the whole roadmap per the audit, but "cheap
to code" isn't the same as "zero risk to enable."

**What it improves:** Correctness for any multi-replica deployment (single-
replica deployments are unaffected either way, since sync only matters
once there's more than one).

**Impacted areas (preliminary):** `create_app()` / app startup wiring
(likely `main.py` or `app.py`), no data-model changes expected.

---

## Phase 3 — Compete on trust (3–6 months)

### 3.1 — Usage-based discovery ranking · `jaas-registry`

**What:** Search ranking today is static token-matching with no usage
signal. Adds usage-event collection (net-new — nothing tracks this today)
feeding into `index/query.py`'s ranking.
**Breaking-change risk:** Medium — changes real search result ordering
for every existing query; needs a rollout plan (e.g. behind a flag,
A/B-able) rather than a silent ranking-algorithm swap, since it changes
what users see for the same query.
**Improves:** Surfaces the curation signal the roadmap's own research
shows matters (16.2-point measured task-success gap for curated results).
**Impacted areas (preliminary):** `index/query.py`, a new usage-tracking
store, likely a new API endpoint or middleware to record usage events.

### 3.2 — Grant-lookup caching for sharing at scale · `jaas-registry`

**What:** A cache layer in front of `GrantStore` lookups (already flagged
as an unmitigated risk in the UI design doc's own risk register).
**Breaking-change risk:** Medium if cache invalidation is wrong — a stale
grant cache could either wrongly deny access (availability bug) or wrongly
allow it (security bug) after a grant is revoked. This needs correctness
scrutiny, not just a cache-aside performance patch.
**Improves:** Sharing/visibility checks under real tenant/grant-count
scale (fine at prototype scale today).
**Impacted areas (preliminary):** wherever `GrantStore` is defined and
consumed — the same routes touched by Phase 1.3's yank authorization
(`api/routes.py`'s `_require_share_management_access` and its callers).

### 3.3 — Governance surface: audit export, identity fields, EU AI Act mapping · `jaas-registry`

**What:** New fields on the index/audit model (owning team, business
purpose, systems accessed, review date) per the Cloud Security Alliance's
Agentic Trust Framework, plus an audit-export endpoint. EU AI Act
high-risk obligations take effect August 2026 — this is compliance-driven,
sales-enablement as much as engineering per the roadmap.
**Breaking-change risk:** Low — additive fields/endpoint, same pattern as
other historically-added `IndexEntry` fields.
**Improves:** Answers the specific fields regulators/enterprise buyers are
already asking for.
**Impacted areas (preliminary):** `index/models.py`, `AuditSink` and its
consumers, a new export API route.

### 3.4 — Ship the missing UI surfaces · `jaas-ui`

**What:** Backend already supports a published-file viewer, cross-tenant
sharing audit page, and share/validation notifications — none has
frontend today. Pure UI debt-paydown, no backend work.
**Breaking-change risk:** Low — new pages/components, not modifications to
existing ones (though this is also where Phase 1.3's `status` field
finally gets a UI treatment — the yanked-version warning banner belongs
here).
**Improves:** Closes real UI gaps against already-shipped backend
capability.
**Impacted areas (preliminary):** new pages under `src/app/(app)/`, new
components alongside `src/components/drafts/` and wherever the existing
skill-detail view lives.

---

## Phase 4 — Scale the ecosystem (6–12 months)

### 4.1 — Framework SDKs (LangGraph, CrewAI, AutoGen) · new packages
**What:** Thin client packages wrapping the existing registry REST API per
each framework's tool/plugin conventions.
**Breaking-change risk:** None to the existing registry — these are new,
separate packages consuming the existing public API surface.
**Improves:** Removes today's "hand-write REST calls" integration tax for
each framework.
**Impacted areas:** entirely new repos/packages, no changes to `jaas-ui`
or `jaas-skills`.

### 4.2 — Billing, plans, and quota model · `jaas-registry`
**What:** Net-new — no rate limiting or billing code exists anywhere
today. Needs its own dedicated design pass; too large and too dependent on
commercial decisions (pricing tiers, quota semantics) to scope here.
**Breaking-change risk:** Potentially significant — the first time any
request can be *rejected* for a non-auth, non-validation reason (quota
exceeded), every existing API consumer needs to handle a new class of
error. Needs careful rollout (e.g. soft-limit/warn-only period before hard
enforcement).
**Improves:** Makes the registry viable as a metered commercial product.
**Impacted areas:** touches essentially every API route (`api/routes.py`,
`api/release_routes.py`, `api/draft_routes.py`) for quota checks — the
widest blast radius of any single item on the roadmap.

### 4.3 — Multi-registry federation · `jaas-registry`
**What:** Net-new concept — every current design doc assumes one registry
instance. Adds resolving a dependency/mirror that lives in a different
registry.
**Breaking-change risk:** Low to existing single-registry deployments if
federation is strictly additive/opt-in; high design complexity in trust
propagation (does a federated registry's Sigstore/certification trust
carry over? — directly builds on Phase 1.2's trust-policy work).
**Improves:** Lets the registry mirror public upstreams or resolve
cross-registry dependencies.
**Impacted areas:** `index/`, `artifact/trust.py` (extends Phase 1.2's
work), new federation-specific API surface.

### 4.4 — Load-test to the stated 50,000-package target · `jaas-registry`
**What:** Extends current performance tests (validated at a 2,000-skill
corpus only) to the design doc's stated 50,000-package/12-month capacity
target.
**Breaking-change risk:** None by itself (it's testing, not a feature) —
but findings from it may force changes elsewhere (e.g. the index's
in-memory model, `InMemoryIndex`, may not hold 50k entries comfortably;
this could feed back into needing a real index backend, which isn't
currently scoped anywhere on the roadmap).
**Improves:** Validates (or disproves) the stated scale target before
customers hit it in production.
**Impacted areas:** test infrastructure only, until/unless it surfaces a
real scaling gap.

### 4.5 — Abuse workflow & re-certification sweep · `jaas-registry`
**What:** Certification is point-in-time by design (the same principle
Phase 1.3 works around for yank) — a version certified under an older,
laxer guardrails catalog is never retroactively re-flagged. Adds a
deliberate re-scan path plus a report/takedown flow for public skills.
**Breaking-change risk:** Medium — a re-certification sweep can change a
previously "certified" version's displayed status without any new publish
action from its owner, which is a new kind of state change this platform
hasn't had before (everything else changes only in response to an explicit
actor action). Needs clear communication/notification design, not silent
status flips.
**Improves:** Closes the gap where old certifications never reflect new
guardrail rules; adds a takedown path that doesn't exist at all today.
**Impacted areas:** `artifact/` guardrail-certification code, likely
extends Phase 1.3's `status` sidecar mechanism (a "flagged for re-review"
state fits the same pattern), a new report-intake API/route, notification
plumbing.

---

## Verification (Phase 1)

- **1.1:** `npm run lint && npm run test` locally, then `npm run test:e2e`
  against a locally running `jaas-skills` backend (`uv run jaasctl serve`
  with `JAAS_DEV_LOGIN_PASSWORD` set) before relying on CI; confirm the new
  `ci.yml` goes green on a real PR.
- **1.2:** unit tests for both `TrustPolicy` implementations (dev-RSA
  unchanged, new Sigstore path); an integration test publishing through
  `jaasctl release` in a real GitHub Actions job to confirm the
  ambient-credential path produces a verifiable bundle end-to-end; confirm
  a pre-existing dev-RSA-signed tag still verifies unchanged.
- **1.3:** `pytest tests/integration/test_yank.py
  tests/unit/test_artifact_status.py -v`; manually exercise
  yank/unyank/get-metadata via `TestClient` or a running server to confirm
  the sidecar file appears/updates correctly on disk.
