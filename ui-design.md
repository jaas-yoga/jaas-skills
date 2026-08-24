# Skill Registry Web UI — Technical & UX Design

Version: 1.0.0
Date: 2026-08-02
Status: Proposed for Engineering Execution
Linked Design: design.md, implementation-plan.md

## 1. Purpose and Scope

This document defines the web UI for JaaS Skills: Google
sign-in/signup, a visibility and sharing model (public skills, private
skills, skills shared with specific users, and skills shared across
tenants), and a skill authoring workspace with a file tree and in-browser
editor. It also defines the backend changes this requires — visibility and
sharing are authorization concerns the API must enforce; the UI cannot
enforce them on its own.

### 1.1 Goals

1. Let a user sign up/sign in with their Google account, with zero
   registry-specific passwords.
2. Make ownership and visibility of every skill unambiguous at a glance:
   public, private, shared-with-me, shared-with-my-tenant.
3. Let a user share a private skill with another specific user, or a tenant
   admin share a skill (or all of a tenant's skills) with another tenant.
4. Provide a file-tree + editor authoring experience for skill packages,
   consistent with design.md §4.1's package layout.
5. Meet enterprise dashboard UX conventions: clear typography, restrained
   color use with deliberate semantic meaning, labeled buttons (not
   icon-only actions for anything destructive or non-obvious), predictable
   navigation.

### 1.2 Non-Goals

1. A public marketing site — this is an authenticated application; the only
   unauthenticated surface is the sign-in screen and (optionally) a
   read-only public-skill detail page reachable by direct link (§10.3).
2. Real-time collaborative editing (multiple users editing one draft
   simultaneously) — out of scope for v1; last-write-wins with a warning is
   sufficient (§11.5).
3. Mobile-native apps. Responsive web only (§13).
4. Billing/usage metering UI.

## 2. Tech Stack

1. **Framework**: Next.js (App Router), TypeScript. SSR is used for the
   skill browse/detail pages (fast first paint, shareable/crawlable URLs
   for public skills); everything behind auth still renders per-request
   against the live API, so SSR here is about latency, not static
   generation.
2. **Auth**: Auth.js (NextAuth) v5, Google OAuth provider. Auth.js owns the
   browser-side OAuth dance and session cookie; it does **not** replace the
   registry's own JWT — see §4.
3. **Styling**: Tailwind CSS + shadcn/ui (Radix primitives). shadcn/ui
   components are copied into the repo (not an npm black box), so they can
   be restyled to the tokens in §8 directly.
4. **Data fetching/cache**: TanStack Query for all registry API calls
   (search, skill detail, sharing, drafts) — handles cache invalidation
   after publish/share actions and background refetch.
5. **Forms**: React Hook Form + Zod, sharing schemas with the backend's
   Pydantic models conceptually (manifest fields, share-grant fields).
6. **Code/file editor**: Monaco Editor (the VS Code editor component) for
   YAML/JSON/Markdown/Python/JS file contents, with per-extension syntax
   highlighting and the manifest schema (design.md §4.2) wired in as a JSON
   Schema for inline validation of `manifest.yaml`/`schema.json`.
7. **File tree**: `react-arborist` (virtualized, keyboard-navigable tree),
   styled to the tokens in §8 rather than its default theme.
8. **Icons**: `lucide-react` (matches shadcn/ui's default icon set).
9. **Theming**: `next-themes` — handles the `data-theme` attribute switch,
   `localStorage`/cookie persistence, and no-flash SSR hydration for the
   4-theme model in §8.5.
10. **Testing**: Playwright for E2E (§14), Vitest + Testing Library for
    component tests.

## 3. Information Architecture (Sitemap)

```text
/login                                  Google sign-in (unauthenticated)
/                                       Redirects to /skills

/skills                                 Browse/search (default: all visible-to-me)
/skills?visibility=public
/skills?visibility=mine
/skills?visibility=shared-with-me
/skills?visibility=tenant

/skills/new                             Authoring workspace — new draft
/skills/[id]                            Overview (latest version, versions list)
/skills/[id]/versions/[version]         Version detail (manifest, deps, permissions)
/skills/[id]/versions/[version]/files   Read-only file tree + viewer (published, immutable)
/skills/[id]/draft/[draftId]            Authoring workspace — edit existing draft
/skills/[id]/share                      Sharing dialog target (rendered as a modal route)

/tenants/[tenantId]                     Tenant home: members, owned skills summary
/tenants/[tenantId]/members             Member list + invite
/tenants/[tenantId]/sharing             Cross-tenant share grants (given + received)
/tenants/[tenantId]/guardrails          Publish guardrails policy (design.md §4.5, §10.7)

/account                                Profile (from Google), linked tenants
/account/appearance                     Theme picker — light/dark/ocean/violet (§8.5)
/account/tokens                         Personal access tokens for CLI/CI use (§4.4)
```

Global chrome (persists across all authenticated routes): left sidebar
(primary nav + tenant switcher), top bar (search box, notifications,
account menu). See §10.1.

## 4. Authentication & Identity Model

### 4.1 Why a new backend auth service is required

Today `authz/jwt_validation.py` only **validates** JWTs already signed with
`settings.jwt_secret` — nothing in the backend issues one, and there is no
user or tenant record anywhere (`TokenClaims.tenant` is just a bare string
pulled off whatever token was handed to it). Google sign-in requires a
service that (a) verifies the Google identity, (b) resolves it to a durable
user record and tenant membership, and (c) mints the registry's own JWT.
That's a new backend component: `authn/` (distinct from the existing
`authz/`), described in §6.

### 4.2 Sign-in sequence

```text
Browser              Next.js (Auth.js)          Google              Registry API (authn/)
  | click "Sign in |                          |                    |
  | with Google"   |------------------------->|                    |
  |                | redirect to Google consent screen              |
  |<---------------|                          |                    |
  | user approves  |                                                |
  |----------------------------------------->|                     |
  |                | Google redirects back with an auth code        |
  |<--------------------------------------------|                  |
  |                | Auth.js exchanges code -> Google ID token       |
  |                |----------------------------------------------->|
  |                |               POST /api/v1/auth/google          |
  |                |               { id_token }                      |
  |                |                                                 | verify id_token
  |                |                                                 | signature+aud w/ Google's
  |                |                                                 | public keys (google-auth lib)
  |                |                                                 | find-or-create User by
  |                |                                                 |   google_sub (§6.1)
  |                |                                                 | find-or-create default
  |                |                                                 |   personal Tenant on first
  |                |                                                 |   sign-up (§5.2)
  |                |<-----------------------------------------------|
  |                |               { jaas_access_token (JWT),        |
  |                |                 jaas_refresh_token, user, tenants }
  |                | Auth.js stores jaas_access_token in the         |
  |                | server-side session (httpOnly cookie, encrypted)|
  |<---------------|                                                 |
  | redirected to /skills, session cookie set                        |
```

Key point: the browser never sees or stores the registry JWT directly —
Auth.js keeps it server-side in the encrypted session, and Next.js server
components/route handlers attach it as `Authorization: Bearer <token>` when
calling the registry API. This avoids exposing a long(er)-lived token to
client-side JS (XSS blast-radius reduction).

### 4.3 Token claims (extends `TokenClaims` in jwt_validation.py)

```json
{
  "sub": "usr_01hf...",            // stable internal user id, not the Google sub directly
  "email": "person@example.com",
  "name": "Person Name",
  "tenant": "tnt_01hf...",         // the *active* tenant for this session
  "tenant_role": "member|admin",   // §5.2
  "scope": "skills:read skills:write skills:share",
  "iss": "jaas-registry-auth",
  "aud": "jaas-registry",
  "exp": 1234567890
}
```

`enforce_tenant_boundary` (existing feature flag) stays meaningful
unchanged — the header-vs-claim tenant check in `policy.py` doesn't need to
change, only how the claim gets populated does.

### 4.4 Personal access tokens (for `jaasctl` CLI use)

The CLI (`jaasctl publish`, `jaasctl serve`) has no browser to run an OAuth
flow in. `/account/tokens` lets a signed-in user mint a long-lived (but
revocable, listed, individually named) token scoped like a normal JWT, for
`export JAAS_TOKEN=...` use with the CLI. This is the same JWT shape as
§4.3 with a longer `exp`, not a different mechanism — no new validation
path needed in `authz/`.

## 5. Multi-Tenancy & Visibility Model

### 5.1 New concepts

1. **User** — a person, identified by Google `sub`. Can belong to multiple
   tenants (e.g., a consultant working across two orgs).
2. **Tenant** — an organization/workspace. Every user gets one personal
   tenant automatically on first sign-up (so "just me, no org" works
   without forcing an org-creation step) plus can join/create others.
3. **Skill visibility** (new field on the skill, per version-independent
   metadata — visibility is a property of the skill `id`, not each
   version):
   - `public` — discoverable and readable by any authenticated user (not
     unauthenticated, except the optional read-only link in §10.3).
   - `private` — visible only to the owning user/tenant and anyone it's
     explicitly shared with.
   - Sharing is additive metadata on top of `private`, not a third
     visibility enum value (§5.3) — this avoids the combinatorial
     explosion of "private-shared-with-user" vs "private-shared-with-tenant"
     vs both.
4. **Share grant** — an ACL entry: `(skill_id, grantee_type: user|tenant,
   grantee_id, permission: read|read+write, granted_by, granted_at)`.

### 5.2 Tenant roles

1. `admin` — manage members, create/accept cross-tenant share grants,
   change a skill's owning-tenant visibility default.
2. `member` — publish skills, share skills they own with individual users,
   cannot create tenant-to-tenant share grants (prevents a single member
   from exposing the whole tenant's catalog without admin sign-off).

### 5.3 Data model changes (`index/models.py`)

```python
class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"

@dataclass(frozen=True)
class IndexEntry:
    # ... existing fields unchanged ...
    owner_user: str            # new — replaces bare "actor" string with a real user id
    owner_tenant: str          # new — the tenant a skill is published under
    visibility: Visibility     # new
    # owner_team (existing) is kept as a free-text label for display/search,
    # distinct from owner_tenant which is the enforceable identity
```

Share grants are **not** stored on `IndexEntry` (they change independently
of a skill's own metadata and shouldn't require re-indexing a skill to
add/revoke one). New store: `sharing/grants.py`, persisted the same way
policy/trust files are today (`policy_dir`), keyed by skill id.

### 5.4 Search/authorization filtering

`GET /api/v1/skills` must only return entries where, for the caller's
`(user, tenant)`:

```text
visibility == PUBLIC
  OR owner_tenant == caller.tenant
  OR exists ShareGrant(skill_id, grantee_type=USER, grantee_id=caller.user)
  OR exists ShareGrant(skill_id, grantee_type=TENANT, grantee_id=caller.tenant)
```

This is a new filter stage in the index query planner (design.md §3.2),
evaluated per-request against the caller's claims — never baked into the
index itself, since the same index entry is visible/invisible to different
callers.

## 6. Authorization Model Changes (`authz/`)

1. New scopes: `skills:share` (create/revoke a share grant),
   `tenant:admin` (manage members and tenant-level share grants).
2. `policy.py`'s `JwtAuthorizer.check` gains an optional
   `visibility_check` callback so route handlers can pass "does this caller
   have read access to skill X" without every route reimplementing §5.4's
   rule.
3. New `authn/` module (separate from `authz/`, per §4.1): `google.py`
   (verify Google ID token), `users.py` (find-or-create User), `tenants.py`
   (find-or-create personal tenant, membership management), `tokens.py`
   (mint the registry's own JWT — reuses the existing `jwt_secret`/`issuer`
   config, just becomes a producer of tokens instead of only a consumer).

## 7. New/Changed Backend APIs

| Method & Path | Purpose |
|---|---|
| `POST /api/v1/auth/google` | Exchange a Google ID token for a registry JWT (+ refresh token) |
| `POST /api/v1/auth/refresh` | Exchange a refresh token for a new access token |
| `GET /api/v1/tenants` | Tenants the caller belongs to |
| `POST /api/v1/tenants` | Create a new tenant (caller becomes admin) |
| `GET /api/v1/tenants/{id}/members` | List members (admin or member) |
| `POST /api/v1/tenants/{id}/members` | Invite a member by email (admin only) |
| `POST /api/v1/tenants/{id}/tokens` | Mint a personal access token (§4.4) |
| `GET /api/v1/skills/{id}/shares` | List share grants for a skill (owner/admin only) |
| `POST /api/v1/skills/{id}/shares` | Create a share grant: `{grantee_type, grantee_id, permission}` |
| `DELETE /api/v1/skills/{id}/shares/{grantId}` | Revoke a share grant |
| `GET /api/v1/skills/{id}/versions/{version}/files` | List the file tree for a **published** version (read-only) |
| `GET /api/v1/skills/{id}/versions/{version}/files/{path}` | Fetch one file's contents (published, read-only) |
| `POST /api/v1/drafts` | Create a new draft (blank, or forked from an existing version — §11.4) |
| `GET /api/v1/drafts/{draftId}` | Fetch a draft's full file tree + contents |
| `PUT /api/v1/drafts/{draftId}/files/{path}` | Upsert one file's contents in a draft |
| `DELETE /api/v1/drafts/{draftId}/files/{path}` | Remove a file from a draft |
| `POST /api/v1/drafts/{draftId}/validate` | Run `validate_skill_package` + the tenant's guardrail policy (§4.5) against the draft's current files; response carries both `errors` (blocking, includes guardrail BLOCK findings) and `warnings` (non-blocking guardrail WARN findings) |
| `POST /api/v1/drafts/{draftId}/publish` | Validate, sign, and publish the draft as a new version (existing `publish_skill` pipeline) |
| `GET /api/v1/guardrails` | Full guardrail catalog (design.md §4.5) — no auth, same posture as search |
| `GET /api/v1/tenants/{id}/guardrail-policy` | The tenant's enabled configurable checks (any member) |
| `PUT /api/v1/tenants/{id}/guardrail-policy` | Update the tenant's enabled configurable checks (admin only) |

`GET /api/v1/skills` and `GET /api/v1/skills/{id}/versions/{version}` gain
the §5.4 visibility filter but keep their existing request/response shape
otherwise (additive — `visibility`, `owner_user`, `owner_tenant` are new
response fields, nothing removed).

## 8. Visual Design System

### 8.1 Color

Enterprise-dashboard palette: mostly neutral, with color reserved for
meaning (status/visibility), not decoration.

| Token | Value | Use |
|---|---|---|
| `--brand-600` | `#4F46E5` (indigo) | Primary buttons, active nav item, links |
| `--brand-700` | `#4338CA` | Primary button hover |
| `--neutral-950`…`--neutral-50` | Tailwind Slate scale | Text, borders, surfaces (dark→light) |
| `--surface` | `#FFFFFF` / `--neutral-950` (dark) | Page/card background |
| `--surface-muted` | `--neutral-50` / `--neutral-900` (dark) | Sidebar, table stripe |
| `--success-600` | `#16A34A` | Public badge, validation pass, publish success toast |
| `--warning-600` | `#D97706` | Draft/unpublished badge, non-blocking validation warnings |
| `--danger-600` | `#DC2626` | Destructive actions, validation errors, revoke-share |
| `--info-600` | `#0284C7` | Shared-with-me / shared-with-tenant badges |

Dark mode is a first-class target (not an afterthought): every token above
has a dark-mode pair, driven by `prefers-color-scheme` with a manual
override toggle in the account menu, consistent with this org's existing
artifact-publishing convention of theme-aware pages.

Semantic badges (used throughout §10) always pair **color + icon + text
label** — never color alone (accessibility: color-blind users, and it's
simply clearer):

- Public → green dot + `Globe` icon + "Public"
- Private → slate dot + `Lock` icon + "Private"
- Shared with me → blue dot + `Users` icon + "Shared with you"
- Shared with tenant → blue dot + `Building2` icon + "Shared with {tenant}"
- Draft → amber dot + `PenLine` icon + "Draft"

### 8.2 Typography

- UI font: **Inter** (variable font), matches the "clean enterprise SaaS"
  register (Linear/Vercel/GitHub all use it or a near-identical grotesque).
- Code/editor font: **JetBrains Mono**, ligatures off (ligatures read as
  "wrong characters" to users scanning manifests literally).
- Type scale (Tailwind defaults, applied deliberately rather than ad hoc):
  `text-2xl font-semibold` page titles, `text-lg font-medium` section
  headers, `text-sm` body/table default, `text-xs text-neutral-500`
  metadata/timestamps. No more than 3 weights in use anywhere (400/500/600).

### 8.3 Spacing, radius, elevation

- 4px base spacing unit (Tailwind default scale) — consistent gutters, no
  arbitrary pixel values in component code.
- `rounded-lg` (8px) on cards/dialogs/inputs, `rounded-md` (6px) on buttons
  — one radius vocabulary, not per-component tuning.
- Elevation via border + minimal shadow (`shadow-sm`) rather than heavy
  drop-shadows — flatter, denser enterprise look vs. a marketing-site feel.

### 8.4 Buttons — labeling convention

Every button has a visible text label; icons are supplementary, never a
replacement, for any action that isn't universally obvious (e.g., a bare
"×" to close a dialog is fine; a bare share icon is not). Verb-first,
specific labels:

| Variant | Example labels |
|---|---|
| Primary (`--brand-600` fill) | "Publish Skill", "Sign in with Google", "Create Tenant", "Save Draft" |
| Secondary (outline) | "Cancel", "View File History", "Save as Draft" (when distinct from primary Publish) |
| Destructive (`--danger-600` outline, fills red on hover) | "Revoke Access", "Delete Draft" |
| Ghost/text | In-table row actions: "Edit", "Share", "View" |

Never: "OK", "Submit", "Yes" as a lone label on an action with real
consequences (publish, revoke, delete) — the label always names the actual
action so a confirmation dialog is legible even out of context.

### 8.5 Centralized tokens and user-selectable themes

All color and typography values live in exactly **one** file,
`styles/tokens.css`, as CSS custom properties scoped per theme via
`[data-theme="..."]`. No component, page, or Tailwind class ever hardcodes
a hex value or a raw Tailwind color utility (`bg-indigo-600`,
`text-slate-400`, etc.) — an ESLint rule (`eslint-plugin-tailwindcss`
`no-arbitrary-value` + a small custom rule denying the raw color-utility
class list) enforces this in CI, not just in code review. Components only
ever reference semantic classes (`bg-brand`, `bg-surface`,
`text-foreground`, `border-muted`) that `tailwind.config.ts` maps to the
CSS variables:

```css
/* styles/tokens.css — the single source of truth for §8.1/§8.2 */
[data-theme="light"] {
  --background: 0 0% 100%;
  --foreground: 222 47% 11%;
  --brand: 243 75% 59%;        /* indigo, per §8.1 */
  --success: 142 71% 35%;
  --warning: 32 95% 44%;
  --danger: 0 72% 51%;
  --info: 199 89% 40%;
  --font-sans: "Inter", ui-sans-serif, system-ui;
  --font-mono: "JetBrains Mono", ui-monospace;
}
[data-theme="dark"] {
  --background: 222 47% 8%;
  --foreground: 210 20% 96%;
  --brand: 243 75% 68%;        /* lightened for AA contrast on dark bg */
  /* success/warning/danger/info re-tuned for dark-bg contrast, same hues */
}
[data-theme="ocean"] {
  /* same --background/--foreground pattern as light or dark (§8.5.1),
     --brand replaced with a teal/cyan hue (≈189°) */
}
[data-theme="violet"] {
  /* --brand replaced with a purple hue (≈271°) */
}
```

Adding, renaming, or retuning a theme is a one-file change; no component
code is ever touched to support it.

#### 8.5.1 The four built-in themes

1. **Light** — default for new users, per §8.1.
2. **Dark** — full dark-mode pass, per §8.1.
3. **Ocean** — light-background layout with a teal/cyan `--brand` accent,
   for users who find indigo too close to the "shared" info-badge color at
   a glance.
4. **Violet** — dark-background layout with a purple `--brand` accent, an
   alternative high-contrast dark option.

**Semantic colors never move between themes.** `--success` (public),
`--warning` (draft), `--danger` (destructive), `--info` (shared) keep the
same hue family in all four themes — only `--brand`,
`--background`/`--foreground`, and surface neutrals vary. This is
deliberate: a visibility badge must mean the same thing regardless of which
theme a user picked, so switching themes never makes "Public" look like
"Shared."

#### 8.5.2 Theme picker

- Location: account menu quick-toggle (light/dark/system, one click, the
  90%-use-case) **and** a fuller picker at `/account` → "Appearance" —
  four swatch cards (one per theme in §8.5.1), each rendering a small
  live-styled preview (mimicking a `SkillCard` + a primary button) so the
  choice is visual, not a name in a dropdown.
- "System" is a fifth *option* that maps to Light or Dark based on the OS
  preference, not a fifth theme file — Ocean/Violet are opt-in only, never
  auto-selected.
- Persistence: `next-themes` writes the choice to `localStorage` and a
  cookie (cookie is what SSR reads to render the correct theme on the very
  first response, avoiding a flash of the wrong theme before JS hydrates).
- Scope: the preference is per-browser (`localStorage`/cookie), not stored
  server-side against the user account in v1 — deliberately simple; if
  cross-device sync of the preference is wanted later, it's one field on
  the `User` record (§5.1) and a merge-on-login step, not a redesign.

## 9. Component Inventory

1. `AppShell` — sidebar + top bar + content slot (all authenticated routes).
2. `TenantSwitcher` — dropdown in the sidebar header; switching tenants
   re-issues/refreshes the session's active-tenant claim (§4.3) via
   `/api/v1/auth/refresh` with a `tenant` hint.
3. `SkillCard` / `SkillTable` — two density modes for the browse page
   (§10.2), both driven by the same data shape.
4. `VisibilityBadge`, `ShareBadge` — §8.1 semantic badges.
5. `ShareDialog` — add/remove share grants (§10.5).
6. `FileTree` — `react-arborist`-based, shows the design.md §4.1 layout;
   read-only mode (published) vs. editable mode (draft) driven by one prop.
7. `FileEditorPane` — Monaco instance, tab strip for open files, dirty-dot
   per unsaved tab.
8. `ManifestFormPanel` — a structured form view over `manifest.yaml` as an
   alternative to raw YAML editing, for fields most authors touch often
   (name, description, tags, category, permissions) — power users can still
   edit the raw file; the two stay in sync via the same draft file write.
9. `ValidationResultsPanel` — surfaces `validate_skill_package` errors
   inline, mapped to the specific file/line where possible (schema errors
   already carry a stable `ErrorCode`; §14.1 covers mapping these to file
   positions).
10. `PublishDialog` — final confirmation, shows resolved version number,
    dependency list, and a diff-of-files-changed summary vs. the previous
    version when forked (§11.4).
11. `EmptyState` — consistent "nothing here yet" component with one clear
    primary action (e.g., empty search results → "Clear filters"; empty
    "My Skills" → "Create Your First Skill").
12. `Toast` — success/error/info, used for publish results, share
    grant changes, autosave confirmations.
13. `Breadcrumbs` — skill id → version → file path, always shows current
    location in deep authoring/detail views.
14. `TenantNavTabs` — Members | Sharing | Guardrails tab row under a
    tenant's header, active-tab underline in `--brand` (§10.6-§10.7 share
    this shell).
15. `GuardrailLevelSection` — one collapsible section per catalog level
    (§4.5), header shows the level name + one-line posture ("Always
    enforced" / "On by default" / "Opt-in" / "Opt-in, regulatory") + a
    live count badge ("3 of 6 enabled"). Level 1 renders its rows
    read-only; Levels 2-4 render `GuardrailCheckRow`.
16. `GuardrailCheckRow` — name, description, category chip, a static
    "Blocks"/"Warns" badge (color-coded per §8.1's danger/warning tokens),
    and a `Switch` (admin) or a read-only "On"/"Off" `Badge` (member).
17. `Switch` — new shadcn primitive, retthemed like `Select`/`Dialog`
    (`data-[state=checked]:bg-brand`) — first use case is
    `GuardrailCheckRow`, generically reusable anywhere else a boolean
    toggle is needed later.
18. `GuardrailWarningsPanel` — sibling to `ValidationResultsPanel` (§9.9),
    same visual idiom with the `--warning-600` token and an `AlertTriangle`
    icon instead of the error styling; renders the `validate` response's
    `warnings` array; renders nothing when empty.

## 10. Screen-by-Screen UX Spec

### 10.1 Global shell

- **Sidebar** (240px, collapsible to icon rail): Browse, My Skills, Shared
  with Me, Drafts, Tenant (name + switcher), Members, Sharing, Settings.
- **Top bar**: global search (⌘K opens a command palette variant of the
  same search), notification bell (share-grant received, validation
  finished), account menu (avatar from Google profile, name, email, theme
  toggle, "Sign out").
- Active nav item and any "current tenant context" indicator use
  `--brand-600` — the single most saturated color on screen, so the current
  location is never ambiguous.

### 10.2 `/skills` — Browse

- Filter chips across the top: `All`, `Public`, `My Skills`, `Shared with
  me`, `My Tenant`, plus category/tag/runtime filters from the existing
  search API (design.md §5.1) — this screen is the existing search endpoint
  with the §5.4 visibility filter and these chips as its UI.
- Table view (default, enterprise-dashboard-appropriate) with columns:
  Name, Visibility badge, Owner, Category, Latest version, Updated. Card
  view toggle available for a more visual/browsy feel.
- Row click → `/skills/[id]`. Row hover reveals ghost-button actions
  ("View", "Share" if owner, "New Version" if owner).

### 10.3 `/skills/[id]` — Overview

- Header: name, visibility badge, owner (user avatar + tenant name),
  category/tags.
- Primary actions (owner only): "Share", "New Version" (→ forks latest
  into a draft, §11.4).
- Versions list (newest first): version, publish date, digest (truncated,
  copyable), "View Files" link.
- If `visibility=public`, a "Copy public link" action is shown — this is
  the one authenticated-but-shareable-outside-the-app case (§1.2): the
  linked page still requires sign-in, but any signed-in user can open it
  without needing an explicit share grant, consistent with §5.4's rule.

### 10.4 `/skills/[id]/versions/[version]/files` — Published file viewer

- `FileTree` in read-only mode + `FileEditorPane` in read-only mode
  (Monaco's `readOnly: true`) — same components as the authoring workspace,
  so the visual language is identical between "look" and "edit" modes.
- Banner: "This version is published and immutable. To make changes, start
  a new version." with a "New Version" button — makes the immutability
  rule a visible fact of the UI, not a surprise when a save fails.

### 10.5 Sharing dialog (`ShareDialog`, opened from §10.3 or the browse table)

- Two tabs: "People" and "Tenants" (the latter only shown/enabled for
  tenant admins, per §5.2, on skills owned by that tenant).
- "People" tab: email-based add (autocompletes against tenant members
  first, falls back to inviting-by-email which resolves once that person
  signs in with that Google account), permission dropdown (`Can view` /
  `Can view and publish new versions`), list of current grants each with a
  "Revoke Access" destructive-ghost button.
- "Tenants" tab: tenant search/select, same permission dropdown, existing
  grants listed with tenant name + who granted it + when.
- Every grant/revoke action shows an inline confirmation toast, not a
  blocking dialog — these are reversible (§5.4 grants can always be
  re-added), so the higher-friction confirm pattern is reserved for
  publish/delete.

### 10.6 `/tenants/[id]/sharing` — Cross-tenant grants overview

- Two sections: "Skills we've shared out" and "Skills shared with us" —
  each a table of (skill, granted to/by, permission, date), so a tenant
  admin can audit exposure in one place rather than hunting per-skill.

### 10.7 `/tenants/[id]/guardrails` — Publish guardrails policy

Design precedent: this screen deliberately follows the same grouped-toggle
pattern used by GitHub's "Code security and analysis" repo settings tab,
AWS Security Hub's standards page (rule packs grouped by framework, with a
pass/enabled count per pack), and Snyk's per-project security-rule
settings — a list of checks grouped by a fixed tier, each row independently
togglable, with the always-on tier visually distinct from the optional
ones. That's a deliberate, well-worn enterprise pattern for exactly this
kind of "some rules are non-negotiable, some are your call" content, so
this screen doesn't invent new interaction language.

- **No new auth work.** This page sits behind the same signed-in Google
  session as every other authenticated route (§4) and the same
  `_require_membership`/`_require_admin` tenant-role gate already enforced
  server-side for `/tenants/[id]/members` (§5.2) — a non-member gets the
  same 404 `TenantNotFound` treatment as elsewhere, a member who isn't an
  admin sees the page but every control is read-only.
- **Header**: "Publish Guardrails" title + one-line description
  ("Automated checks that run every time someone on this tenant publishes
  a skill.") + `TenantNavTabs` (§9.14) with "Guardrails" active.
- **Four `GuardrailLevelSection`s (§9.15)**, in level order:
  1. **Baseline** — badge "Always enforced", `--danger-600` accent (these
     block a publish). Rows render read-only regardless of role — there is
     no admin path to turn these off, and the UI says so directly rather
     than showing a disabled-looking toggle that invites a support ticket.
  2. **Standard** — badge "On by default", `--warning-600` accent (WARN
     severity). Admins see live `Switch` controls; members see read-only
     "On"/"Off" badges.
  3. **Advanced** — badge "Opt-in", same accent, same control split.
  4. **Regulatory** — badge "Opt-in · regulatory", same accent, plus a
     one-line note ("Lower-confidence heuristics intended for tenants under
     specific compliance requirements") so admins don't enable these
     expecting Standard-tier precision.
- **Save**: one "Save Changes" button at the bottom of the page (not
  per-row auto-save — a policy change affects every future publish for the
  whole tenant, which is exactly the class of action this org's button
  convention (§8.4) treats as deliberate, not a low-stakes autosave field).
  On success: toast + `router.refresh()`, matching the sharing dialog
  pattern (§10.5).
- **Empty/error states**: if the catalog fails to load (submodule/startup
  issue, design.md §4.5), the whole page renders `EmptyState` with a
  "Retry" action — the same shape as the existing skills-browse load
  failure (§10.2) — rather than a partially-rendered settings form.

## 11. File Tree & Editor Design

### 11.1 Two distinct modes, one component set

- **Draft mode** (`/skills/new`, `/skills/[id]/draft/[draftId]`): fully
  editable. Files can be added, edited, renamed, deleted.
- **Published mode** (`/skills/[id]/versions/[version]/files`): strictly
  read-only, per §10.4 — this is the load-bearing rule that keeps the UI
  honest about design.md's immutability guarantee. There is no code path
  in the frontend that PUTs to a published version's files; the backend
  has no such endpoint either (§7).

### 11.2 Draft persistence and autosave

- Each keystroke updates local editor state only; a debounced (1.5s idle)
  autosave calls `PUT /api/v1/drafts/{id}/files/{path}` per changed file.
- A visible, unobtrusive status indicator in the tab strip: "Saving…" →
  "Saved" (with relative timestamp) → "Save failed, retrying" on error,
  so "can I close this tab" always has a visible answer instead of relying
  on a manual Save button as the only truth (a manual "Save Draft" button
  still exists for explicit control and to satisfy the requested labeled
  button, but autosave means it's never the only way work gets persisted).

### 11.3 Validation feedback

- "Validate" button (and automatically, right before "Publish" is
  enabled) calls `POST /api/v1/drafts/{id}/validate`, which runs the exact
  same `validate_skill_package` used by `jaasctl validate` — one validation
  implementation, exercised from the CLI, the API, and the UI.
- Errors render in `ValidationResultsPanel` with the stable `ErrorCode`
  (e.g. `INVALID_VERSION_FORMAT`, `CIRCULAR_DEPENDENCY`) and, where the
  error identifies a specific document, a "Jump to file" link that opens
  the right tab in `FileEditorPane`. A `GUARDRAIL_VIOLATION` error (a
  Baseline-level guardrail, design.md §4.5) renders the same way — same
  panel, same jump-to-file behavior — since it blocks a publish exactly
  like a structural error does.
- Non-blocking guardrail findings (Standard/Advanced/Regulatory checks the
  tenant has enabled) render separately in `GuardrailWarningsPanel` (§9.18),
  directly below `ValidationResultsPanel`. Warnings never disable the
  "Publish" button — they're advisory, matching design.md §4.5's severity
  model.

### 11.4 "Edit" on a published skill = fork into a new draft

Given design.md's no-overwrite guarantee, "New Version" on `/skills/[id]`
calls `POST /api/v1/drafts { forkFrom: {id, version} }`, which server-side
copies every file from the published version into a fresh draft. The user
edits that draft exactly as in §11.1-11.3, then `Publish` runs the existing
`publish_skill` pipeline requiring a new, higher SemVer (enforced the same
way duplicate-publish already is — reusing the current version number is
just a duplicate-publish 409, no new rule needed). This is the entire
"edit and save" story for something already public: nothing is mutated in
place, ever.

### 11.5 Conflict handling (not full real-time collaboration)

If two people (e.g., two tenant members with write access to a shared
draft) save the same file within the same window, the second `PUT` wins
but the UI shows a non-blocking "This file changed since you last loaded
it — showing the latest version" notice and reloads that tab's content,
rather than silently discarding either person's intent without saying so.

## 12. State Management & Data Fetching

As built: server state (skills, drafts, shares, tenants) is read directly in
Server Components (`src/lib/*-api.ts`, all `jaasFetch` wrappers) and mutated
through Server Actions (`src/lib/actions.ts`), with `router.refresh()` for
cache invalidation after a mutation — not the TanStack-Query-centric
architecture originally planned below. This turned out to be the more
idiomatic fit for Next.js's App Router and was sufficient for every screen
actually built; `@tanstack/react-query` remains installed and the app is
still wrapped in a `QueryProvider`, but nothing calls `useQuery`/
`useMutation`. Revisit this section if a future screen needs client-side
polling, optimistic updates, or cross-tab cache sharing that the
Server-Component-first approach doesn't cover well.

Originally planned (superseded by the above):

1. Server state (skills, drafts, shares, tenants) lives entirely in
   TanStack Query — no duplicate Redux/Zustand store for the same data.
2. Ephemeral UI-only state (dialog open/closed, active editor tab, sidebar
   collapsed) uses local component state or React Context — introduced
   only where prop-drilling would otherwise cross more than 2 component
   levels.
3. Auth/session state comes from Auth.js's `useSession()`; the active
   tenant (for the switcher) is derived from the session's JWT claims
   (§4.3), not duplicated into a separate store.

## 13. Accessibility & Responsive Design

1. WCAG 2.1 AA target: all interactive elements keyboard-reachable and
   labeled (shadcn/ui + Radix primitives provide this by default for
   dialogs/dropdowns/menus — verified per component, not assumed).
2. Color contrast: every text/background pairing in §8.1 checked against
   AA thresholds (4.5:1 body text, 3:1 large text) in both light and dark
   mode.
3. Breakpoints: sidebar auto-collapses to icon rail under 1024px, to an
   off-canvas drawer under 640px. The file-tree + editor authoring screen
   is the one view explicitly documented as desktop-first (a split
   tree/editor layout is not a good use of a phone screen) — it remains
   usable but not optimized below 768px.

## 14. Security Considerations

1. The registry JWT never reaches client-side JavaScript (§4.2) — mitigates
   XSS token theft; a compromised client script can at most ride the
   existing session's server-proxied requests, not exfiltrate a
   long-lived bearer token.
2. CSRF: Auth.js's session cookie is `SameSite=Lax` + `httpOnly`; all
   state-changing calls go through Next.js route handlers (same-origin),
   never a direct cross-origin fetch from the browser to the registry API.
3. CSP: default-src 'self'; Monaco's web workers and Google's OAuth
   redirect domains explicitly allow-listed, nothing else.
4. File content in drafts is user-supplied — rendered strictly as text in
   Monaco (never `dangerouslySetInnerHTML`'d as markup) except `README.md`
   preview, which goes through a sanitizing markdown renderer
   (`rehype-sanitize`) before display.

## 15. Non-Functional Requirements

1. Browse page interactive within 2s on a median corpus-sized result set
   (aligns with design.md §9.1's 150ms search p95 — the budget here is
   almost entirely client render/hydration, not the API call).
2. Editor workspace: opening a draft with the full canonical file set
   (design.md §4.1) renders and becomes editable within 1s.
3. Lighthouse accessibility score ≥ 95 on `/skills` and `/skills/[id]`.
