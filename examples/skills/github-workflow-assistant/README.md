# github-workflow-assistant

An example skill package (design.md §4.1 canonical layout) published into the
JaaS Skills as a working demo — public, visible to every tenant, no
sign-in required to view it in `/skills`.

It teaches an AI agent this repo's git/GitHub conventions: how to check
state before acting, how to write commit messages, how to open a PR or issue
via the `gh` CLI, and how to verify CI status before reporting success. See
`SKILL.md` for the actual instructions the skill carries — written in
Claude Code's own skill format (YAML frontmatter + instructions), since
that's what this skill actually targets.

## Files

- `manifest.yaml` — identity, owner, category/tags, runtime compatibility.
- `schema.json` — `task`/`repo` in, `summary`/`actionsTaken`/`url` out.
- `permissions.yaml` — `network:egress` (calls the GitHub API via `gh`),
  `fs:read` (reads local git state).
- `dependencies.yaml` — depends on `rune.devtools.git-fundamentals
  >=1.0.0,<2.0.0` (the companion example skill), resolved and
  cycle-checked at publish time (design.md §4.4). Publish
  `git-fundamentals` first, or this publish fails with `MISSING_DEPENDENCY`.
- `SKILL.md` — the skill's actual content (its `entrypoint`).

## Publishing (or re-publishing after an edit)

```bash
uv run runectl validate examples/skills/github-workflow-assistant
uv run runectl publish examples/skills/github-workflow-assistant
./run.sh restart   # the running API only re-scans storage at startup
```

`runectl publish` has no session/tenant concept, so it always publishes as
`visibility: public`, `ownerTenant: local` — exactly what "visible to every
tenant" requires. To publish a new version, bump `version` in
`manifest.yaml` first (duplicate id+version publishes are rejected with
409).
