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

**Third thing worth knowing:** `\.Verifier.production()`
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

## Phase 2 — Interoperate with the standard (1–3 months) — ✅ ALL FOUR ITEMS DONE (2026-09-02)

**Status (2026-09-02):** All four items done. 2.3 landed ahead of
sequence during Phase 1; 2.2, 2.4, and 2.1 all done this session, each
with an Explore pass surfacing real judgment calls the roadmap's one-line
descriptions undersold — see their sections below. **Phase 2 is complete.**

### 2.1 — SKILL.md / agentskills.io import & export · `jaas-registry` — ✅ DONE (2026-09-02)

**What we built:** `jaasctl export <skill_id>` and `jaasctl import <path>`
— a bidirectional converter between this registry's manifest.yaml and the
open `agentskills.io` `SKILL.md` format (YAML frontmatter + markdown
body), scoped to backend + CLI only this pass (the `jaas-ui` "export as
SKILL.md"/"import from SKILL.md" buttons are a deliberate follow-up, not
built here — same deferral pattern as Phase 1.3's yank-status UI banner).
`export` reuses Phase 2.2's `_download_skill_files()` to fetch an
already-published skill's real manifest + entrypoint content, then
`artifact/skillmd.py::manifest_to_skillmd()` converts it. `import` is the
reverse and purely local/offline (no server involved) —
`skillmd_to_source_documents()` materializes a normal
`manifest.yaml`+`schema.json`+`permissions.yaml`+`dependencies.yaml`
directory, unchanged input to the existing `jaasctl validate`/`jaasctl
publish` pipeline (proven by an end-to-end test that runs a real imported
package through `jaasctl validate`).

**Design decisions surfaced by researching the actual external spec
(agentskills.io) against the actual internal manifest model — the
roadmap's one-liner undersold how different these two formats are — all
three were confirmed with the user before coding:**
- **v1 scope is single-file skills only.** A real SKILL.md skill often
  ships a `scripts/`/`references/`/`assets/` folder alongside SKILL.md;
  this registry's packaging (`artifact/packaging.py::collect_package_files`)
  only ever bundles exactly 4 known documents + 1 entrypoint file, no
  arbitrary extra files. Extending that to arbitrary bundles was
  explicitly scoped out as separate, larger follow-up work, not silently
  attempted.
- **`jaasctl import` requires explicit `--id`/`--version`/`--owner-team`/
  `--category`/`--runtime` flags — never inferred.** SKILL.md's `name`
  field has no namespace (a bare slug, locally unique at best); this
  registry requires a globally-unique 3+-segment dotted `id`
  (`validation/models.py`'s `ID_PATTERN`). Guessing one from a bare
  `name` risks silently colliding with an unrelated published skill —
  rejected in favor of requiring the author to state it explicitly, same
  reasoning as Phase 1.2's Sigstore identity decision.
- **No jaas-ui surface in this pass** — see "What we built" above.

**Where the two formats structurally diverge (why this is lossy in both
directions, on purpose, not by oversight):**
- SKILL.md has **no** id/version/owner/category/runtime-compatibility/
  permissions/dependencies/digest/signature/visibility concept at all —
  every `IndexEntry` field beyond `name`/`description` has no frontmatter
  equivalent. Export stashes the round-trippable ones (`id`, `version`,
  `category`, `owner.team`, `tags`) under `metadata.jaas-*` string keys
  (SKILL.md's own documented escape hatch for non-standard data) so a
  later re-import can recover them instead of losing them outright —
  proven by a round-trip test. `runtime` becomes a free-text
  `compatibility` field on export (capped at the spec's own 500-char
  limit) but is **not** parsed back out of it on import — free-text
  compatibility strings aren't a safe structured-data source, so
  `--runtime` must be supplied fresh on import instead.
- This registry has **no** freeform-instructions field distinct from
  `description` — SKILL.md's markdown body *is* the actual skill logic.
  The closest bridge: if `manifest.entrypoint` is already a text/markdown
  file (`.md`/`.markdown`/`.txt` — `publish.py`'s own
  `load_source_documents` comment already names `prompt.md`/`SKILL.md` as
  valid entrypoints), its content becomes the SKILL.md body verbatim on
  export, and on import the SKILL.md body is written back as the
  package's own `entrypoint: SKILL.md` file, unchanged. A non-text
  entrypoint (e.g. `executor.py`) has no home in a single SKILL.md file
  in this v1 scope — export still succeeds, but with a synthesized
  description-only body and a printed note that the real program wasn't
  included, never silently.
- `allowed-tools` (SKILL.md, experimental — pre-approved agent tool
  names) and `permissions.yaml` (this registry — declared capability
  scopes like `network:egress`) look similar but aren't the same concept;
  no attempt is made to translate between them in either direction.

**Does it break anything?** No — two new, independent CLI subcommands; no
existing route, schema, or storage format changed. `export` requires
`--token` unconditionally, same reasoning as `pull`/`install` (Phase
2.2's artifact-token auth boundary, not loosened here either).

**What it improves:** Turns a published skill from "usable in this
registry only" into a real `SKILL.md` file any of the ~40 tools reading
that open standard can consume directly, and lets an externally-authored
`SKILL.md` skill become a real, valid, publishable registry package with
one command plus five required flags.

**Impacted areas (actual):** new `src/jaas_registry/artifact/skillmd.py`
(`manifest_to_skillmd`, `parse_skillmd`, `skillmd_to_source_documents`,
`slugify_skill_id`, `SkillMdFormatError`, `ParsedSkillMd`); `cli.py` (new
`export`/`import` subparsers, `cmd_export`/`cmd_import`, reusing Phase
2.2's `_download_skill_files`/`_write_files` helpers) — no server-side
route/schema changes. New tests: `tests/unit/test_artifact_skillmd.py`
(20 tests — export/parse/import + a round-trip test), `tests/integration/
test_cli_export_import.py` (8 tests, including one that runs a real
imported package through `jaasctl validate` end-to-end). 730 → 758
backend tests passing; ruff clean; no new mypy errors.

### 2.2 — `jaasctl search / pull / install` · `jaas-registry` CLI — ✅ DONE (2026-09-02)

**What we built:** Three new CLI subcommands — `jaasctl search`,
`jaasctl pull <skill_id>`, `jaasctl install <skill_id>` — the first
`jaasctl` commands built for an end user browsing/consuming the registry,
rather than CI (`release`) or an author (`publish`/`validate`).
`search` hits `GET /api/v1/skills` (auth-optional, same as the web UI's
search). `pull`/`install` share a `_download_skill_files()` helper: issue
a short-lived artifact token (`POST .../artifact-token`), redeem it for
the signed tar (`GET /artifacts/{token}`), and extract it with the
existing `artifact/packaging.py::extract_archive()` — the same function
`drafts/store.py` and the file-viewer API already use. `pull` extracts to
`--dest` (default `./<skill_id>/`); `install` extracts to
`.claude/skills/<skill_id>/` relative to cwd.

**Design decisions surfaced by an Explore pass before coding (the roadmap's
one-line description undersold two real judgment calls):**
- **Install target directory** — no convention for this existed anywhere
  in the codebase. Resolved with the user: `.claude/skills/<skill_id>/`
  (Claude Code's own convention, matching this repo's own dev tooling) —
  chosen over a bare `--dest`-only design or deferring `install` entirely.
- **Pull's download path had to be the signed tar, not the per-file JSON
  endpoint** — `GET .../files/{file_path}` UTF-8-decodes each file with
  `errors="replace"` (`api/schemas.py`'s `FileContentResponse`), which
  would silently corrupt any binary asset in a package. The tar endpoint
  (`GET /artifacts/{token}`) is binary-safe and was already the right tool.
- **Considered and explicitly rejected**: loosening `create_artifact_token`
  to allow anonymous issuance for PUBLIC-visibility skills, so `pull`
  could work without `--token`. `authz/policy.py`'s `JwtAuthorizer` is
  documented as deny-by-default with "no implicit-allow branch" —
  artifact-token issuance is a distinct, stricter security boundary from
  the visibility-based anonymous access `search`/`/files` already have
  (which gate on `can_view`, not `authorizer.check`). Changing that
  boundary is a deliberate security-model decision, not something to
  slip in as a side effect of a CLI feature — `pull`/`install` require
  `--token` unconditionally instead, matching `release`'s existing
  `--token` precedent.

**Does it break anything?** No — three new, independent subcommands and
one new module-level constant list; no existing subcommand, route, or
schema changed. `--token` is optional for `search` (widens results,
matching the API's own optional-auth behavior) and required (with a
friendly error, not an argparse crash) for `pull`/`install`.

**What it improves:** Every current framework integration was hand-rolled
REST calls against `GET /api/v1/skills`/`/artifacts/{token}`; this gives a
real command-line consumption path, and `install` specifically makes a
published skill usable by Claude Code with one command.

**Impacted areas (actual):** `src/jaas_registry/cli.py` only (new
subparsers, `cmd_search`/`cmd_pull`/`cmd_install`/`_download_skill_files`/
`_print_api_error`/`_write_files`, new `main()` dispatch branches) — no
server-side code touched. New test file
`tests/integration/test_cli_search_pull_install.py` (8 tests: 7 with
monkeypatched `httpx`, following `test_cli_release.py`'s established
pattern, plus one true end-to-end test that routes `httpx.get`/`post`
through a real `TestClient(create_app(...))` to confirm the hand-typed
fake response shapes in the other 7 actually match the real
routes/schemas). 722 → 730 backend tests passing; ruff clean; no new
mypy errors.

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

## Phase 3 — Compete on trust (3–6 months) — ✅ ALL FOUR ITEMS DONE (2026-09-02)

**Status:** 3.1, 3.2, 3.3, and 3.4 all done this session, each preceded
by an Explore pass that found the roadmap's own descriptions undersold,
mismatched, or overstated real scope (see their sections below) — 3.2
shipped a deliberately *narrower* fix than its literal wording implied
(confirmed with the user first, since the wider version would have taken
on real security risk nothing in the codebase justified), and 3.1
shipped both a smaller piece (no new endpoint needed) and a bigger one
(real storage-engineering work the roadmap's one-liner didn't surface)
than its description implied, plus one real product decision confirmed
with the user (usage ranking applies to query-less browsing, not just
query-matched results).

### 3.1 — Usage-based discovery ranking · `jaas-registry` — ✅ DONE (2026-09-02)

**Two scope corrections found via an Explore pass before coding — one
making the item smaller than the roadmap implied, one making it bigger:**
- **Smaller on "what counts as a usage event":** no new endpoint or
  middleware was needed. `POST /skills/{id}/versions/{version}/artifact-
  token` already existed and is already the single hook every real
  download path goes through (`jaasctl pull`/`install`/`export`, per
  Phase 2.2's `_download_skill_files`) — instrumenting its existing
  handler body was simpler than the roadmap's guess of "likely a new API
  endpoint or middleware." (`design.md §7.3` item 2 had separately
  anticipated "emit retrieval events" for audit purposes years earlier
  and it was never built either — this closes that gap as a side effect,
  though usage counting and audit logging remain two separate concerns
  with two separate stores, not merged into one.)
- **Bigger on storage engineering:** `design.md §9.2`'s own documented
  capacity assumption is ~80 RPS average on that exact endpoint — roughly
  6.9M events/day. The audit log's one-file-append-per-event pattern
  (Phase 3.3's `FileAuditSink`) would be the wrong model to copy at that
  volume; this needed a genuinely different storage shape (in-process
  aggregation + periodic merged flush) with no precedent elsewhere in
  this codebase, not just "a new usage-tracking store" as a peer of
  `GrantStore`.

**A real product decision, confirmed with the user before building:**
today, browsing with no search query sorts purely alphabetically by id —
there's no relevance signal in that case at all. Usage ranking is most
valuable exactly there, but it changes the *default* Browse order for
every caller, not just an edge case within query-matched results.
Confirmed: apply the usage signal everywhere, including query-less
browsing — matches the roadmap's own stated goal ("surfaces the curation
signal") most directly, since today's alphabetical fallback was never a
deliberate ranking choice, just what's left with nothing to score
against.

**What we built:**
- `index/usage.py::UsageCounter` — an in-process, per-replica counter
  (`record()`/`drain()`, lock-guarded, O(1), zero I/O on the hot
  artifact-token-issuance path). `flush_usage_counts()` merges a
  replica's drained delta additively into one shared durable
  `usage_counts.json` under a new `Settings.usage_dir`; `flush_usage_
  counts_periodically()` runs that on a timer (`Settings.usage_flush_
  interval_seconds`, default 60s) — same "periodic, eventually
  consistent, safe by construction" shape Phase 2.4's
  `reconcile_periodically()` established for multi-replica index sync,
  reused here because usage data tolerates staleness (and even a rare
  lost increment under a concurrent-flush race) far better than index or
  grant correctness does. `usage_score()` log-scales a raw count into
  roughly `[0, 1]` with diminishing returns, so one viral skill can't
  swamp ranking regardless of query relevance.
- `index/query.py::search()` gains `usage_counts: dict[str, int] | None
  = None` (default preserves every existing caller's exact behavior) and
  a new `WEIGHT_USAGE = 0.3` (comparable to `WEIGHT_CATEGORY`,
  deliberately below `WEIGHT_EXACT_ID`/`WEIGHT_NAME` — a supporting
  signal, not a dominant one). Applied *after* the query-match filter
  (so a popular-but-irrelevant skill can never leak into a specific
  search), but unconditionally including the no-query path, per the
  product decision above.
- `FeatureFlags.usage_ranking_enabled` (default **off**) gates only the
  *read* side — `api/routes.py::search_skills` only calls `read_usage_
  counts()` and passes real data into `search()` when it's on.
  Collection (recording + the periodic flush) always runs regardless of
  the flag, so real data is already warm the moment an operator turns
  ranking on, rather than starting from zero.

**Does it break anything?** No — verified with `usage_counts=None`
byte-identical-to-before regression tests, a dedicated test proving a
high usage count can never surface a non-matching result for a specific
query, and an end-to-end integration test suite that issues real
artifact-tokens over real HTTP requests and confirms search ordering
only changes when the flag is on. `test_artifact_token_p95_latency_
within_slo` (an existing perf test that exercises the new `record()`
call unconditionally) still passes — the new hot-path work is genuinely
O(1)/in-memory.

**What it improves:** Surfaces the curation signal the roadmap's own
cited research shows matters (16.2-point measured task-success gap for
curated results) — and does so specifically for query-less Browse, which
had zero relevance signal at all before this.

**Impacted areas (actual):** new `src/jaas_registry/index/usage.py`;
`index/query.py` (`WEIGHT_USAGE`, `usage_counts` param); `common/config.py`
(`usage_dir`, `usage_flush_interval_seconds`, `FeatureFlags.usage_
ranking_enabled`); `api/app.py` (`UsageCounter` construction + periodic
flush task, always-on, wired into the existing lifespan alongside Phase
2.4's reconciliation task); `api/deps.py` (`UsageCounterDep`);
`api/routes.py` (`create_artifact_token` records; `search_skills` reads,
flag-gated). New tests: `tests/unit/test_index_usage.py` (14 tests),
5 new cases in `tests/unit/test_query.py`, `tests/integration/
test_usage_ranking.py` (4 end-to-end HTTP tests). 794 → 817 backend
tests passing; ruff clean; no new mypy errors.

**This completes Phase 3 in full — all four items (3.1–3.4) done.**

### 3.2 — Grant-lookup caching for sharing at scale · `jaas-registry` — ✅ DONE (2026-09-02)

**Design correction found via an Explore pass before coding — the
roadmap's "cache layer... at scale" framing overstated what the actual
cited source justifies, and a wider fix was rejected on purpose:**
`ui-implementation-plan.md`'s risk register (item 2) — the exact
document the roadmap cites — specifies **request-scoped memoization**
("cache per-user visible-tenant-id/grant sets for the request's
lifetime") as its designed mitigation, not a cross-request/process-
lifetime cache. That distinction matters: a cross-request cache is the
*only* shape that carries the "wrongly allow access after a revoked
grant" security risk the roadmap warns about, since it would outlive the
request that created it. Nothing in the codebase justifies taking on
that risk — no grant-count scale target exists anywhere (`design.md`'s
own §9.2 capacity table has one for skills/query-throughput/artifact-
tokens, but not grants), and the register's own honest note already
records that the *measured* problem (N `GrantStore.list_for_skill()` file
reads, one per non-public search candidate, per request) was already
partially absorbed by an earlier, cheaper mitigation (filter reordering
+ a `Visibility.PUBLIC` fast-path, moving the budget from 150ms to
160ms — a 10ms regression already tolerated, not an active SLO breach).
Confirmed with the user before building the narrower, originally-
designed fix instead of the wider one the roadmap's paraphrase implied.

**What we built:** `sharing/access.py::visible_skill_ids_via_grants()` —
computes the full set of skill ids a caller can see via an explicit
grant (their own + their active tenant's) in exactly two
`GrantStore.list_for_grantee()` calls, regardless of how many search
candidates there are. `index/query.py::search()` calls this **at most
once per request**, lazily (only if a non-public candidate is actually
reached — an all-public result set pays nothing extra), and threads the
precomputed set through every `can_view()` call in its filtering loop via
a new `_visible_skill_ids` parameter. This replaces what was previously
one `grants.list_for_skill()` file read *per non-public candidate* with
a fixed cost of two reads *per request*. `can_view()`'s existing
single-entry callers (`get_skill_metadata`, `_require_viewable_entry`,
draft fork-from-existing) are completely unaffected — they never pass
`_visible_skill_ids`, so they fall through to the exact
`grants.list_for_skill(entry.id)` path that already existed, unchanged.
The cache **dies with the request** (it's a local variable in one
`search()` call) — there is no invalidation story to design because
there is nothing that outlives a single request to invalidate.

**Does it break anything?** No — verified with a dedicated regression
test asserting identical search results before/after (same skills
visible to the same callers via user grants, tenant grants, ownership,
and public visibility), plus a new test asserting `GrantStore` call
count stays at 0 `list_for_skill` calls (down from one-per-candidate)
across 25 shared candidate skills in a single request. The pre-existing
`test_revoking_a_grant_immediately_removes_visibility` test (a *direct*
`can_view()` call, not through `search()`) still passes unchanged,
confirming revocation still takes effect immediately for every call path
that isn't the new request-scoped one — and the request-scoped path
can't go stale across requests by construction, since nothing persists
between them.

**What it improves:** Closes the risk register's own acknowledged gap
("the caching half of this mitigation was not built") for the actual
problem it measured, with zero new invalidation-correctness surface
area. If real grant/tenant counts ever do grow enough to matter, the
register's own suggested next step — a denormalized "visible to" field
on the index entry, eliminating the grant-store round trip from the
search hot path entirely — remains the documented path forward; this
item doesn't block it or need un-doing to get there.

**Impacted areas (actual):** `src/jaas_registry/sharing/access.py`
(new `visible_skill_ids_via_grants()`, `can_view()` gains an internal
`_visible_skill_ids` parameter), `src/jaas_registry/index/query.py`
(`search()` computes and threads it through its filtering loop).
`api/routes.py`/`GrantStore` itself/`_require_share_management_access`
— **not touched**, contrary to the roadmap's preliminary guess; those
are the cold-path share-management routes, not the hot path this item
actually addresses. New tests in `tests/unit/test_query.py`: a missing
tenant-grant-visibility case the existing suite hadn't covered, plus a
`TestGrantLookupIsRequestScopedNotPerCandidate` class (call-count
assertion + result-parity assertion). 791 → 794 backend tests passing;
ruff clean; no new mypy errors.

### 3.3 — Governance surface: audit export, identity fields, EU AI Act mapping · `jaas-registry` — ✅ DONE (2026-09-02)

**Design deviation found via an Explore pass before coding:** "add an
audit-export endpoint" undersold real scope — no durable, queryable audit
store existed anywhere. `StructuredLogAuditSink` only ever printed each
event as JSON to stdout; nothing was persisted, so there was no data to
actually export. Three scope decisions were resolved with the user before
implementing: (1) build real file-backed audit persistence now, not defer
it; (2) also close the pre-existing audit *coverage* gap — yank/unyank and
share-grant create/revoke were never audited at all, unlike publish/
guardrail-rule-changes/GitHub-connections; (3) reuse the existing
`owner_team` field for "owning team" rather than adding a distinct,
competing governance-owner field.

**What we built, in three stages:**
- **Durable audit persistence**: `common/audit_store.py::FileAuditSink` —
  a drop-in `AuditSink` implementation that both prints (same JSON shape
  as before, nothing that tails process logs loses that output) *and*
  appends one JSON line per event to `Settings.audit_dir/audit.jsonl`
  (new `audit_dir` setting, same file-backed convention as
  `storage_root`/`policy_dir`). Replaced `StructuredLogAuditSink()` at
  every production call site (`cli.py::cmd_publish`, `release_routes.py`,
  `draft_routes.py`, `tenant_routes.py` ×2, `github_routes.py` ×4) —
  **except** `index/demo_seed.py`, deliberately left print-only, since
  its synthetic seed-data publishes on every fresh checkout would
  otherwise pollute a real audit export with fake events.
- **New audit coverage**: `common/audit.py` gains `YankAuditEvent`/
  `ShareGrantAuditEvent` (+ factory functions, `AuditSink` Protocol
  methods, `InMemoryAuditSink`/`StructuredLogAuditSink`/`FileAuditSink`
  implementations). `_set_version_status` (yank/unyank) and
  `create_share`/`revoke_share` (`api/routes.py`) now emit these.
- **Governance record**: `artifact/governance.py` — same mutable-sidecar
  pattern as `artifact/yank.py` (`ObjectStore.write_object`, overlaid
  post-hoc by `index/bootstrap.py`/`index/consumer.py`), but keyed by
  `skill_id` alone, not `skill_id`+`version` — a governance record is
  shared across every version of a skill, since business purpose doesn't
  vary release to release. Three new `IndexEntry` fields
  (`business_purpose`, `systems_accessed`, `governance_review_date`, all
  additive/defaulted). New `PUT /api/v1/skills/{id}/governance` route
  (`api/routes.py`), gated by a new `skills:governance` permission scope
  — deliberately distinct from `skills:write`/`skills:share`, since this
  is a compliance concern, not a publish or sharing action. Exposed on
  `SkillMetadataResponse`, not `SearchResultItem` — same precedent as
  every other provenance/governance-style field.
- **Audit export**: `GET /api/v1/tenants/{id}/audit-export`
  (`api/tenant_routes.py`), tenant-admin-only (reuses the existing
  `_require_admin` guard). Scoping is the interesting part:
  `CustomGuardrailRuleAuditEvent`/`GitHubConnectionAuditEvent` already
  carry `tenant_id` directly; `PublishAuditEvent`/`YankAuditEvent`/
  `ShareGrantAuditEvent` don't, so those are scoped by looking up the
  referenced skill's *current* `owner_tenant` in the index instead — a
  lookup failure excludes the record rather than including it, so it can
  never leak cross-tenant.

**Does it break anything?** No — every new field is additive/defaulted
(`IndexEntry`, `SkillMetadataResponse`); every new route is new surface,
not a change to an existing one; `FileAuditSink`'s printed output is
byte-identical in shape to `StructuredLogAuditSink`'s. One broad but
contained test-infrastructure fix was needed: `FileAuditSink` being a
*real* file writer (unlike its print-only predecessor) meant every test
fixture across the suite that constructs `Settings(...)` without
mentioning `audit_dir` would otherwise share one real, unisolated
`.local_registry/audit/` path relative to wherever pytest runs. Fixed
with one global `autouse` fixture in `tests/conftest.py`
(`_isolated_audit_dir`) that sets `JAAS_AUDIT_DIR` per test —
pydantic-settings reads env vars for any `Settings(...)` field not
explicitly passed as a constructor kwarg, so this isolates every
existing fixture without editing each one individually.

**What it improves:** Answers the specific governance fields regulators/
enterprise buyers are already asking for (CSA Agentic Trust Framework;
EU AI Act high-risk obligations from August 2026), and — going beyond the
roadmap's literal scope — closes a real security-relevant audit-coverage
gap (yank and sharing-grant changes were previously invisible to any
audit trail at all) discovered while investigating this item, not
silently left as-is.

**Impacted areas (actual):** new `src/jaas_registry/artifact/governance.py`,
`src/jaas_registry/common/audit_store.py`; modified `common/audit.py`
(new event types), `common/config.py` (`audit_dir`), `index/models.py`
(3 new `IndexEntry` fields), `index/bootstrap.py`/`index/consumer.py`
(governance overlay), `storage/keys.py` (`governance_key`), `api/routes.py`
(yank/share-grant audit emission, new governance route), `api/schemas.py`
(`GovernanceUpdateRequest`/`GovernanceResponse`, 3 new
`SkillMetadataResponse` fields), `api/tenant_routes.py` (audit-export
route, `FileAuditSink` swap), `api/github_routes.py`/`api/release_routes.py`/
`api/draft_routes.py`/`cli.py` (`FileAuditSink` swap), `tests/conftest.py`
(global audit-dir isolation), `tests/integration/test_cli.py` (isolation
fixture updated). New tests: `tests/unit/test_audit_events_yank_and_share.py`,
`tests/unit/test_audit_store.py`, `tests/unit/test_artifact_governance.py`,
`tests/integration/test_audit_trail.py`, `tests/integration/test_governance_endpoint.py`,
`tests/integration/test_audit_export_endpoint.py`. 758 → 786 backend
tests passing; ruff clean; no new mypy errors.

### 3.4 — Ship the missing UI surfaces · `jaas-ui` — ✅ DONE (2026-09-02)

**Reality check found via an Explore pass across both repos before
building anything — 3 of the roadmap's 4 named sub-items didn't match
the actual code:**
- **Published-file viewer**: already fully built
  (`skill-files-viewer.tsx`, wired into the skill detail page with a
  Monaco read-only editor and a source-repo tab) — the roadmap's "none
  has frontend today" was simply wrong. Nothing built here; would have
  been pure duplication.
- **Cross-tenant sharing audit page**: didn't map to one clean backend
  surface. Split into (a) `GrantStore.list_for_grantee()` — real,
  useful, but never exposed by any route — and (b) Phase 3.3's generic
  multi-event-type tenant audit-export, unrelated to sharing
  specifically and out of this pass's agreed scope (no UI built for it).
- **Share/validation notifications**: no notification concept exists
  anywhere in the backend (no email/SSE/websocket/inbox) — same kind of
  roadmap-description-bigger-than-reality gap as Phase 3.3's "audit
  export." Not built; "validation" already has a real UI as inline
  panels in the draft workspace, and "share" is covered by the
  richer "shared with me" work below instead of an invented
  notification system.
- **Yank-status warning banner**: confirmed exactly as described —
  backend-ready (`status` on `SkillMetadataResponse`/`SearchResultItem`
  since Phase 1.3), frontend types never updated to read it, deliberately
  deferred per Phase 1.3's own note. The one sub-item that needed no
  rescoping.

Two more real, adjacent gaps were found and folded in with the user's
sign-off: the Phase 3.3 governance fields were also backend-ready and
silently unrendered (same page, same staleness pattern as yank status),
and `jaas-api-types.ts` was stale — missing `status` on both response
types and all three governance fields entirely.

**What we built:**
- **`GET /shares/received`** (`jaas-skills/api/routes.py`) — new route
  exposing the previously-dead `list_for_grantee()`, enriched with
  skill name/category. Requires sign-in, matches grants made to the
  caller directly *and* to their active tenant.
- **`YankStatusBanner`/`GovernanceCard`** (`jaas-ui/components/skills/`)
  — both render `null` for the common case (active status, no governance
  record), wired into the skill detail page.
- **`/skills?visibility=shared-with-me` now fetches real grant data** —
  jaas-ui already had a "Shared with Me" nav link and filter chip, using
  a clever client-side inference over search results (an already-visible
  private item neither owned by me nor my tenant must have arrived via a
  grant). That inference logically still holds, but can't show *who*
  shared it or *when* (`SearchResultItem` carries no grant metadata) —
  replaced with a real fetch against the new endpoint for that one
  filter value, rendering a dedicated table (name/category/permission/
  shared-by/shared-at). Every other filter is untouched.
- **`jaas-api-types.ts` updated**: `status` added to both response
  types, `businessPurpose`/`systemsAccessed`/`governanceReviewDate`
  added to `SkillMetadataResponse`, new `ReceivedShareResponse` type.

**A real backend bug found only by testing against the actual running
stack, not just the test suite:** `PUT /skills/{id}/governance`'s
`skills:governance` permission scope was defined and used to build the
route (Phase 3.3), fully covered by integration tests using hand-minted
JWTs — but never added to `authn/service.py`'s `_MEMBER_SCOPES`, so no
real login-minted token could ever carry it. Every test passed because
`tests/fixtures/jwt_tokens.py::make_token()` accepts any scope string
with no cross-check against what a real sign-in issues. Caught by
starting the real local stack (`./run.sh`), signing in for real, and
finding an empty/rejected response where real data should have appeared
— fixed in `_MEMBER_SCOPES`, with a full manual verification pass after
(yank banner, governance card, and the shared-with-me table all
confirmed rendering correctly against real API responses via a scripted
Playwright session, screenshotted).

**Does it break anything?** No — one new backend route, three new/
modified frontend components, one branch added to an existing page's
data-fetching (the other filter values' code path is byte-for-byte
unchanged), and a permission-scope fix that only *adds* what a member
token can do, never removes anything.

**Impacted areas (actual):** `jaas-skills`: `api/schemas.py`
(`ReceivedShareResponse`), `api/routes.py` (new route),
`authn/service.py` (`_MEMBER_SCOPES` fix),
`tests/integration/test_shares_received_endpoint.py`,
`tests/unit/test_authn_service.py` (scope assertion added). `jaas-ui`:
`src/lib/jaas-api-types.ts`, `src/lib/skills-api.ts`,
`src/lib/visibility-filter.ts`, `src/app/(app)/skills/page.tsx`,
`src/app/(app)/skills/[id]/versions/[version]/page.tsx`, new
`src/components/skills/yank-status-banner.tsx`+test, new
`src/components/skills/governance-card.tsx`+test. 786 → 791 backend
tests passing; jaas-ui: 10 → 15 frontend tests passing, lint/build
clean. Both repos' `SKILL.md` conventions files updated.

---

## Phase 4 — Scale the ecosystem (6–12 months)

**Status:** 4.1 and 4.4 done this session (2026-09-02) — see below. 4.2,
4.3, 4.5 not started; each needs its own dedicated Explore→Plan pass
before coding (4.2 and 4.3 explicitly so, per their sections below).

### 4.1 — Framework SDKs (LangGraph, CrewAI, AutoGen) · new packages — ✅ DONE (2026-09-02)

**Two scoping decisions confirmed with the user before building, since
the roadmap's wording was ambiguous on both:**
- **Location:** the roadmap says "new packages"/"entirely new repos" —
  ambiguous between real standalone GitHub repos and packages inside this
  repo. Built as four independent packages under a new `sdks/` directory
  in this repo (not a uv workspace — each has its own `pyproject.toml`
  and `.venv`, wired together via `[tool.uv.sources]` path deps), not new
  repos. Easy to split into standalone repos later once stable enough to
  publish to PyPI independently; avoided the overhead/commitment of real
  `gh repo create` calls for a first cut.
- **Framework dependencies:** "thin client... per each framework's tool
  conventions" only means something if the adapters' output is genuinely
  usable by each framework's real runtime, not just shaped like it should
  be. Confirmed: install `langgraph`/`crewai`/`autogen-core` (etc.) for
  real, and validate against real framework classes (`langchain_core.
  tools.BaseTool`, `crewai.tools.BaseTool`, `autogen_core.tools.
  FunctionTool`) and real tool-container construction (`langgraph.
  prebuilt.ToolNode`, a real `crewai.Agent`, a real `autogen_agentchat.
  agents.AssistantAgent`), not mocks.

**What we built — `sdks/`, four packages:**
- **`jaas-client`** — the shared core. A thin, standalone `httpx`+`pyyaml`
  client (`JaasRegistryClient`) reimplementing the exact request sequence
  `jaasctl pull`/`install` already use (`cli.py::_download_skill_files`:
  artifact-token → redeem → extract), but as typed, importable, non-CLI
  code (`errors.py`'s `JaasApiError`/`JaasNotFoundError`/`JaasAuthError`
  hierarchy, not print-and-return-`None`). Archive extraction is a
  from-scratch stdlib-`tarfile` reimplementation, not an import of
  `artifact/packaging.py`, so this package never depends on the full
  `jaas_registry` backend at runtime (only at test time, as an editable
  path dev-dependency, for real end-to-end interop tests against a real
  `create_app()` instance). `search()`, `get_metadata()`, `pull()`, and
  `get_entrypoint_content()` (fetches a skill's packaged entrypoint file
  — its instructions, typically a SKILL.md — the one method with real
  product judgment behind it: see below). 19 tests (13 unit, against
  `httpx.MockTransport`; 6 real end-to-end, against a real in-process
  `jaas_registry` app).
- **`jaas-langgraph` / `jaas-crewai` / `jaas-autogen`** — three thin
  adapters, same shape: `build_jaas_tools(client) -> list[<framework's
  tool type>]`, exactly two tools each (`search_skills`, `get_skill`),
  differing only in each framework's own tool-wrapping convention
  (LangChain's `@tool` → `BaseTool`, CrewAI's `@tool` → `BaseTool`,
  AutoGen's `FunctionTool(func, description=..., name=...)`). Each takes
  a structurally-typed `_JaasClientLike` `Protocol`, not a concrete import
  of `JaasRegistryClient`, keeping every adapter decoupled and separately
  testable. 8 tests each (4-5 unit against a hand-rolled fake client; 3-4
  real-interop against the real framework package AND a real
  `jaas_registry` app). 43 SDK tests total, all green.
- **A real product decision behind the two-tool shape:** a "skill" in
  this registry is instructional content (an entrypoint file, typically a
  SKILL.md), not a directly invokable function — so the adapters expose
  *discovery* (search) and *loading instructions* (get_skill), never "run
  the skill" as if it were an RPC call. Keeps every framework adapter to
  exactly the same two capabilities, translated three different ways.

**A real bug found and fixed during this item (documented in the new
`jaas-sdk-conventions` SKILL.md, not just here):** `jaas-client`'s own
real-API test extracts FastAPI `TestClient`'s internal `._transport` and
wraps it in a plain `httpx.Client` for a fast in-process test — works
fine there. It silently breaks once `httpx2` is present anywhere in the
same venv (confirmed: `langgraph`/`langchain-core` pull it in
transitively via `langsmith`) — `starlette.testclient` auto-detects
`httpx2` and switches `TestClient`'s transport to an incompatible one,
failing with a confusing low-level `assert isinstance(response.stream,
SyncByteStream)` error with no obvious connection to the real cause.
Fixed by running the real app on a real localhost port via
`uvicorn.Server` in a background thread (`sdks/*/tests/_live_server.py`,
one copy per package) instead of extracting `TestClient`'s transport —
used in all three framework adapters' real-interop tests.

**Does it break anything?** No — entirely new, independent packages; zero
changes to `src/jaas_registry` or `jaas-ui`.
**What it improves:** Replaces "hand-write REST calls" with `pip install
jaas-langgraph` (etc.) for the three frameworks the roadmap named.
**Impacted areas (actual):** new `sdks/jaas-client/`, `sdks/jaas-
langgraph/`, `sdks/jaas-crewai/`, `sdks/jaas-autogen/` (each with its own
`pyproject.toml`, `src/`, `tests/`, `README.md`); new `.claude/skills/
jaas-sdk-conventions/SKILL.md`. Nothing under `src/jaas_registry` or
`jaas-ui` touched.

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

### 4.4 — Load-test to the stated 50,000-package target · `jaas-registry` — ✅ DONE (2026-09-02)

**What we tested, and what we found — the target holds for the pieces that
carry real per-request cost; one real, previously-undocumented
architectural risk was found and is flagged, not fixed, below:**

- **`index/query.py::search()` at a real (not extrapolated) 50,000-entry
  corpus** — measured directly, isolating the algorithm itself from
  HTTP/tracing/concurrency overhead (those are already covered at 2,000
  entries by `tests/performance/test_load.py`): query-matched search
  ~60-100ms, query-less browse ~85-130ms, both comfortably inside
  design.md §9.1's 160ms p95 budget. **The 50k target holds** — the
  roadmap's own worry ("the in-memory model may not hold 50k entries
  comfortably") turned out not to be the case for the search algorithm
  itself, contrary to what reading `query.py`'s O(n)-unindexed-scan
  in isolation would suggest.
- **`bootstrap_index()` at a real 50,000-entry corpus** — `tests/
  performance/test_bootstrap_load.py` already asserted this via
  extrapolation from a 5,000-skill sample; this investigation actually ran
  the full 50,000 for real once to check the extrapolation's honesty:
  ~16.6s, matching the extrapolated prediction closely and landing
  comfortably inside the 120s budget (design.md §9.1.4). The extrapolation
  approach that file already used is confirmed sound, not just assumed so.
- **`index/usage.py::flush_usage_counts()` (Phase 3.1) at 50,000 tracked
  skills** — a full read-modify-write of `usage_counts.json` on every
  flush (not append-only). Measured directly: ~10-14ms per flush at 50k,
  negligible against the default 60s flush interval. Holds fine.
- **One real, new finding: `index/reconciliation.py::reconcile()` under
  concurrent request load, at 50,000 entries.** `common/config.py`'s
  `background_index_reconciliation` flag (**default: on**, every 300s)
  explicitly deferred this exact question to this item ("revisit the
  default once the roadmap's 50k-package scale target is load-tested").
  `reconcile()` alone, uncontended, is linear and fine (~16s at 50k,
  comfortably inside the 300s interval — `tests/performance/
  test_reconcile_at_target_scale.py` asserts this, extrapolated from a
  5,000-skill sample the same way bootstrap's test does). But `api/
  app.py` runs it via `asyncio.to_thread` specifically so it doesn't block
  the event loop — that keeps requests being *accepted*, but reconcile's
  ~16s of CPU-bound work (parsing/validating every stored record, then
  hashing every entry twice for the before/after checksum) still competes
  for the GIL with concurrent request-handling threads. An ad hoc manual
  measurement during this investigation ran concurrent `search()` calls
  alongside one 50k-scale `reconcile()` call: wall-clock went from ~16s
  (reconcile alone) to **over 3.5 minutes** before being deliberately
  stopped — a severe, order-of-magnitude degradation to concurrent
  request latency for the duration of every reconcile cycle, not machine
  noise. **This is real production-relevant risk at 50k scale with
  today's default settings, and it is not fixed here** — reproducing it as
  a stable, fast-enough-for-CI automated regression test, and deciding on
  a fix (raise the interval default; move reconciliation off the GIL
  entirely via multiprocessing; make it incremental instead of a full
  rescan; something else), is flagged as a follow-up decision, not
  something this load-testing item should resolve unilaterally.
- **Also newly noted, out of this item's corpus-size axis (a
  grant-count/tenant-count axis instead, already flagged as a known risk
  by Phase 3.2's own investigation):** `sharing/grants.py::list_for_grantee`
  is a full glob-scan of every grant file — untouched here, not a
  size-of-catalog concern.

**Small, safe, in-scope fix shipped alongside the finding above:**
`index/store.py::InMemoryIndex.all_ids()` re-sorted the full id set on
every call — a real, avoidable `O(n log n)` cost paid on every single
`search()` request even though the id set only changes on `put()`. Now
cached, invalidated on `put()`, returning a fresh copy each call (so a
caller mutating the returned list can't corrupt the cache). Verified this
doesn't change any observable ordering/behavior (`tests/unit/
test_index_store.py`'s existing + two new invariant tests) — a genuinely
minor win at measured 50k scale (the id-sort was never the dominant cost;
the per-candidate scan and final score-sort dominate), kept because it's
free and correct, not because it moved the needle much on its own.

**Breaking-change risk:** None realized — testing only; the `all_ids()`
caching change is behavior-preserving (verified).
**Improves:** Validates the 50k target holds for search/bootstrap/usage-
flush; surfaces a real, previously-undocumented reconciliation risk at
that scale before it would have been found in production.
**Impacted areas (actual):** new `tests/performance/
test_search_at_target_scale.py`, `tests/performance/
test_reconcile_at_target_scale.py`; `index/store.py` (`all_ids()`
caching); `tests/unit/test_index_store.py` (2 new invariant tests). 817 →
821 backend tests passing; ruff clean; no new mypy errors.
**Follow-up decision needed (not resolved here):** how to mitigate the
reconcile-vs-concurrent-request GIL contention at 50k scale — raised with
the user rather than picked unilaterally, since it's a real production
default (`background_index_reconciliation=True`) with a genuine
availability/latency trade-off either way.

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
