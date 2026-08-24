---
name: rune-frontend-conventions
description: Conventions and known gotchas for the rune-registry web app (this repo, rune_ui) — Next.js 16's breaking changes vs. training data, the Tailwind v4 CSS-first theming architecture, Auth.js v5 type-augmentation quirk, and the server-only backend API client pattern. Use when reading, writing, or reviewing any code in this repo.
---

# rune-registry web app conventions

Next.js 16 App Router + TypeScript + Tailwind v4 + shadcn/ui + Auth.js v5
(`next-auth@beta`). This repo is independent from the Python backend it
talks to (`../rune_skills`, a sibling checkout by convention) and from the
standalone guardrails service (`../rune_guardrail`) — no shared code, only
HTTP. `run.sh` in this repo's root starts all three together for local
dev. Read `../rune_skills/ui-design.md` and
`../rune_skills/ui-implementation-plan.md` for the full design and phase
plan this app implements — those docs are cross-cutting (they also cover
backend changes made to support the UI) so they stay in the backend repo
rather than being duplicated here.

## This is Next.js 16 — not what's in training data

`AGENTS.md` says this outright; the two changes that actually bite:

- **Middleware is renamed Proxy.** The file is `src/proxy.ts`, not
  `middleware.ts`; export a `proxy` function (default or named), not
  `middleware`. Behavior is otherwise unchanged (`export const config = {
  matcher: [...] }` still works). See `node_modules/next/dist/docs/01-app/
  01-getting-started/16-proxy.md` if in doubt.
- **`params` and `searchParams` are both `Promise<...>`** on every page/
  layout/route handler — `await params` / `await searchParams` before use.
- When genuinely unsure whether something changed, check
  `node_modules/next/dist/docs/` before trusting prior Next.js knowledge.

## Theming is CSS-first (Tailwind v4) — one file to edit

- `src/styles/tokens.css` is the **single source of truth** for every color
  and font, as bare `H S% L%` triples scoped per theme:
  `[data-theme="light|dark|ocean|violet"] { --background: ...; --brand: ...; }`.
- `src/app/globals.css`'s `@theme inline` block maps those to real Tailwind
  utilities: `--color-background: hsl(var(--background));` etc. — this is
  why components can use `bg-background`, `bg-brand`, `text-danger` as
  ordinary Tailwind classes.
- **Never hardcode a color or a raw Tailwind color utility** (`bg-indigo-600`,
  `text-slate-400`) in a component. Add or retune a theme by editing
  `tokens.css` only.
- Semantic tokens (`--success`, `--warning`, `--danger`, `--info`) keep the
  same hue across all four themes — only `--brand` and the neutral scale
  vary per theme. Don't repurpose a semantic color for decoration.
- `next-themes` drives the `data-theme` attribute (`ThemeProvider` in
  `src/components/theme/theme-provider.tsx`); the "mounted" `useEffect`
  guard in `theme-toggle.tsx`/`theme-picker.tsx` is next-themes' documented
  SSR-hydration-mismatch workaround, not a bug — don't "simplify" it away.

## Auth.js v5 type augmentation: target `@auth/core/jwt`, not `next-auth/jwt`

The `jwt` callback's `token` parameter type resolves through `@auth/core`'s
own `AuthConfig["callbacks"]`, which imports `JWT` directly from
`@auth/core/jwt` — augmenting `declare module "next-auth/jwt"` silently
fails to merge into that type (you'll see `token.yourField` typed as
`unknown`). The working augmentation lives in `src/types/next-auth.d.ts`:
`declare module "@auth/core/jwt"`. Session augmentation via
`declare module "next-auth"` works exactly as documented — only the JWT
side has this quirk.

## The registry's JWT never reaches the browser

- `src/lib/rune-api.ts`'s `runeFetch()` is the only way server code calls
  the Python backend — it's `"server-only"`, reads the session via `auth()`,
  and attaches `Authorization: Bearer <token>` itself. Never fetch the
  backend directly from a client component or expose the token to one.
- `src/lib/skills-api.ts` (search, metadata, shares) and future API modules
  should be thin wrappers over `runeFetch`, called from Server
  Components/Server Actions — not from `"use client"` code.

## Server Actions can't be inline inside a client-bundled file

If a component is pulled into a `"use client"` tree (imported and rendered
by any client component), an inline `async () => { "use server"; ... }`
closure inside it fails to build ("not allowed to define inline Server
Actions in Client Components"). Extract the action to its own `"use
server"` file instead — see `src/lib/actions.ts` (`signOutAction`,
`createShareGrantAction`, `revokeShareGrantAction`) — and import the named
export.

## Keeping the backend contract in sync

`src/lib/rune-api-types.ts` is a **hand-kept mirror** of
`../rune_skills/src/rune_registry/api/schemas.py`'s Pydantic response
models (a sibling repo now — no shared filesystem to grep against
automatically) — field names and shapes must match exactly. When the
backend schema changes, update the matching TypeScript type here in a
coordinated change across both repos; there is no codegen step.

## Components

- shadcn/ui components are vendored into `src/components/ui/` (not an npm
  black box) — add more with `npx shadcn@latest add <name>` (already
  initialized with the `nova`/`radix` preset); don't hand-roll a component
  that duplicates one already there.
- Any page under `src/app/(app)/` renders inside the authenticated
  `AppShell` automatically via that route group's `layout.tsx` — don't
  re-wrap it in a page component.
