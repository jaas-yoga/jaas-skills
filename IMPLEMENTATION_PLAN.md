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

## Phase 1 — Harden the foundation (0–4 weeks) — ✅ ALL THREE ITEMS DONE (2026-09-02)

All of 1.1, 1.2, and 1.3 landed this session, built test-first throughout.
Combined with Phase 2.3 (landed ahead of sequence, see below), Phase 1 of
this roadmap is complete. See each item's own "✅ DONE" section for what
shipped, what deviated from the original plan, and the real bugs TDD
caught before they reached production.

### 1.1 — Frontend test suite (Playwright + component tests) · `jaas-ui` — ✅ DONE (2026-09-02)

**Status: implemented and verified against the real stack.** 10/10
component tests pass (Vitest + RTL), 3/3 E2E tests pass against a real
`jaas-registry` + `jaas-guardrails` backend via `run.sh`, `eslint` clean.
Discovered along the way that `jaas-ui/run.sh` already exists and
orchestrates all three local services — this replaced the plan's original
"hand-roll `jaasctl serve &` in CI" idea with reusing that script directly
in the new CI job.

**Deviation from plan:** no `data-testid`/`aria-label` additions to
production components were needed — every interaction was reachable via
existing accessible roles/labels. `entrypoint` test files ended up as
`draft-workspace.test.tsx`/`publish-dialog.test.tsx` +
`e2e/drafts-workflow.spec.ts` (not `validation-results-panel.test.tsx` —
its behavior is exercised indirectly through `draft-workspace.test.tsx`'s
Validate tests instead of a standalone file, since it's a trivial pure
render with no logic of its own worth isolating).

**Real bugs the tests caught before shipping (not in the original plan,
found via TDD):** (1) the autosave debounce calls `saveDraftFileAction`
with `undefined` as its options argument, not an explicit
`{ syncToGit: false }` — relies on that function's own default parameter;
the plan's assumed call shape was wrong. (2) Driving Monaco from
Playwright naively (select-all + type) silently **appended** new content
instead of replacing it, and multi-line `keyboard.insertText()` still
triggers Monaco's per-Enter auto-indent, corrupting YAML — both fixed and
documented in `jaas-frontend-conventions/SKILL.md` as reusable patterns
for future E2E specs touching the editor.

**Known gap, not fixed:** CI's new `e2e` job needs a `CI_DEV_LOGIN_PASSWORD`
GitHub Actions secret on `jaas-ui` to actually pass — this requires
repo-admin access to configure and was flagged, not set, since it's outside
what a code change can do.

**Original plan text below, for reference — see the deviations above for
what actually shipped.**

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

### 1.2 — Real Sigstore/Cosign signing · `jaas-skills` — ✅ DONE (2026-09-02)

**Status: implemented via TDD, verified against the real `sigstore` library
(v3+, actually installed and used, not stubbed).** 44 new/updated tests
across 8 files, full suite 714/715 pass (the one failure is the
pre-existing perf flake), `ruff` clean, `pip-audit` clean on the new
dependency tree, no new `mypy` errors. Confirmed with the user before
coding: local `jaasctl release` runs with no ambient CI OIDC credential
**hard-fail** with a clear message — no silent dev-RSA fallback.

**Real design correction found during implementation, not in the original
plan:** the plan didn't distinguish `jaasctl release`'s two auth paths
(`--oidc-token` vs `--token`/PAT) when describing "the release path
becomes Sigstore's primary path." Making Sigstore signing mandatory
regardless of auth path would have been incoherent — the **PAT path exists
specifically for CI systems without an ambient OIDC identity**
(non-GitHub-Actions CI), so requiring Sigstore (which needs OIDC) there
contradicts the reason that path exists, and would have broken every
existing PAT-path test and every real non-GitHub-Actions CI user on
upgrade. Fixed: Sigstore signing (and the hard-fail-if-missing check) only
applies to the `--oidc-token` path; `--token` (PAT) releases are
untouched, always dev-RSA-signed server-side exactly as before, regardless
of `sigstore_signing_required`'s setting (that flag only ever rejects a
*missing bundle*, and a PAT-path release never sends one — so enabling it
deployment-wide effectively restricts releases to GitHub-Actions-OIDC
callers, which is flagged as the real, intended consequence of turning it
on, not a bug).

**Second real gap found and fixed, via manual review after the main
implementation was green:** `ArtifactToken` (`artifact/tokens.py`, backing
short-lived artifact download tokens) carried `digest`/`signature` but no
`signature_kind`. With `high_assurance_signature_recheck` enabled, a
Sigstore-signed artifact's download would have tried to verify its Bundle
JSON as an RSA-PSS signature and always failed — a real bug the original
plan's scope didn't anticipate (it only discussed the ingest-time verify
path, not this retrieval-time one). Fixed: `ArtifactToken` and
`ArtifactTokenIssuer.issue()` now carry `signature_kind`;
`download_artifact` dispatches on it, loading a `SigstoreTrustPolicy` via
a `functools.lru_cache`-memoized factory (see below) only when actually
needed. Covered by a new integration test
(`test_high_assurance_recheck_dispatches_to_sigstore_for_a_sigstore_signed_artifact`).

**Third thing worth knowing:** `sigstore.verify.Verifier.production()`
does real network I/O at construction (~2s — fetches Sigstore's
TUF-distributed trust root). It is **never** called at app startup
(`api/app.py::create_app()` doesn't import `artifact/sigstore_trust.py` at
all) and is memoized with `@lru_cache` where it is called
(`load_sigstore_trust_policy`), so this cost is paid at most once per
process, only if a release or high-assurance download actually needs it —
not on every test run, not on every request.

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

**Impacted areas (actual):**
- New: `artifact/sigstore_sign.py` (client-side signing + ambient-credential
  detection), `artifact/sigstore_trust.py` (`SigstoreTrustPolicy` +
  memoized `load_sigstore_trust_policy` factory) — kept as two files, not
  one, mirroring the existing `signing.py`/`trust.py` split. New tests:
  `tests/unit/test_artifact_sigstore.py`,
  `tests/unit/test_artifact_sigstore_sign.py`,
  `tests/unit/test_verify_signature_kind_dispatch.py`.
- Modified: `artifact/verify.py` (`signature_kind`/`sigstore_trust_policy`
  dispatch params, both optional/defaulted), `artifact/publish.py`
  (`external_signature`/`sigstore_trust_policy` params, `signing_key`/
  `trust_policy` now optional with a runtime exactly-one-of check),
  `artifact/tokens.py` (`ArtifactToken.signature_kind` — a gap found
  during review, not in the original plan; see above),
  `validation/models.py` (`ManifestDocument.signature_kind`),
  `index/models.py`/`index/ingest.py` (`IndexEntry.signature_kind`,
  default-to-`"dev-rsa"` on absence), `api/schemas.py` (`ReleaseRequest.
  sigstoreBundle`), `api/release_routes.py` (dispatch + `
  sigstore_signing_required` check), `api/routes.py` (`download_artifact`'s
  high-assurance recheck now signature_kind-aware; `create_artifact_token`
  passes it through), `common/config.py` (`sigstore_signing_required` flag,
  `sigstore_identity_issuer` setting — no separate Fulcio/Rekor URL
  settings needed, `Verifier.production()`/`ClientTrustConfig.production()`
  already encode the standard public-good endpoints), `common/errors.py`
  (new `SIGSTORE_SIGNATURE_REQUIRED` code), `pyproject.toml` (`sigstore>=3.0`
  in base `dependencies`), `schemas/manifest.schema.json` (regenerated —
  `uv run python tools/generate_schemas.py`, required after any
  `ManifestDocument` field change, per `tests/unit/test_schema_drift.py`).
- CLI: `cli.py::cmd_release` signs client-side, but **only on the
  `--oidc-token` path** — see the design-correction note above for why the
  `--token` (PAT) path is untouched. `cmd_publish`'s success message now
  notes "signed with local dev key, not Sigstore."
- CI reference workflow: `examples/ci/github-actions-release.yml` — no new
  secrets, existing `permissions: id-token: write` is sufficient; comment
  added explaining the implicit second (Sigstore-specific) token request.
- **Not touched:** `jaasctl publish`'s signing itself, web-UI draft-publish
  (`api/draft_routes.py`), or anything in `jaas-ui` — those paths keep
  dev-RSA signing unconditionally.

---

### 1.3 — Version deprecation / "yank" mechanism · `jaas-skills` — ✅ DONE (2026-09-02)

**Status: implemented via TDD** (tests written first, red-confirmed, then
made green) — 694/695 repo-wide tests pass (the one failure is the
pre-existing, host-load-sensitive perf test, unrelated to this change and
already documented as flaky in the backend-conventions skill), `ruff`
clean, no new `mypy` errors beyond this repo's pre-existing missing-stub
noise. Not committed yet — reviewed for gaps first (see below), commit
follows this update.

**Design deviation from the original plan, found during implementation:**
the plan called for extending `new_index_update_event()`/`index/events.py`
with a `kind` discriminator to avoid the event-ID collision. Implementation
found that **no live route actually wires an `EventBus` into
`publish_skill()` today** — `release_routes.py`, `draft_routes.py`, and
`cli.py` all call `index.put()` directly after a storage write; the event
bus only exists inside the isolated `test_publish_to_index_sync.py` unit
test (this is exactly Phase 2.4's "wire up the existing event-bus index
sync" gap). So the yank/unyank routes follow the same direct-`index.put()`
pattern as every other publish-adjacent route, and `index/events.py` was
**not** touched — no route calls `new_index_update_event()` for a yank, so
the collision can't fire yet. The collision risk is real but latent; it's
called out as a landmine for whoever picks up Phase 2.4 (also flagged in
the `jaas-backend-conventions` skill now). `index/bootstrap.py` and
`index/consumer.py` were still both made sidecar-aware (see below) so a
yank survives a cold-start restart today, and the consumer path is already
correct for whenever 2.4 wires it in.

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
- **`IndexEntry` field addition:** `status: ArtifactStatus = ArtifactStatus.ACTIVE`
  (an enum, matching the existing `visibility: Visibility` field's
  convention, not a raw `str` as originally planned) — has a default, so
  every existing call site, fixture, and serialized record keeps working
  unchanged. Low risk, same pattern this dataclass already uses for prior
  additive fields.
- **`_require_share_management_access()` ownership lookup changed** from
  `index.get_resolved(skill_id, None)` to `index.get(skill_id,
  list_versions(skill_id)[-1])` — the original would return `None` (and
  trip its own `assert entry is not None`) the moment *every* version of a
  skill was yanked, since `get_resolved` now excludes yanked versions from
  unconstrained resolution. That would have locked a skill's own owner out
  of unyanking their last remaining version. Caught by an explicit
  regression test (`test_yank_status_survives_even_when_every_version_of_the_skill_is_yanked`)
  before it could ship. Functionally equivalent for ownership purposes
  either way — `owner_user`/`owner_tenant` don't vary by version, which is
  the same assumption the original code already made, just via a
  different, now-broken selection path.
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

**Impacted areas (actual):**
- New: `src/jaas_registry/artifact/yank.py` (named `yank.py`, not the
  originally-planned `status.py` — matches the action-oriented naming of
  its siblings `publish.py`/`verify.py`/`trust.py`), `tests/unit/
  test_artifact_yank.py`, `tests/integration/test_yank.py`.
- Modified: `storage/base.py` (`write_object` added to the `Protocol`),
  `storage/local_filesystem.py` + `storage/s3_store.py` (both implement
  it), `storage/keys.py` (new `status_key()`), `index/models.py`
  (`ArtifactStatus` enum + `IndexEntry.status`), `index/bootstrap.py` +
  `index/consumer.py` (sidecar overlay via `artifact.yank.apply_status`),
  `index/store.py` (`get_resolved` exact-pin-vs-filtered logic),
  `api/routes.py` (new `/yank`, `/unyank` routes; generalized
  `_require_share_management_access` to accept `required_permissions`;
  `status` added to the `get_skill_metadata`/`search_skills` response
  mapping), `api/schemas.py` (`YankRequest`/`YankResponse`, `status` field
  on `SkillMetadataResponse`/`SearchResultItem`).
- `index/ingest.py` and `index/events.py` were **not** touched — status
  lives entirely outside the immutable manifest record (no ingest.py
  change needed), and no route calls `new_index_update_event()` for yank
  (see the design-deviation note above).
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

**Status (2026-09-02):** 2.3 and 2.4 done (2.3 landed ahead of sequence
during Phase 1; 2.4 done this session, with a corrected design — see its
section below). 2.1 (SKILL.md/agentskills.io import-export) and 2.2
(`jaasctl search/pull/install`) remain not yet started; per this
document's own process, each gets its own Explore→Plan pass before
implementation begins, since — unlike Phase 1 — they were only scoped
from the roadmap audit, not verified line-by-line against the code yet.

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

### 2.4 — Wire up multi-replica index sync · `jaas-registry` — ✅ DONE (2026-09-02)

**Design deviation from the roadmap wording, found via TDD exploration
before writing any code:** the item as scoped ("wire up the existing
event-bus index sync") turns out not to achieve its own stated goal.
`index/events.py::InMemoryEventBus` is a plain in-process Python list — its
own docstring calls it a stand-in for Kafka/SQS/Pub-Sub. It cannot carry an
event across separate OS processes, which is what "replica" means for a
horizontally-scaled deployment; wiring it into `create_app()` would only
ever synchronize async tasks *within one process*, never actually solving
multi-replica staleness. The codebase already has the right tool for this
job: `index/reconciliation.py::reconcile()` rebuilds an authoritative index
straight from the shared object store (the same code `bootstrap_index()`
uses at cold start, including re-reading each entry's yank-status
sidecar), so it's process-safe by construction with no shared memory or
message transport required. **What actually got built** is a periodic
reconciliation loop, not an event-bus wire-up.

**What we built:** `index/background_sync.py::reconcile_periodically()` —
an `asyncio` loop that reruns `reconcile()` (offloaded to a worker thread
via `asyncio.to_thread`, since `reconcile()`/`bootstrap_index()` are
synchronous blocking I/O) on a fixed interval until a `stop_event` fires.
Wired into `create_app()` via a new FastAPI `lifespan` context manager
(the app had none before), started only if
`FeatureFlags.background_index_reconciliation` is on (default **on**;
additive flag, defaults preserve today's single-replica behavior since
`reconcile()` against an already-authoritative index is a safe no-op), on
`Settings.index_reconciliation_interval_seconds` (default 300s). Also
fixed the Phase 1.3-documented `event_id` collision landmine in
`index/events.py::new_index_update_event()` (now takes `kind: str =
"publish"`, `event_id` includes it) — cheap, correct hygiene fix, done
even though the event bus isn't the live sync mechanism, since it was a
one-line change sitting right next to code this item touched and the
default preserves every existing call site's behavior.

**Does it break anything?** No — `background_index_reconciliation`
defaults to on, but `reconcile()` running against an index that's already
correct is a verified no-op (`test_reconcile_on_already_consistent_index_reports_no_drift`,
pre-existing). Single-replica deployments (today's only real deployment
shape) see zero behavior change beyond a periodic no-op storage listing
every 5 minutes. The event bus/`IndexEventConsumer` are untouched other
than the additive `kind` param.

**What it improves:** A second replica now converges onto a publish or
yank made by another replica within one reconciliation interval, without
needing any message transport between them — closes the actual multi-
replica correctness gap the roadmap named, via a mechanism proven safe by
the existing `reconcile()` test suite rather than a previously-dead code
path being turned on for the first time in production.

**Impacted areas (actual):** new `src/jaas_registry/index/background_sync.py`,
`api/app.py` (`create_app()` gains a `lifespan`), `common/config.py`
(`FeatureFlags.background_index_reconciliation`,
`Settings.index_reconciliation_interval_seconds`), `index/events.py`
(`new_index_update_event()`'s `kind` param). New tests:
`tests/unit/test_index_background_sync.py`,
`tests/integration/test_background_index_sync_app.py`, plus 3 new cases
in `tests/unit/test_events_and_consumer.py` covering the collision fix.
714 → 722 backend tests passing; ruff clean; no new mypy errors (same
pre-existing unrelated baseline). `.claude/skills/jaas-backend-conventions/SKILL.md`
updated with the reconciliation-vs-event-bus rationale and a note that
the event bus remains available as a future upgrade path if reconciliation's
polling latency ever isn't good enough (design.md §3.2 note 6).

**Not touched:** `index/events.py::InMemoryEventBus`/`IndexEventConsumer`
stay exactly as before structurally — real, tested, but still only
exercised by tests, not wired into any live route. `jaasctl serve`
(`cli.py::cmd_serve`) needed no changes; it already calls `create_app()`,
which now starts the background task itself.

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
