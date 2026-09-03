---
name: monorepo-navigation
description: Finds the right package/app boundary in a monorepo before making a change - traces the workspace/build graph to know which packages a change actually affects and which build/test commands to scope to, instead of running everything or guessing package ownership. Use when asked to make a change in a monorepo, find which package owns something, or scope a build/test run.
---

# Monorepo Navigation

Given a `task` inside a monorepo:

1. **Find the workspace manifest first** (`pnpm-workspace.yaml`,
   `lerna.json`, `nx.json`, `pyproject.toml` workspace members, Bazel
   `WORKSPACE`, etc.) to get the real package list before guessing from
   directory names alone.
2. **Identify which package(s) actually own the code in question** - a
   file living under `packages/foo/` is not necessarily owned/built by
   `foo` alone if it's a shared symlinked/generated path; check the
   package's own manifest for what it declares as its source root.
3. **Trace the dependency graph, not just the folder tree**, to find what
   depends on the package you're changing (`nx graph`, `pnpm why`,
   `bazel query`, or the monorepo tool's equivalent) - a change to a
   shared package needs every dependent's tests run, not just its own.
4. **Scope build/test commands to the affected set**, using the monorepo
   tool's own affected/changed-since mechanism (`nx affected`, `turbo run
   --filter`, `bazel query --output=...`) rather than running the full
   workspace's build - full-workspace runs waste time and can mask which
   package actually failed.
5. **Respect existing package boundaries** - don't reach into another
   package's internals via a relative path when its public entrypoint
   (its `index.ts`/`__init__.py`/declared exports) is the intended
   boundary; import it the way any other consumer would.
6. **Check for a root-level lint/format config vs. per-package
   overrides** before assuming one config governs everything - many
   monorepos let packages opt out or extend the root config.
7. **Report which packages were touched and which were determined to be
   affected but not touched**, so the person reviewing knows the blast
   radius was actually considered, not assumed to be one package.
