---
name: jaas-backend-conventions
description: Conventions, known gotchas, and repo/git state for the jaas-registry Python/FastAPI backend (src/jaas_registry) — error codes, the file-backed no-database persistence pattern, FastAPI dependency wiring, the visibility/sharing model, test fixtures, and this repo's own commit/CI/push conventions. Use when reading, writing, reviewing, or committing any code under src/jaas_registry or tests/ in this repo.
---

# jaas-registry backend conventions

Stateless, GitOps-driven skill registry. No database anywhere — every store
is JSON files under `settings.policy_dir` or content-addressed blobs under
`settings.storage_root`. Read `design.md` and `implementation-plan.md` for
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
  client of this endpoint — it's the *only* `jaasctl` command that talks
  to a remote backend over HTTP rather than writing local storage
  directly, since a CI runner has no business having filesystem access to
  `storage_root`/the signing key. `jaasctl guardrails push` similarly
  calls the custom-guardrails CRUD API; `jaasctl guardrails validate`
  talks straight to the guardrails service's `/validate-rule` (no
  tenant/auth needed, mirrors how `cmd_validate` reaches that service).
  See `examples/ci/github-actions-release.yml` for the reference workflow
  these commands are meant to run inside.

## Tests

- `tmp_path` is the standard way to get an isolated store directory for any
  file-backed store test — don't mock the filesystem.
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

## Git/GitHub state (check before assuming otherwise)

- This repo has commits on `master` but **no remote configured**
  (`git remote -v` is empty) — no push/PR/issue workflow is possible until
  one is added (`gh repo create` or `git remote add origin <url>` against
  an already-created one). Don't assume a remote exists.
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
