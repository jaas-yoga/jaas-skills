# Changelog

Feature-level record of what's shipped, newest first. Each entry names
every repo it touched — this is a two-repo system (`rune_skills` backend +
`rune_ui` frontend), plus the standalone `rune_guardrails` scanning
service where noted. Nothing here has been released as a version tag; this
tracks what's running in the local dev stack (`run.sh`).

## Fix: A Publish Was Invisible to Search/Metadata Until the Server Restarted

*Repo: `rune_skills`.*

`publish_skill()` only ever wrote the blob/tag to object storage — the
running `api` process's in-memory search index (`InMemoryIndex`) was only
ever populated once, at server startup (`bootstrap_index(store)` scanning
whatever was already published). There was no live update path: the
`EventBus`/`IndexEventConsumer` machinery already in the codebase
(`index/events.py`, `index/consumer.py`) was built for a future multi-
replica deployment but was never actually wired into `create_app()`, so a
skill published or released *after* the server started (via the web UI's
draft publish, or the git-native CI release endpoint) simply didn't show
up in `GET /api/v1/skills` (search) or `GET /skills/{id}/versions/{version}`
until the next restart.

Fixed by re-indexing synchronously, in the same request, right after
`publish_skill()` succeeds — `index.put(parse_published_record(store.read(tag_key)))`
in both `api/draft_routes.py::publish_draft` and
`api/release_routes.py::release_skill` (including its duplicate-publish
retry branch). No background consumer/event bus needed for this
single-process deployment; the existing `EventBus` abstraction is left
alone for whenever a real multi-replica setup exists.

## Guardrail Certification Pipeline

*Repos: `rune_skills`, `rune_ui`. `rune_guardrails`: unchanged.*

Every publish now computes a **persisted, queryable certification** —
previously a guardrail WARN finding only ever reached a structured log
line (`PublishAuditEvent.guardrail_warning_ids`); there was no way to ask
afterward "what did this published version actually pass, and at what
level?"

- Certification is a per-level (1–4) attestation: `certified` (every check
  at that level was attempted and clean), `attempted_with_findings` (attempted,
  at least one WARN), or `not_attempted` (tenant never enabled it). The
  headline `highestCertifiedLevel` is contiguous from Level 1 — a gap at a
  lower level caps the number even if a higher level individually looks
  clean, so an untested baseline can never look implicitly passed.
- Computed once, at publish time, by a new pure function
  (`guardrails/certification.py::compute_certification`), and threaded
  through all three publish front doors (`cli.py`, the web UI's draft
  publish, and the git-native CI release endpoint) via
  `artifact/publish.py::publish_skill()`.
- Persisted on the published record itself (`IndexEntry` +
  `serialize_published_record`/`parse_published_record`), the same pattern
  already used for git provenance (`sourceRepo`/`sourceCommit`/etc.) —
  optional fields, backward-compatible with records written before this
  existed (they simply show no certification, not a failure).
- **This is a point-in-time attestation, not a live status** — if the
  tenant later changes their guardrail policy, an already-published
  version's certification never changes retroactively. Every UI surface
  that shows it says so explicitly.
- Surfaced on `GET /skills/{id}/versions/{version}`, the draft publish
  response, and the CI release response. A **projected** certification
  (what you'd get if you published right now) also comes back from
  `POST /drafts/{id}/validate`, using the identical function.
- UI: a "Guardrail Certification" card on the published skill page (same
  visual pattern as the existing Provenance card, per-level breakdown,
  explicit "not a live status" disclaimer), and a "Projected certification:
  Level N" line in the draft workspace right after Validate.
- Key files: `guardrails/certification.py` (new), `artifact/publish.py`,
  `index/models.py`, `index/ingest.py`, `api/schemas.py`,
  `api/draft_routes.py`, `api/release_routes.py`,
  `components/skills/certification-card.tsx` (new),
  `components/drafts/certification-preview.tsx` (new),
  `lib/guardrail-level-meta.ts` (new, shared with the existing tenant
  policy editor).

## Per-Skill Git Directories

*Repo: `rune_skills`.*

One GitHub repo can now host multiple skills without their files
colliding at the root. Every new git-connected draft commits its files
under `<skill-id>/` (derived from `manifest.yaml`'s own `id`, sanitized)
instead of the repo root, from its very first commit.

- A draft connected before this existed keeps its flat history until an
  explicit, one-time **"Move to directory"** action (new endpoint
  `POST /drafts/{id}/git/move-to-directory`) moves everything into the
  right folder in a single atomic commit — never implied automatically by
  a routine save.
- Key files: `drafts/models.py` (`git_subdirectory`), `drafts/git_sync.py`
  (`skill_directory_name`, `prefix_changes`), `api/draft_routes.py`.

## Draft Saves: Commit-Message-Gated Git Sync

*Repo: `rune_skills`, `rune_ui`.*

Every keystroke-driven autosave used to push a commit to the connected
repo — noisy, unreviewable history. Now:

- The debounced autosave only ever writes locally.
- The explicit **Save Draft** button is the only thing that commits — for
  a git-connected draft it first prompts for a commit message.
- Creating a file, uploading one (drag-and-drop), and the sync-error Retry
  button still commit immediately, since those are deliberate one-off
  actions, not keystroke spam.
- Key files: `api/schemas.py` (`PutFileRequest.syncToGit`/`commitMessage`),
  `api/draft_routes.py`, `components/drafts/draft-workspace.tsx`.

## Draft Editor: Folder-Aware File Creation + Drag-and-Drop Upload

*Repo: `rune_ui`.*

- "New File" now offers a folder destination picker when the draft already
  has folders, instead of requiring the folder path to be typed by hand.
- Files can be dragged from the OS straight into the FILES panel — dropped
  on empty space lands at the root, dropped on a folder (or a file inside
  one) lands in that folder, with a highlighted drop target while dragging.
- Key files: `lib/file-tree.ts` (`listFolderPaths`), `components/drafts/file-tree.tsx`.

## Draft Editor: Full Syntax Highlighting by File Type

*Repo: `rune_ui`.*

Monaco's language mode was already wired per-file but the extension map
only covered the exact canonical package files. Broadened to shell
scripts, TOML/INI, SQL, HTML/CSS, XML, reStructuredText, more JS/TS
variants, and extensionless files (`Dockerfile`, `Makefile`) matched by
name — `.py`/`.md`/`.yaml`/`.json` already worked correctly.

- Key file: `lib/monaco-language.ts`.

## Draft Editor: FILES Panel Scroll Fix

*Repo: `rune_ui`.*

The workspace's outer height was computed with a fragile
`calc(100dvh-3.5rem)` that double-counted the page's own padding,
starving the FILES panel of the height it needed for its own
`overflow-y-auto` to kick in with a long file list. Replaced with a proper
`h-full`/`min-h-0` chain.

- Key file: `components/drafts/draft-workspace.tsx`.

## Create Skill: Inline Destination/Repo/Branch Picker

*Repo: `rune_ui`.*

Replaced the card-based "where should this draft live?" modal dialog with
an inline panel (no popup) with chained dropdowns: Local vs. GitHub repo,
then — only for GitHub — a repository dropdown restricted to already-
Connected Repos, then a branch dropdown (or a name field, when the repo is
genuinely empty and its first commit will create the branch). Buttons sit
on the same row as the fields.

- Key file: `components/drafts/create-draft-dialog.tsx`.

## Git-Backed Drafts: Empty-Repo Bootstrap Fix

*Repo: `rune_skills`.*

GitHub's Git Data API (blob/tree/commit) cannot write anything — not even
an empty tree — to a repository with zero commits; every attempt 409s.
Switched the one-time empty-repo bootstrap to the Contents API
(`PUT .../contents/{path}`), which is the endpoint actually designed to
seed a brand-new repo's first commit.

- Key files: `authn/github_client.py` (`bootstrap_empty_repo`),
  `drafts/git_sync.py` (`create_working_branch`).

## Drafts List: Show the Skill's Name, Not the Draft ID

*Repo: `rune_skills`, `rune_ui`.*

The drafts list used to show the opaque `draft_<uuid>` id as the primary
label. Now shows `manifest.yaml`'s own `id` (read live off local disk, so
it stays current as it's edited) — the raw draft id still shows underneath
in small mono text.

- Key files: `api/draft_routes.py` (`DraftSummaryResponse.skillId`),
  `app/(app)/drafts/page.tsx`.
