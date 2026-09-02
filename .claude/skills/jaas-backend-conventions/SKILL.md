---
name: jaas-backend-conventions
description: Conventions, known gotchas, and repo/git state for the jaas-registry Python/FastAPI backend (src/jaas_registry) — error codes, the file-backed no-database persistence pattern, FastAPI dependency wiring, the visibility/sharing model, test fixtures, and this repo's own commit/CI/push conventions. Use when reading, writing, reviewing, or committing any code under src/jaas_registry or tests/ in this repo.
---

# jaas-registry backend conventions

Stateless, GitOps-driven skill registry. No database anywhere — every store
is JSON files under `settings.policy_dir` or content-addressed blobs under
`settings.storage_root`. The blob/tag store itself is backend-swappable
(`storage/factory.py::build_store()`, `Settings.storage_backend`): `"local"`
(default, `storage/local_filesystem.py`) or `"s3"`
(`storage/s3_store.py`, any S3-compatible endpoint — OCI Object Storage,
MinIO, AWS S3). `policy_dir` (JSON entity stores, signing keys) is always
local disk regardless of `storage_backend` — that setting only affects
published-artifact storage. Read `design.md` and `implementation-plan.md` for
the original 8-phase design; `ui-design.md`/`ui-implementation-plan.md` for
the web UI phases (auth, visibility/sharing, drafts) layered on top later
— those UI docs stay here even though the UI itself now lives in the
sibling `jaas_ui` repo, since they also cover the backend changes built to
support it (see "This repo's boundaries" below).

## This repo's boundaries

This repo is the backend only — no frontend code. The web UI lives in the
independent sibling repo **`jaas_ui`**, reached only over HTTP
(`JAAS_API_URL`); the publish-time guardrails scanning engine lives in the
independent sibling repo/service `jaas-guardrails-catalog` (see the
"Publish-time guardrails" section below). Neither sibling's code is ever
imported here, and this repo's code is never imported there — don't
re-merge that boundary by adding a cross-repo Python import as a
"convenience."

## Error model (`common/errors.py`)

- One `ErrorCode` StrEnum, one `HTTP_STATUS_BY_CODE` dict, one `JaasError`
  exception (`code`, `message`, `details`). Every rejection anywhere in the
  codebase raises `JaasError`, never a bare exception, so the API's global
  error handler always returns the same `{code, message, details}` shape.
- **A code is never reused for a different meaning once shipped** — a new
  failure mode gets a new `ErrorCode` member, even if an existing code's
  HTTP status would "work". Check `common/errors.py` before assuming an
  existing code fits.

## The file-backed store pattern

Every persistence layer (`authn/users.py`, `authn/tenants.py`,
`sharing/grants.py`, `drafts/store.py`, `artifact/trust.py`) follows the same
shape — don't invent a new one:

- One JSON file per entity under `<policy_dir>/<kind>/`.
- **Deterministic IDs where the entity is naturally unique** (e.g.
  `derive_user_id(google_sub)` in `authn/users.py`, personal-tenant id
  derived from user id in `authn/tenants.py`) — this makes find-or-create
  race-free with zero locking, because two concurrent creates compute the
  identical path and converge instead of racing.
- **Compound-key filenames for relations**, e.g. `<tenant_id>__<user_id>.json`
  (`authn/tenants.py`'s `MembershipStore`) or `<skill_id>__<grant_id>.json`
  (`sharing/grants.py`) — enables `list_for_x` via `glob()` instead of
  scanning and parsing every file in the directory.
- **User-supplied file paths need a traversal guard.** `drafts/store.py`'s
  `_safe_file_path` is the template: reject absolute paths, reject `..` in
  `Path(...).parts`, then verify the resolved path is still inside the
  entity's own directory. Any new endpoint that writes a file at a
  caller-supplied relative path must do this — it's a real trust boundary.
- Scanning a whole directory to answer a query is an accepted tradeoff at
  this local-prototype's scale, not an oversight — don't "optimize" it into
  a second index file that then needs to be kept in sync.

## FastAPI wiring (`api/deps.py` + `api/app.py`)

- `api/deps.py`: `def get_x(request: Request) -> X: return request.app.state.x`
  plus `XDep = Annotated[X, Depends(get_x)]`. Route handlers only ever
  depend on the `XDep` alias, never construct `X()` themselves.
- `api/app.py`'s `create_app()` constructs the real default
  (`x or X(settings.policy_dir)`) and assigns `app.state.x`, with `x`
  accepted as an optional constructor param so tests can inject a fake or a
  pre-seeded instance.
- **`app.state.trust_policy` is a fixed snapshot from `create_app()` time.**
  `trust_policy or load_trust_policy(...)` does **not** fall through when
  the snapshot is an empty-but-present `TrustPolicy()` — a non-None object
  is truthy regardless of its contents. Any code path that self-registers a
  signing key and then needs to trust it immediately (draft publish,
  `jaasctl publish`) must call `load_trust_policy(settings.policy_dir)`
  fresh, exactly like `cli.py`'s `cmd_publish` does — never rely on the
  injected `TrustPolicyDep` for that.

## Version status / yank (`artifact/yank.py`, `index/models.py`)

- `IndexEntry.status` (`ArtifactStatus`: `ACTIVE`/`YANKED`) is **not** part
  of the immutable published record — it's never read or written by
  `index/ingest.py`'s `parse_published_record`/`serialize_published_record`.
  It lives in a separate, deliberately-mutable sidecar file
  (`storage/keys.py::status_key()`, alongside the tag's `manifest.json`),
  written via the new `ObjectStore.write_object()` — the one write path in
  that interface that's an unconditional overwrite, unlike
  `write_tag_if_absent`'s immutability guarantee. Don't be tempted to fold
  status into the manifest record "for simplicity" — that would mean
  rewriting an immutable file, which is exactly what this sidecar exists to
  avoid.
- **Two places build an `IndexEntry` from storage and must both overlay the
  sidecar**: `index/bootstrap.py` (cold start) and `index/consumer.py`
  (event-driven incremental apply). Both call
  `artifact.yank.apply_status(entry, read_status(store, skill_id=..., version=...))`
  right after `parse_published_record()`. If you ever add a third place
  that builds an `IndexEntry` from a tag key, it needs this too — check
  `git grep parse_published_record` before assuming you've found them all.
- **`InMemoryIndex.get_resolved()` excludes yanked versions from
  unconstrained/range/alias resolution, but an exact version-string pin
  still resolves a yanked version directly** (PyPI/npm-style yank
  semantics) — implemented by checking `constraint in
  self._entries[skill_id]` (a dict-key hit) *before* filtering, since that
  can only be true for a literal version string, never `"latest"`/
  `"stable"`/a range expression.
- **Phase 2.4 landmine — fixed, not just documented anymore**:
  `index/events.py::new_index_update_event()` now takes a `kind: str =
  "publish"` param and derives `event_id` as `f"{skill_id}@{version}:{kind}"`
  — a yank event and a publish event for the same `(skill_id, version)` no
  longer collide in `IndexEventConsumer.apply()`'s dedup set. Existing call
  sites that omit `kind` are unaffected (`kind` defaults to `"publish"`, same
  `event_id` shape as before this fix). Still true, deliberately: no live
  route emits a yank event through the bus — see the reconciliation note
  below for why that's fine.
- `InMemoryIndex.list_versions()` returns `sorted(self._entries[skill_id])`
  — a **plain lexicographic string sort, not semver-aware**
  (`"10.0.0" < "2.0.0"`). Fine for `_require_share_management_access()`'s
  "grab any version, ownership doesn't vary by version" use, but don't
  reach for `list_versions()[-1]` expecting "the highest semver version" —
  that's what `get_resolved()`/`resolve_version()` are for.
- **Multi-replica index sync (Phase 2.4) is periodic reconciliation, not the
  event bus** — `index/background_sync.py::reconcile_periodically()` reruns
  `index/reconciliation.py::reconcile()` on a timer
  (`Settings.index_reconciliation_interval_seconds`, default 300s), wired
  into `create_app()`'s FastAPI `lifespan` and gated by
  `FeatureFlags.background_index_reconciliation` (default **on**). This
  deviates from the roadmap's literal wording ("wire up the existing
  event-bus index sync") on purpose: `index/events.py::InMemoryEventBus` is
  a plain in-process Python list (its own docstring says so) — it cannot
  carry an event across separate OS processes, which is what "replica"
  means for a horizontally-scaled deployment. Wiring it into `create_app()`
  would only synchronize async tasks within one process and would not
  solve the actual multi-replica problem at all. `reconcile()` already
  rebuilds from the shared object store (same code `bootstrap_index()` uses
  at cold start, including re-reading each entry's yank-status sidecar via
  `apply_status`/`read_status`), so it's process-safe by construction with
  no new transport needed. The event bus (`InMemoryEventBus`,
  `IndexEventConsumer`) stays exactly as before — real, tested, but only
  exercised by tests and never wired into a live route; it remains the
  natural place to plug in a real broker (Kafka/SQS/Pub-Sub) later if
  reconciliation's polling latency (up to one interval) ever isn't good
  enough, per design.md §3.2 note 6. `reconcile()` is a full store listing
  + rebuild on every tick — cheap at today's tested corpus size, revisit
  the interval or move to incremental sync before Phase 4.4's 50k-package
  load test.
- `_require_share_management_access()` (`api/routes.py`) takes a
  `required_permissions: tuple[str, ...] = ("skills:share",)` param now,
  not a hardcoded scope — `/yank` and `/unyank` reuse it with
  `("skills:write",)` instead of inventing a parallel ownership check.
  Reach for this same generalization before writing a new "owner or tenant
  admin" guard anywhere else in this file.

## Visibility & sharing (`sharing/access.py`, `index/models.py`)

- `IndexEntry.visibility` (`public`/`private`) plus `owner_user`/
  `owner_tenant` decide who can see a skill; `sharing/grants.py`'s
  `GrantStore` layers additive per-user/per-tenant ACL entries on top of
  `private` — sharing is never a third visibility value.
- `can_view(entry, caller=..., grants=...)` is evaluated **per request**,
  never baked into the index — revoking a grant takes effect on the very
  next call, no index rebuild.
- `resolve_caller_context(token, settings=...)` is best-effort: a missing,
  expired, or malformed token degrades to `ANONYMOUS`, it never raises.
  Search/metadata endpoints must stay reachable without auth (that's
  pre-existing, intentional behavior) — only endpoints that actually
  require a permission (`AuthorizerDep.check(...)`) should reject a bad
  token outright.
- A caller who can see a public/owned skill but not a private one they lack
  access to gets `SKILL_NOT_FOUND` / `DRAFT_NOT_FOUND` (404), never 403 —
  don't leak whether a private resource exists.

## Publish-time guardrails (`guardrails/`, design.md §4.5)

- **This repo contains no scanning logic and no rule catalog.** Both live
  entirely in the separate [jaas-guardrails-catalog](https://github.com/balakrishna-maduru/jaas-guardrails-catalog)
  repo/service, reached only over HTTP. `guardrails/client.py`'s
  `GuardrailsClient` (Protocol) + `HttpGuardrailsClient` (real impl) is
  the **only** contact point — never add an import from that other repo's
  Python here; that would silently re-merge the two codebases. Locally,
  that service must be running (`run.sh` starts it as a third managed
  process, default port 8028) — see ROLLOUT.md.
- `guardrails/models.py` is a **hand-kept mirror** of that service's
  response shapes (same pattern as the sibling `jaas_ui` repo's
  `src/lib/jaas-api-types.ts` mirroring this app's own schemas) —
  `GuardrailDefinition`,
  `GuardrailFinding`, `GuardrailScanResult`. If that service's `/scan` or
  `/catalog` response shape changes, update this mirror in the same
  change, there is no codegen step.
- `guardrails/policy.py` (tenant policy storage) is the one piece of
  guardrails-related code that legitimately still lives here: which
  *configurable* checks a tenant has opted into is a tenant-administration
  concern tied to this app's own auth/RBAC, not the scanning service's
  job. `GuardrailPolicyStore.put()` silently drops any mandatory id from
  what gets persisted — belt-and-suspenders, since the *service itself*
  also force-runs mandatory checks regardless of what's sent to it.
- `guardrails/custom_rules.py` (`CustomGuardrailRuleStore`) is the other
  piece that legitimately lives here: a tenant's *reusable, named* custom
  rules (as opposed to which platform-catalog checks are enabled). Same
  file-backed convention, ids namespaced `custom:<tenant_id>:<slug>` via
  `make_id()` so they can never collide with a platform id or another
  tenant's rule. This store never validates rule *content* — that's the
  guardrails service's job (`POST /validate-rule`, called from
  `api/tenant_routes.py` before every `put`) — it only owns storage,
  namespacing, and the per-tenant rule-count limit
  (`MAX_RULES_PER_TENANT`). Every create/update/delete goes through
  `common/audit.py`'s `emit_custom_guardrail_change` — these rules execute
  against every future publish they're applied to, so they get the same
  audit trail a publish gets, not just a silent file overwrite.
- `guardrails/skill_config.py` parses a skill package's optional
  `.jaas/guardrails.yaml` (`apply:` a list of catalog or tenant custom
  rule ids; `rules:` up to `MAX_INLINE_RULES` one-off rules scoped to just
  that skill) and `resolve_guardrails_for_skill()` combines it with the
  tenant's baseline `GuardrailPolicy` — this file can only ever *add*
  checks, never remove one the tenant enabled or disable a mandatory
  check (still force-run server-side regardless). Both `cli.py`'s
  `cmd_validate`/`cmd_publish` and `api/draft_routes.py`'s
  `validate_draft`/`publish_draft` call this same resolver — whichever
  front door a skill goes through, its own guardrails config is honored
  identically.
- `artifact/publish.py`'s `publish_skill()` takes `guardrails_client:
  GuardrailsClient | None = None` — same opt-in-via-`None` shape as
  `existing_dependency_graph` right above it in the signature. Real
  callers (`cli.py`, `api/draft_routes.py`) always pass a real client, so
  production publishes are always scanned; passing `None` cleanly skips
  the scan rather than forcing every caller (including unrelated tests)
  to reach a live service. A BLOCK finding raises
  `JaasError(GUARDRAIL_VIOLATION)` before any archive/store write; WARN
  findings never block, they're recorded as `guardrail_warning_ids` on the
  publish audit event.
- `api/deps.py::get_guardrail_catalog` fetches fresh **per request**, not
  once at app startup — a temporary blip in the guardrails service must
  never take the rest of this app down. Only the specific routes that
  call it (draft validate/publish, the two tenant guardrail-policy
  endpoints, `/api/v1/guardrails`) can return
  `503 GUARDRAILS_SERVICE_UNAVAILABLE`; everything else stays up.
- **Tests never execute the real guardrails service's code** — that
  service has its own test suite in its own repo. `tests/fixtures/
  fake_guardrails_client.py`'s `FakeGuardrailsClient` is what every test
  here injects (`create_app(..., guardrails_client=FakeGuardrailsClient(...))`,
  or `publish_skill(..., guardrails_client=...)` directly, or `cli.main(...,
  guardrails_client=...)` — all three call sites accept the same
  override). Each test supplies exactly the `GuardrailScanResult` it wants
  back; there's no regex/detection logic duplicated in this repo's tests.

## Git-native release (`api/release_routes.py`, `authn/repo_links.py`, `authn/ci_credentials.py`)

- `POST /api/v1/skills/release` is a **third** front door to
  `publish_skill()`, alongside the web UI's draft-publish and `jaasctl
  publish`. It exists for CI: a tag push triggers a workflow that calls
  this endpoint with the packaged skill files + the tag that triggered it.
- **`guardrails_client` is never optional on this path** — unlike the
  CLI's local-dev-only `guardrails_client=None` opt-out, every release
  through this endpoint is scanned, no exceptions. If you're touching this
  file, don't add a way to skip that.
- Two mutually exclusive auth paths, resolved in `_resolve_tenant()`:
  `X-Jaas-OIDC-Token` (GitHub Actions OIDC, verified by
  `authn/ci_credentials.py::GitHubOidcVerifier` against GitHub's real
  JWKS — injected via `OidcVerifierDep`/`app.state.oidc_verifier` so tests
  can swap in a fake JWK client instead of hitting the network) or a
  normal `Authorization: Bearer <PAT>` (same auth every other endpoint
  uses — a PAT already carries a `tenant` claim, so no new scope exists
  for this). Either way, the resolved tenant must have a
  `repo_links.py` registration for the skill id being released — that's
  the actual authorization check, not the credential kind.
- A release always cross-checks the git tag against `manifest.yaml`'s own
  `version` field (`RELEASE_VERSION_MISMATCH` on mismatch) — the same
  discipline `npm publish`/`cargo publish` get for free from package
  metadata being the tag, enforced explicitly here since nothing else
  ties the two together.
- **Re-releasing an already-published `(id, version)` is idempotent
  success, not `DUPLICATE_PUBLISH`** — this is the one place in the
  codebase that catches that error and turns it into a 200 (recomputing
  the digest from the same input files rather than reusing a stored one).
  A CI re-run must never be treated as a pipeline failure; everywhere else
  `DUPLICATE_PUBLISH` (409) is correct, human-facing feedback.
- `authn/repo_links.py`'s `RepoLinkStore` enforces a skill id's link is
  globally unique across tenants (`find_any()`), not just unique within
  one — this is the anti-squatting property; a per-tenant-only check
  wouldn't stop a second tenant from registering the same id.
- A `RepoLink` can optionally restrict `release_branches` — empty (the
  default) means no restriction, fully backward compatible with every
  link created before this existed. When non-empty,
  `release_routes.py::_check_release_branch_allowed()` requires a
  resolved branch name: on the OIDC path that's `identity.environment`
  (GitHub's `environment` claim, only present when the workflow job
  declares `environment:` — deliberately the *only* branch signal trusted
  here, since a git tag isn't reliably "on" one branch the way a commit
  on a branch tip is); on the PAT path it's the caller-supplied
  `releaseBranch`, a weaker, unverified claim consistent with PAT being
  the fallback auth path everywhere else in this file. Don't try to
  derive "which branch is this tag on" any other way.
- CLI side: `jaasctl release` (`cli.py::cmd_release`) is a pure HTTP
  client of this endpoint, since a CI runner has no business having
  filesystem access to `storage_root`/the signing key. `jaasctl
  guardrails push` similarly calls the custom-guardrails CRUD API;
  `jaasctl guardrails validate` talks straight to the guardrails
  service's `/validate-rule` (no tenant/auth needed, mirrors how
  `cmd_validate` reaches that service). See
  `examples/ci/github-actions-release.yml` for the reference workflow
  these commands are meant to run inside. (`search`/`pull`/`install` are
  also real HTTP clients now — see the section below.)

## `jaasctl search / pull / install` (Phase 2.2, `cli.py`)

The first `jaasctl` commands built for an end user consuming the registry
(not CI, not an author) — a package-manager-style layer on top of existing
read APIs. No server-side code was touched to add these; `cli.py` only.

- `search` → `GET /api/v1/skills`, auth-optional (`--token` widens results
  to private/shared skills, same as the web UI's search — see "Visibility
  & sharing" above). Prints a flat line per result; no pagination UX
  beyond `--page`/`--page-size` yet.
- `pull`/`install` share `_download_skill_files()`: `POST
  .../artifact-token` then `GET /artifacts/{token}`, extracted via the
  existing `artifact/packaging.py::extract_archive()`. **Deliberately not**
  built on the per-file `GET .../files/{file_path}` endpoint — that one
  UTF-8-decodes with `errors="replace"` (`FileContentResponse`), so it
  would silently corrupt a binary asset; the signed tar is the only
  binary-safe read path for a whole package today.
- **`--token` is required for `pull`/`install`, unconditionally — even for
  a PUBLIC skill.** `create_artifact_token` calls
  `authorizer.check(token=..., ...)`, and the real `JwtAuthorizer`
  (`authz/policy.py`) is deny-by-default with no anonymous branch at all
  (`if not token: raise UNAUTHORIZED`), regardless of the entry's
  visibility. This is a *different* security boundary than
  `search`/`/files`, which gate on `can_view`/visibility, not
  `authorizer.check`. Loosening artifact-token issuance to allow anonymous
  PUBLIC access was considered and explicitly rejected while building this
  — it would be a deliberate security-model change (this file's own
  `authz/policy.py` docstring calls out "no implicit-allow branch" as a
  load-bearing property), not something to fold into a CLI convenience
  feature. If anonymous `pull` of public skills is ever wanted, that's a
  standalone decision for `create_artifact_token`, not an implicit side
  effect of the CLI.
- `install` extracts to `.claude/skills/<skill_id>/` relative to cwd —
  Claude Code's own convention, and the only agent-skill-directory
  convention this codebase knows about (confirmed via search before
  building this: nothing else in `src/` references any such layout).
  There's no lockfile/update tracking on repeat installs — re-running
  `install` just overwrites the directory's contents.
- Test pattern: `tests/integration/test_cli_search_pull_install.py`
  follows `test_cli_release.py`'s established convention — `main([...])`
  in-process, `monkeypatch.setattr("httpx.get"/"httpx.post", ...)`, no
  real server. One extra test in that file routes the same monkeypatched
  `httpx.get`/`post` through a real `TestClient(create_app(...))` instead
  of a hand-typed fake payload — worth doing whenever a CLI test's fake
  response shape is itself an assumption being tested, not just plumbing.

## Sigstore signing (`artifact/sigstore_sign.py`, `artifact/sigstore_trust.py`)

- **Two signature kinds coexist permanently, not just during a
  migration**: `"dev-rsa"` (`artifact/signing.py`/`trust.py`, the original
  in-process RSA stand-in) and `"sigstore"` (real keyless/OIDC-bound
  signing). `IndexEntry.signature_kind`/`ManifestDocument.signature_kind`
  carry which one; absent (pre-existing records) defaults to `"dev-rsa"`
  at `index_entry_from_manifest`, the same pattern this codebase already
  uses for `visibility`. `artifact/verify.py::verify_artifact()` dispatches
  on it — every pre-existing call site that omits `signature_kind` gets
  the identical `"dev-rsa"` behavior it always had.
- **Sigstore signing only happens on `jaasctl release`'s `--oidc-token`
  path, never `--token` (PAT)** — the PAT path exists specifically for CI
  systems *without* an ambient OIDC identity, so requiring Sigstore
  (which needs one) there would be self-contradictory. If you're adding
  anything that touches `cmd_release`'s signing, keep this split; don't
  make Sigstore signing unconditional.
- `Settings.feature_flags.sigstore_signing_required` only rejects a
  release with **no bundle at all** — it doesn't (and can't) force a PAT
  release to become Sigstore-signed. Enabling it deployment-wide is
  equivalent to "GitHub-Actions-OIDC releases only," not "Sigstore or
  bust for everyone."
- **`sigstore.verify.Verifier.production()` does real network I/O at
  construction** (~2s — fetches Sigstore's TUF-distributed trust root).
  Never call it eagerly (`api/app.py::create_app()` never imports
  `sigstore_trust.py` at all, matching how `app.state.trust_policy`
  itself is a cheap empty default, not `load_trust_policy(...)`, at
  startup — see the FastAPI wiring section above). `load_sigstore_trust_policy()`
  is `@lru_cache`d for this reason; call sites (`api/release_routes.py`,
  `api/routes.py::download_artifact`) call it directly rather than
  threading it through `app.state`/DI, since the cache already gives them
  the "construct once" property without that plumbing.
- **`ArtifactToken` (`artifact/tokens.py`) must carry `signature_kind`** —
  a real bug caught late during this feature's own implementation:
  without it, `download_artifact`'s high-assurance recheck
  (`Settings.feature_flags.high_assurance_signature_recheck`) would try to
  verify a Sigstore Bundle as an RSA-PSS signature and always fail. Any
  new code path that reads a signature back out for reverification needs
  to carry and check `signature_kind` the same way — don't assume
  `TrustPolicy`/dev-RSA is the only kind in play.
- Testing this without real network or a real CI OIDC identity: inject a
  fake at the `ArtifactVerifier`/policy boundary (`SigstoreTrustPolicy`
  takes an injectable `verifier`, matching `GuardrailsClient`'s
  real-vs-fake DI pattern), or monkeypatch `artifact/sigstore_sign.py`'s
  own `detect_credential`/`sign_digest_with_sigstore` at their module
  attributes (not deep inside the `sigstore` package) — see
  `tests/integration/test_cli_release.py`'s `_fake_ambient_sigstore_signing()`
  helper. A malformed/garbage Sigstore bundle string is a legitimate,
  cheap thing to test directly (`Bundle.from_json()` raises on it, caught
  and turned into `False`) — no real bundle needed for that path.

## Tests

- `tmp_path` is the standard way to get an isolated store directory for any
  file-backed store test — don't mock the filesystem. For `storage/s3_store.py`,
  the equivalent is `moto`'s `mock_aws()` + a real `boto3.client("s3",
  region_name=...)` against it (`tests/unit/test_storage_s3_store.py`'s
  `s3_client` fixture) — a real client talking to moto's in-process fake,
  not a hand-rolled mock of `S3ObjectStore` itself.
- Use `tests/fixtures/index_entries.make_entry(**overrides)` and
  `tests/fixtures/jwt_tokens.make_token(**overrides)` for test data; don't
  hand-construct `IndexEntry` or sign a JWT manually.
- `tests/performance/test_load.py::test_search_p95_latency_within_slo` is
  genuinely sensitive to host machine load (other processes, IDE language
  servers competing for CPU) — if it fails, re-run it in isolation
  (`uv run pytest tests/performance/test_load.py -q`) a few times before
  concluding it's a real regression, not machine noise.
- **`uv sync` alone does not install dev tooling.** `pytest`/`ruff`/etc. are
  declared under PEP 621 `[project.optional-dependencies].dev`, which plain
  `uv sync` skips. After adding any new dependency, run
  `uv sync --extra dev`, or the dev tools silently vanish from `.venv`.
- **Any `ManifestDocument` field change needs a schema regen**:
  `tests/unit/test_schema_drift.py` diffs the live-generated JSON Schema
  against the checked-in `schemas/manifest.schema.json` and fails if
  they've drifted. Run `uv run python tools/generate_schemas.py` and
  commit the result in the same change — don't hand-edit the schema file.

## Git/GitHub state (check before assuming otherwise)

- Main branch is `main` (not `master`), with `origin` configured
  (`git@github-jaas-skills:jaas-yoga/jaas-skills.git` — note the custom SSH
  host alias `github-jaas-skills`, not the default `github.com`; a plain
  `git@github.com:...` remote won't authenticate the same way). Push/PR/
  issue workflows are usable. This corrects an earlier version of this
  skill that said no remote existed — re-check with `git remote -v`
  yourself if this ever seems stale again, don't propagate it forward from
  memory.
- `gh` CLI is installed and authenticated as `balakrishna-maduru`
  (`repo`/`read:org`/`gist` scopes) — PR/issue commands will work as soon
  as a remote exists.
- No `.github/PULL_REQUEST_TEMPLATE.md` or issue templates exist — `gh pr
  create`/`gh issue create` use whatever title/body you pass.
- Commit style: heredoc commit messages (avoids shell quoting issues), a
  1-2 sentence body focused on *why*, ending with
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` when Claude
  Code authored the change. Always a new commit, never `--amend`, unless
  the user explicitly asks.
- **`.github/workflows/ci.yml` only covers this repo** — checkout, `uv
  sync --extra dev`, `ruff check .`, `pytest -q`, `pip-audit`. It has no
  awareness of the sibling `jaas_ui`/`jaas_guardrail` repos; each of those
  has (or should have) its own independent CI.
- `pyproject.toml`'s `version = "0.1.0"` is the only repo-level version
  marker. **Do not confuse it with the registry's own per-skill SemVer**
  (design.md's versioning of *published skill packages inside* the
  registry) — two unrelated versioning schemes that happen to both use
  SemVer.
