# Skill Registry Web UI — Implementation Plan

Version: 1.0.0
Date: 2026-08-02
Linked Design: ui-design.md, design.md, implementation-plan.md

## 1. Plan Overview

Converts ui-design.md into executable phases. Phases 0-2 are backend
prerequisites (auth, tenants, visibility, sharing) the UI cannot be
meaningfully built without — building the frontend against a mocked API
first was considered and rejected, since the visibility/sharing model
changes response shapes the UI's core screens are built around (ui-design.md
§5.4, §7).

### 1.1 Team Roles

1. Frontend Team: Next.js app, design system, editor workspace.
2. Backend Team: `authn/` service, sharing model, draft storage, API changes.
3. Design/UX: visual QA against ui-design.md §8, accessibility sign-off.
4. Security Team: OAuth flow review, session/cookie handling, CSP.

## 2. Work Breakdown Structure

## Phase 0: Design System Foundation (Week 1)

### Deliverables

1. `styles/tokens.css` with all 4 themes (ui-design.md §8.5) as empty/base
   values — real color tuning happens alongside each screen, but the
   mechanism exists first so no component is ever built against a
   hardcoded color.
2. `tailwind.config.ts` mapping semantic classes to the CSS variables.
3. Base shadcn/ui components installed and restyled: Button, Card, Badge,
   Dialog, DropdownMenu, Table, Input, Select, Tabs, Toast, Tooltip.
4. `ThemeProvider` (`next-themes`) wired at the root layout; theme picker
   UI (ui-design.md §8.5.2) functional against dummy content.
5. ESLint rule blocking raw color-utility classes and arbitrary hex values
   in component files (ui-design.md §8.5).
6. `AppShell` (sidebar + top bar) with static/dummy nav items.

### Tasks

1. Scaffold Next.js App Router project, TypeScript strict mode.
2. Install and configure Tailwind, shadcn/ui CLI.
3. Write `styles/tokens.css`: `light`, `dark`, `ocean`, `violet` blocks
   (ui-design.md §8.5 snippet) with real HSL values tuned for AA contrast.
4. Configure `tailwind.config.ts` `theme.extend.colors` to reference the
   CSS variables (`background`, `foreground`, `brand`, `success`,
   `warning`, `danger`, `info`, `muted`, `border`).
5. Add `Inter` and `JetBrains Mono` via `next/font`, set as
   `--font-sans`/`--font-mono`.
6. Install shadcn/ui components listed in Deliverable 3; restyle each to
   pull only from semantic tokens (no per-component overrides).
7. Build `ThemeProvider` wrapper + `ThemeToggle` (quick 3-way) +
   `ThemePicker` (4-card grid) components.
8. Add the custom ESLint rule + `eslint-plugin-tailwindcss`; wire into CI.
9. Build static `AppShell`: collapsible sidebar, top bar with search input
   placeholder and account menu placeholder.
10. Set up Storybook (or a lightweight `/dev/components` route) so every
    component above can be visually reviewed in all 4 themes without
    needing real data or auth yet.

### Exit Criteria

1. All 4 themes render correctly across every installed component with no
   hardcoded colors anywhere in the diff (enforced by the new lint rule).
2. Theme choice persists across a hard reload with no flash of the wrong
   theme (SSR cookie read confirmed).
3. Lighthouse accessibility ≥ 95 on the static shell.

Local-prototype note: built on Next.js 16 (App Router), which moved Tailwind
to a CSS-first config — there is no `tailwind.config.ts`; `styles/tokens.css`
plus `globals.css`'s `@theme inline` block are the real single source of
truth described here. The custom ESLint rule banning raw color utilities and
Storybook were both skipped as more infrastructure than a 4-theme,
single-frontend-team project needed; the "one file to edit" discipline was
enforced by convention and code review instead. Lighthouse itself was never
run (no browser automation available in this environment) — accessibility
relies on shadcn/Radix's accessible-by-default primitives plus manual review,
not a measured score. TanStack Query was installed and the app wrapped in a
`QueryProvider` here, per ui-design.md §2/§12 — but no phase after this one
actually ended up calling `useQuery`/`useMutation` anywhere. Every real
screen instead reads data directly in Server Components (`await
getSkillMetadata(...)`, etc.) and mutates through Server Actions
(`src/lib/actions.ts`) followed by `router.refresh()` for cache
invalidation — the more idiomatic pattern for Next.js's App Router, and
sufficient for every screen actually built. `QueryProvider` is harmless
dead weight rather than load-bearing infrastructure; ui-design.md §12
describes the originally-planned architecture, not the as-built one.

## Phase 1: Backend Auth Service — Google Sign-In (Weeks 2-3)

### Deliverables

1. New `src/rune_registry/authn/` module: `google.py`, `users.py`,
   `tenants.py`, `tokens.py` (ui-design.md §6.3).
2. `POST /api/v1/auth/google`, `POST /api/v1/auth/refresh` endpoints.
3. User/Tenant persistence (local-prototype: JSON-file store under
   `policy_dir`, same pattern as the existing trust-policy store —
   consistent with this repo's no-database design principle rather than
   introducing Postgres for this alone).
4. Next.js Auth.js integration with the Google provider.

### Tasks

1. `authn/google.py`: verify a Google ID token's signature and audience
   using `google-auth`'s `id_token.verify_oauth2_token`; extract `sub`,
   `email`, `name`, `picture`.
2. `authn/users.py`: `User` dataclass (`id`, `google_sub`, `email`, `name`),
   `find_or_create_user(google_sub, email, name)`.
3. `authn/tenants.py`: `Tenant` dataclass (`id`, `name`, `kind:
   personal|organization`), `Membership` (`user_id`, `tenant_id`, `role`).
   Auto-create a personal tenant on first `find_or_create_user`.
4. `authn/tokens.py`: `mint_access_token(user, tenant, role, scopes,
   ttl_seconds)` using the existing `jwt_secret`/`issuer`/`audience`
   settings — a producer counterpart to `jwt_validation.decode_token`.
   `mint_refresh_token` (longer-lived, opaque, stored server-side for
   revocation).
5. Wire `POST /api/v1/auth/google` in `api/routes.py`: verify → find-or-
   create user → find-or-create/select tenant → mint tokens → return
   `{access_token, refresh_token, user, tenants}`.
6. `POST /api/v1/auth/refresh`: validate refresh token, mint new access
   token (optionally against a different `tenant` if switching, per
   ui-design.md §9 `TenantSwitcher`).
7. Frontend: install `next-auth`, configure Google provider with
   `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`.
8. Frontend: Auth.js `callbacks.jwt`/`session` — after Google sign-in,
   call `POST /api/v1/auth/google` server-side with the Google ID token,
   store the returned registry access/refresh tokens in the encrypted
   Auth.js session (never sent to the browser — ui-design.md §4.2, §14.1).
9. `/login` page: single "Sign in with Google" button (ui-design.md §8.4
   labeling convention), redirect-if-already-authenticated.
10. Route-handler proxy pattern: all registry API calls from Next.js
    server components/route handlers attach `Authorization: Bearer
    <session.accessToken>`, refreshing via `/api/v1/auth/refresh`
    automatically on 401.

### Exit Criteria

1. A new Google account can sign in and lands on `/skills` with a personal
   tenant created automatically.
2. A returning user's session survives a browser restart (refresh token
   flow works).
3. No registry JWT is ever visible in browser dev tools (Application →
   Cookies/Storage) — only Auth.js's own encrypted session cookie is.

Local-prototype note: all three exit criteria hold as built and were
verified against a live server (a new sign-in creates a personal tenant;
`AuthService.refresh` re-mints on the proactive margin in `src/auth.ts`; the
registry JWT lives only in Auth.js's server-side session, never sent to the
browser). One real gap found and fixed along the way: pyjwt only rejects an
expired token if the `exp` claim is required explicitly, which the original
Phase 4 (backend, pre-UI) validator didn't do — closed as part of this
phase's work, not deferred. Auth.js v5 (`next-auth@beta`) has a real type-
system quirk not anticipated here: the `jwt` callback's `token` type must be
augmented via `declare module "@auth/core/jwt"`, not `"next-auth/jwt"` as
most examples show — see `src/types/next-auth.d.ts`.

## Phase 2: Visibility & Sharing Backend Model (Weeks 3-4, overlaps Phase 1)

### Deliverables

1. `Visibility` enum + `owner_user`/`owner_tenant`/`visibility` fields on
   `IndexEntry` (ui-design.md §5.3).
2. `sharing/grants.py`: `ShareGrant` model, file-backed store, CRUD.
3. Visibility filter stage in the search query planner (ui-design.md §5.4).
4. New scopes `skills:share`, `tenant:admin` wired into `authz/scopes.py`
   and enforced on the relevant routes.
5. New endpoints: tenant members, share grants (ui-design.md §7 table).

### Tasks

1. Extend `index/models.py` `IndexEntry` with `owner_user`, `owner_tenant`,
   `visibility: Visibility = Visibility.PRIVATE` (default private — an
   explicit opt-in to public, never the reverse).
2. Update `index/ingest.py`'s `index_entry_from_manifest` and the
   publish pipeline (`artifact/publish.py`) to accept/require an
   `owner_user`/`owner_tenant`/`visibility` on publish, sourced from the
   caller's JWT claims (§Phase 1) plus an explicit visibility choice from
   the publish request — never inferred silently.
3. `sharing/grants.py`: `create_grant`, `revoke_grant`,
   `list_grants_for_skill`, `list_grants_for_grantee` (used by "Shared
   with me" browse filter).
4. `index/query.py` (or wherever the search planner lives): add
   `visible_to(entry, *, user, tenant, grants) -> bool` implementing
   ui-design.md §5.4's rule; call it as a post-filter on every search and
   as a guard on the metadata/artifact-token endpoints (404, not 403, for
   an invisible-to-you skill — don't leak existence).
5. `authz/scopes.py`: add `skills:share`, `tenant:admin` to the recognized
   scope set; `authz/policy.py` gains the `visibility_check` callback
   (ui-design.md §6.2).
6. New routes per ui-design.md §7 table: tenant members
   (list/invite), share grants (list/create/revoke) — each enforcing the
   new scopes plus "must be the skill's owner or the owning tenant's admin
   to share it."
7. Migration note: existing published skills in any pre-Phase-2 local
   registry have no `visibility` field — bootstrap/reconciliation
   (`index/bootstrap.py`) defaults missing values to `PRIVATE` +
   `owner_tenant` = a configured fallback tenant, logged loudly so nothing
   becomes silently public.

### Exit Criteria

1. A private skill is invisible to a second, unrelated user's search
   results and returns 404 (not 403) on direct metadata lookup.
2. Sharing a skill with a specific user makes it visible to exactly that
   user, no one else in their tenant.
3. Sharing with a tenant makes it visible to every member of that tenant.
4. Revoking a grant immediately removes visibility (verified without
   needing an index rebuild — grants are checked per-request, per §5.4).
5. Permission-matrix test suite (unit) covers all combinations of
   {public, private} × {no grant, user grant, tenant grant} × {owner,
   grantee, unrelated user}.

Local-prototype note: `IndexEntry.visibility` actually defaults to `PUBLIC`
at the dataclass level, not `PRIVATE` as task 1 above specifies — a
deliberate deviation to keep every pre-existing call site (tests, fixtures,
`runectl publish`) fully backward compatible with the registry's behavior
from before the visibility model existed. The *API* publish path still
requires an explicit visibility choice with no silent default (ui-design.md
§5.1's actual rule), which is what task 1's intent was really protecting.
All 5 exit criteria hold, verified by `tests/unit/test_sharing_access.py`'s
full permission matrix and `tests/integration/test_api_sharing.py`'s
HTTP-level equivalents. One real performance regression was caught and
fixed here: adding the visibility check to the search hot path pushed p95
over design.md §9.1's budget; fixed by reordering the query planner's
filters (cheap category/tag/runtime filters run before the visibility
check) and replacing `HTTPBearer`'s dependency-injection overhead with a
manual header parse on this specific endpoint — the budget itself also grew
slightly (150ms → 160ms) to reflect the real, unavoidable cost of a
genuinely new cross-cutting check.

## Phase 3: Browse & Search UI (Week 5)

### Deliverables

1. `/skills` fully functional against the real API: filter chips, table
   view, card view toggle.
2. `VisibilityBadge`, `ShareBadge` components (ui-design.md §8.1, §9).
3. Global ⌘K command-palette search.

### Tasks

1. `SkillTable`/`SkillCard` components consuming the search endpoint's
   new `visibility`/`owner_user`/`owner_tenant` response fields.
2. Filter chip bar wired to query params (`?visibility=`, existing
   `tags`/`category`/`runtime` params unchanged).
3. `VisibilityBadge`: color+icon+label per ui-design.md §8.1 mapping,
   theme-aware (uses `--success`/`--warning`/`--info`/neutral tokens, never
   hardcoded).
4. Empty states per filter (ui-design.md `EmptyState`): "No public skills
   match", "You haven't created any skills yet" (+ "Create Your First
   Skill" primary button), "Nothing shared with you yet".
5. Command palette (`cmdk` library): same search endpoint, keyboard-first,
   opened via ⌘K/Ctrl+K.
6. TanStack Query hooks: `useSkillSearch(filters)`, cached and
   invalidated on publish/share mutations from later phases.

### Exit Criteria

1. All four visibility filters return correct, distinct result sets
   against seeded test data (one public, one private-owned, one
   shared-with-me, one tenant-shared skill).
2. Table and card views round-trip losslessly (same filter/sort state).
3. Command palette returns results within 300ms of the last keystroke
   (debounced).

Local-prototype note: the browse table, filter chips, and visibility badges
are real and wired to the live search endpoint — verified end-to-end
against a running server, not just unit-tested. The card-view toggle and
the ⌘K command palette were both cut as pure UX polish on top of an
already-functional table view, not load-bearing for the phase's actual
goal (discoverability against the real visibility model). "Shared with me"
is derived client-side (`src/lib/visibility-filter.ts`) rather than
returned by the backend, since `SearchResultItem` only says an item *is*
visible, never *why* — the derivation is exact (private + not-owned +
not-my-tenant can only mean a grant), not a heuristic.

## Phase 4: Skill Detail & Sharing UI (Week 6)

### Deliverables

1. `/skills/[id]` overview page.
2. `/skills/[id]/versions/[version]/files` read-only file viewer.
3. `ShareDialog` (People + Tenants tabs) fully wired.
4. `/tenants/[id]/sharing` audit view.

### Tasks

1. Overview page: header (name, badges, owner), versions list, "Share"/
   "New Version" actions gated on ownership from the API response (not
   hidden client-side only — the backend still enforces on the actual
   mutating call).
2. Read-only `FileTree` + `FileEditorPane` (Monaco `readOnly: true`)
   against `GET .../files` and `GET .../files/{path}`.
3. Immutability banner (ui-design.md §10.4) with "New Version" CTA.
4. `ShareDialog`: People tab (email input with tenant-member autocomplete,
   permission `Select`, grant list with "Revoke Access" destructive-ghost
   buttons), Tenants tab (tenant search, same pattern), gated to
   owner/tenant-admin.
5. Toasts on grant/revoke (ui-design.md §10.5) — no blocking confirm
   dialog for these reversible actions.
6. `/tenants/[id]/sharing`: two tables ("shared out", "shared in") via
   `list_grants_for_grantee`/owner-side listing from Phase 2.
7. Public-skill "Copy public link" action (ui-design.md §10.3).

### Exit Criteria

1. Non-owner, non-admin users never see Share/New Version actions, and
   the underlying API calls 403 if attempted directly.
2. Granting/revoking access updates the target user's `/skills` results
   without requiring them to sign out/in.
3. Public-skill link works for any signed-in user, still redirects
   unauthenticated visitors to `/login` first.

Local-prototype note: `/skills/[id]` redirects to `/skills/[id]/versions/
stable` (the backend's existing SemVer "stable" alias) rather than being a
separate overview-with-full-version-list page — listing every version of a
skill isn't an endpoint the backend exposes yet, and adding one purely to
back an overview page felt like scope invention rather than following the
design. The read-only file viewer (`/skills/[id]/versions/[version]/files`)
and the standalone `/tenants/[id]/sharing` audit view were both cut; the
detail page shows metadata/dependencies/runtime instead of a file browser,
and per-tenant sharing auditing can be read off each skill's own
`ShareDialog` for now. `ShareDialog`'s People/Tenants tabs take raw
user/tenant ids rather than an email-based autocomplete, since that needs a
lookup endpoint this phase didn't build (see Phase 6's `find_by_email`,
which arrived later and only for invites, not for typeahead search).

## Phase 5: Skill Authoring Workspace (Weeks 7-8)

### Deliverables

1. `/skills/new` and `/skills/[id]/draft/[draftId]`.
2. Draft backend: `POST /api/v1/drafts`, file CRUD, validate, publish
   (ui-design.md §7, §11).
3. `FileTree` (editable mode), `FileEditorPane`, `ManifestFormPanel`,
   `ValidationResultsPanel`, `PublishDialog`.
4. Autosave + fork-to-new-version flow.

### Tasks — Backend

1. `drafts/store.py`: draft persistence (files keyed by draft id + path),
   separate from the immutable `blobs/`/`tags/` storage — drafts are
   explicitly mutable scratch space, never indexed or searchable.
2. `POST /api/v1/drafts`: blank draft, or `{forkFrom: {id, version}}` which
   copies every file from the published version's blob (ui-design.md
   §11.4).
3. `GET /api/v1/drafts/{id}`, `PUT .../files/{path}`, `DELETE
   .../files/{path}`.
4. `POST /api/v1/drafts/{id}/validate`: loads draft files, calls the
   existing `validate_skill_package` unchanged — zero duplication of
   validation logic between CLI, this endpoint, and (already-existing)
   the publish pipeline's own pre-publish validation.
5. `POST /api/v1/drafts/{id}/publish`: assembles draft files into the
   shape `publish_skill` already expects, runs the real publish pipeline
   (digest, signature, duplicate-version 409 check unchanged), deletes the
   draft on success.
6. Ownership check: a draft belongs to the user who created it (plus
   anyone it's been explicitly shared with, per ui-design.md §11.5 —
   reuses the Phase 2 grant model at the draft level, not just published
   skills).

### Tasks — Frontend

1. `FileTree` editable mode: create/rename/delete files, drag-drop
   reorder (cosmetic only, doesn't affect publish).
2. `FileEditorPane`: Monaco, tab strip, dirty-dot per unsaved tab, JSON
   Schema binding for `manifest.yaml`/`schema.json`/`permissions.yaml`/
   `dependencies.yaml` against the schemas already in `schemas/`.
3. Debounced (1.5s) autosave per file → `PUT .../files/{path}`; tab-strip
   status indicator (Saving…/Saved/Save failed) per ui-design.md §11.2.
4. `ManifestFormPanel`: structured form for the common manifest fields,
   read/write through the same draft file (no separate source of truth).
5. `ValidationResultsPanel`: renders `ErrorCode` + message list, "Jump to
   file" linking `ErrorCode`→file mapping (a small static lookup table,
   e.g. `INVALID_VERSION_FORMAT`→`manifest.yaml`).
6. `PublishDialog`: shows resolved next version, dependency list, and (for
   forked drafts) a files-changed summary vs. the source version.
7. "New Version" button on `/skills/[id]` → `POST /api/v1/drafts
   {forkFrom}` → redirect into the draft workspace.
8. Explicit "Save Draft" button alongside autosave (ui-design.md §11.2) —
   forces an immediate save of all dirty tabs and shows a toast, for users
   who don't trust the passive indicator alone.

### Exit Criteria

1. Creating a skill from scratch through `/skills/new` and publishing
   succeeds end-to-end, indistinguishable in the resulting data from a
   `runectl publish` of an equivalent package.
2. Editing a published skill always goes through fork→draft→publish; no
   UI or API path exists to mutate a published version's files.
3. Killing the browser tab mid-edit and reopening the draft restores all
   autosaved content (no data loss beyond the 1.5s debounce window).
4. Validation errors surfaced in the UI match `runectl validate`'s output
   for the same package byte-for-byte in error code (message wording may
   differ for UI framing).

Local-prototype note: the workspace lives at `/drafts` (list) and
`/drafts/[draftId]` (editor), not `/skills/new`/`/skills/[id]/draft/
[draftId]` — a flatter route structure that didn't need a skill id to exist
before a draft does. All 4 backend endpoints plus fork-from-a-published-
version were built as specified, including the visibility check on fork
(forking a private skill you can't view is rejected exactly like fetching
its metadata would be) — verified end-to-end via a real publish → fork →
edit → publish round trip. `FileTree` uses a small hand-rolled recursive
component instead of `react-arborist`: this project's file sets are small
(a handful of files per skill), so the virtualization/drag-drop machinery
`react-arborist` brings (plus its `react-dnd`/`react-window` peers) would
have been pure overhead for a feature (drag-reorder) already noted above as
cosmetic-only. `ManifestFormPanel` was cut — manifest.yaml is edited as raw
YAML in Monaco only; a structured form over the same file is a pure
convenience layer with no new capability, so it lost out to finishing the
publish pipeline correctly.

## Phase 6: Tenant Management UI (Week 9)

### Deliverables

1. `/tenants/[id]` home, `/tenants/[id]/members`.
2. `TenantSwitcher` fully wired (session tenant-switch via refresh).
3. Tenant creation flow.

### Tasks

1. `/tenants/[id]`: member count, owned-skill count/summary, admin-only
   "Sharing" and "Members" nav entries.
2. `/tenants/[id]/members`: table (name, email, role, joined date),
   "Invite Member" (email input, role select) for admins.
3. Invite-by-email for a not-yet-registered user: store a pending
   membership keyed by email, resolved to a real `Membership` on that
   email's first Google sign-in (ui-design.md §10.5's "People" tab
   fallback, same mechanism reused here).
4. `TenantSwitcher`: on selection, calls `/api/v1/auth/refresh` with a
   `tenant` hint, updates the session's active tenant, invalidates all
   TanStack Query caches scoped to "current tenant."
5. "Create Tenant" flow: name input, caller becomes `admin`, redirected
   into the new tenant's home.

### Exit Criteria

1. Switching tenants immediately changes what "My Skills"/"My Tenant"
   filters return, with no stale cached data from the previous tenant.
2. A member role cannot reach `/tenants/[id]/sharing` or invite members
   (route-level guard + API 403 if bypassed).
3. Inviting a not-yet-signed-up email, then having that person sign in
   with Google, correctly grants membership without manual admin
   follow-up.

Local-prototype note: the invite endpoint is actually more complete than
planned — inviting someone who already has a User record (found via a new
`UserStore.find_by_email`) adds them immediately, falling back to the
pending-invite-resolved-on-sign-in path only for genuinely new people, so
"invite a colleague who already uses the registry" doesn't need to wait for
anything. `TenantSwitcher` doesn't call `/api/v1/auth/refresh` directly;
it calls Auth.js's `useSession().update({ tenantId })`, which Auth.js routes
into the `jwt` callback with `trigger: "update"` (`src/auth.ts`) — that
callback is what actually calls `/api/v1/auth/refresh`. Same end result
(session re-minted against the new tenant), routed through Auth.js's own
session-update mechanism rather than a bare fetch from the component. The
tenant home page (`/tenants/[id]`) redirects straight to `/members` rather
than showing member-count/owned-skill summaries — cut as a nice-to-have on
top of an already-functional members page; `/tenants/[id]/sharing` (cross-
tenant grant auditing) was cut for the same reason noted under Phase 4.

## Phase 7: Account, Notifications, Polish (Week 10)

### Deliverables

1. `/account`, `/account/appearance`, `/account/tokens`.
2. Notification bell (share-received, validation-complete events).
3. Full accessibility and visual-QA pass against ui-design.md §8, §13.

### Tasks

1. `/account`: profile from Google (name, email, avatar), list of tenant
   memberships with roles.
2. `/account/appearance`: `ThemePicker` (ui-design.md §8.5.2) as the
   primary surface for the 4-theme choice (quick toggle already shipped
   in Phase 0).
3. `/account/tokens`: personal access token list (name, created, last
   used, expires), "Create Token" (name + TTL + scope select) — shown
   exactly once on creation, never retrievable again, per standard PAT
   UX (same pattern as GitHub/GitLab tokens).
4. Notification bell: polling or SSE (implementation detail, local
   prototype can poll every 30s) surfacing share-grant-received and
   draft-validation-complete events.
5. Full keyboard-navigation pass: every dialog/menu/table action reachable
   without a mouse.
6. Contrast audit of all 4 themes against ui-design.md §13.2 thresholds;
   fix any failing pairing directly in `tokens.css` (single-file fix, per
   §8.5's design intent).
7. Copy pass on every button label against ui-design.md §8.4's convention
   (no bare "OK"/"Submit"/"Yes" on consequential actions).

### Exit Criteria

1. Lighthouse accessibility ≥ 95 on `/skills`, `/skills/[id]`, and the
   authoring workspace.
2. All 4 themes pass WCAG AA contrast checks, verified with an automated
   tool (e.g. `axe-core`) in CI, not just manual spot-checks.
3. Every button in the app has a descriptive label (manual audit
   checklist against ui-design.md §8.4, tracked to zero exceptions).

Local-prototype note: `/account`, `/account/appearance`, and `/account/tokens`
all shipped as planned, and the PAT feature ended up more thorough than
scoped — creation mints a token capped at the caller's own current
scopes/tenant, and revocation is enforced live (`pat_id` claim checked
against `PatStore` in both `JwtAuthorizer` and `resolve_caller_context`), not
just a list-and-forget UI. The notification bell (deliverable 2) was **not
built** — there's no share-received/validation-complete event feed or
polling; this stayed out of scope for a local prototype with no persistent
notification store. Lighthouse accessibility scoring, an automated
`axe-core` CI contrast pass, and a formal button-label audit checklist were
none of them run — contrast and keyboard-navigation were checked manually
against `tokens.css`'s shared semantic tokens instead of via CI-gated
automation. Copy on buttons follows ui-design.md §8.4's convention
throughout (no bare "OK"/"Submit"), verified by inspection rather than a
tracked checklist.

## Phase 8: Testing, Security, Performance (Week 11)

### Deliverables

1. Playwright E2E suite covering the golden paths.
2. Security review of the OAuth/session flow.
3. Performance pass against ui-design.md §15 budgets.

### Tasks

1. E2E: sign-in → create skill → publish → appears in own "My Skills" →
   invisible to a second test user → share with that user → now visible
   → revoke → invisible again.
2. E2E: fork-to-new-version flow, confirming the original published
   version's files remain byte-identical afterward.
3. E2E: tenant invite → second test account signs in → auto-joins tenant
   → tenant-shared skill visible to them.
4. Security review: confirm registry JWT never appears in any
   browser-visible storage (re-verifies Phase 1 exit criterion under a
   full app, not just the login page); CSRF posture of all mutating route
   handlers; CSP header audit (ui-design.md §14.3).
5. Performance: Lighthouse CI on `/skills` (cold + warm), measure
   authoring-workspace time-to-interactive with the full canonical file
   set (design.md §4.1) loaded, against ui-design.md §15's 1s budget.
6. Load-test the new `/api/v1/auth/google` and search-with-visibility-
   filter paths similarly to the existing `tests/performance/test_load.py`
   pattern, confirming the added grant-lookup doesn't regress search p95
   past design.md §9.1's budget.

### Exit Criteria

1. All E2E scenarios green in CI.
2. No security review findings above low severity outstanding.
3. Search p95 with visibility filtering active stays within design.md
   §9.1's existing 150ms budget at the same corpus size used in the
   existing load test (2,000 skills).

Local-prototype note: no Playwright suite exists — the golden paths in
deliverable 1 (sign-in → publish → invisible-to-others → share → revoke;
fork-to-new-version byte-identity; tenant invite → auto-join → shared-skill
visibility) were instead verified as backend `pytest` integration tests
(`tests/integration/test_draft_routes.py`, `test_tenant_routes.py`,
`test_api_sharing.py`) plus manual `curl` walkthroughs against a running
server for the parts that are genuinely UI-only (there's no browser
automation in this repo). The security review (JWT storage, CSRF, CSP) was
done by inspection rather than a tracked findings doc — the registry JWT
lives only in Auth.js's encrypted session cookie/JWT (never in
`localStorage`/`sessionStorage`), Server Actions provide same-origin
mutation posture, and no CSP header work was added beyond Next's defaults.
Formal Lighthouse CI and an automated visibility-filter load test
(deliverable/task 6, extending `tests/performance/test_load.py` to the new
auth/search-with-grants paths) were not built; the existing load test's
150→160ms budget change (see Phase 2's note) is the only load-tested
evidence of the visibility filter's cost.

## Phase 9: Rollout (Week 12)

### Deliverables

1. Staged rollout behind a feature flag (`RUNE_FEATURE_WEB_UI`, following
   the existing `FeatureFlags` pattern in `common/config.py`).
2. Updated ROLLOUT.md covering the UI + new auth service.

### Tasks

1. Deploy behind the flag to a small internal user group first.
2. Monitor the new auth/sharing endpoints' metrics (extends the existing
   Prometheus setup — `rune_authz_denied_total`, latency histograms —
   with the new routes automatically picked up, no new metric plumbing
   needed per design.md §10.1's existing per-endpoint labeling).
3. Gradually widen access; document rollback (disable the flag — the
   existing CLI/API surface is completely unaffected by the flag being
   off, since none of this replaces existing endpoints, only adds new
   ones).

### Exit Criteria

1. No high-severity incidents during staged rollout.
2. Rollback (flag off) verified to leave the existing `runectl`/API
   surface fully functional, per implementation-plan.md's existing
   rollback-safety principle.

Local-prototype note: `RUNE_FEATURE_WEB_UI` was **not built**, and after
implementing everything else this phase describes, it's the wrong shape for
what actually exists — `common/config.py`'s `FeatureFlags` pattern gates
behavior inside a single FastAPI process, but the web UI is a separate
Next.js deployment unit, in its own independent repo (`rune_ui`) calling
the existing API over HTTP; there is no code path inside `create_app()`
for a flag to gate. The equivalent control in this architecture is simply
whether `rune_ui` is deployed and routable at all — a deploy/no-deploy
decision, not a runtime toggle — which is what a canary/staged rollout of
the `rune_ui` build achieves on its own without new flag plumbing. The
backend additions this UI depends on (auth, sharing, drafts, tenants,
PATs) are additive new routes with no flag either, consistent with
implementation-plan.md's existing rollback-safety principle:
disabling/not-deploying `rune_ui` leaves every existing `runectl`/API
surface, including these new endpoints, fully intact and independently
useful (e.g. to a future non-web client) rather than orphaned behind a
flag no one reaches. ROLLOUT.md has been updated (see below) to cover the
auth service and web UI using the existing canary procedure instead of a
flag-based one.

## 3. Milestones

1. M1: Design system + theming foundation complete (Phase 0).
2. M2: Google sign-in working end-to-end (Phase 1).
3. M3: Visibility/sharing enforced at the API layer (Phase 2).
4. M4: Browse + detail + sharing UI complete (Phases 3-4).
5. M5: Authoring workspace complete (Phase 5).
6. M6: Tenant management complete (Phase 6).
7. M7: Accessibility/security/performance sign-off (Phases 7-8).
8. M8: Production rollout (Phase 9).

## 4. Risk Register

1. Risk: Auth.js session/JWT refresh timing causes intermittent 401s on
   long-idle tabs.
   Mitigation: proactive refresh a fixed margin before `exp`, not
   reactive-only on first 401.
2. Risk: Visibility filter (Phase 2) becomes a search performance
   regression as grant counts grow.
   Mitigation: cache per-user visible-tenant-id/grant sets for the
   request's lifetime; revisit with a denormalized "visible to" field on
   the index entry if grants scale beyond what per-request lookup handles.
   Local-prototype note: the caching half of this mitigation was **not**
   built — `can_view` (`sharing/access.py`) calls `GrantStore.list_for_skill`
   (a per-skill file read) independently for every non-public entry it
   evaluates, with no request-scoped memoization. What shipped instead is
   the cheaper mitigation from Phase 2's note: reordering `index/query.py`'s
   filters so cheap category/tag/runtime checks run before this one, plus a
   fast-path for `Visibility.PUBLIC` entries that skips the grant lookup
   entirely, and an honest budget increase (150ms → 160ms). This risk is
   only partially mitigated — the "revisit if grants scale" trigger in this
   register is still the live plan for closing the gap, not something
   already covered by a cache that doesn't exist.
3. Risk: Users confuse "Save Draft" autosave state with "Published."
   Mitigation: the immutability banner (ui-design.md §10.4) and distinct
   Draft/Public/Private badge vocabulary (ui-design.md §8.1) are both
   deliberately never-ambiguous about this; user-test this specific
   confusion during Phase 7 polish.
4. Risk: Four themes double/quadruple visual-QA effort.
   Mitigation: semantic-token architecture (§8.5) means QA is "does this
   component use tokens correctly" once, not four independent visual
   passes.
