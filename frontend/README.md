# rune_ui

The web UI for JaaS Skills: Google sign-in, skill search and
browsing, the drafts authoring workflow, tenant/sharing administration, and
publish-time guardrail policy management. Next.js 16 App Router +
TypeScript + Tailwind v4 + shadcn/ui + Auth.js v5.

This repo is independent of the backend it talks to — no shared code,
only HTTP. It depends on two sibling repos at runtime (not at build time):

- **`../rune_skills`** — the Python/FastAPI registry backend. Provides
  every API this app calls (search, drafts, tenants, sharing, guardrail
  policy) and validates the Google ID token this app forwards to it on
  sign-in.
- **`../rune_guardrail`** — the standalone guardrails scanning service.
  This app never talks to it directly; only the backend does.

Both are optional for `run.sh` (see below) — this app runs standalone
against whatever `RUNE_API_URL` points at, including a backend that isn't
managed by this script at all.

## Running it

```bash
cp .env.local.example .env.local   # fill in AUTH_SECRET, AUTH_GOOGLE_ID/SECRET
./run.sh                            # starts guardrails -> api -> web
```

`./run.sh status` / `./run.sh stop` / `./run.sh logs [api|web|guardrails]`
manage all three. By default it expects `../rune_skills` and
`../rune_guardrail` as sibling checkouts; override with `RUNE_BACKEND_DIR`
/ `RUNE_GUARDRAILS_DIR`, or set either to `""` to skip starting it (e.g. if
a backend is already running elsewhere — point `RUNE_API_URL` at it
instead). Run `./run.sh --help` for the full list of environment
overrides.

Sign-in requires a dedicated Google OAuth client (see
`.env.local.example`) with `http://localhost:3027/api/auth/callback/google`
registered as an authorized redirect URI, and the backend started with
the *same* client id so it validates ID tokens against the right
audience — `run.sh` wires this up automatically from this repo's own
`.env.local`.

For plain frontend-only work (`npm run dev`, `npm run build`, `npm run
lint`), no backend is required to start the dev server, only to exercise
any page that calls it.

## Design docs

The UI's design (`ui-design.md`) and phased delivery plan
(`ui-implementation-plan.md`) live in the sibling `../rune_skills` repo —
they're cross-cutting documents that also describe the backend changes
(auth, sharing, drafts, tenants) built to support this app, so they stay
with the backend rather than being duplicated or forked here. See
`.claude/skills/rune-frontend-conventions/SKILL.md` in this repo for
this codebase's own conventions and gotchas.
