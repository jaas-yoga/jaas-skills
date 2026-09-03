---
name: dependency-upgrade-assistant
description: Plans and executes a dependency version bump safely - reads changelogs/release notes for breaking changes, runs the test suite before and after, and stages the upgrade as its own commit separate from unrelated changes. Use when asked to upgrade, bump, or update a package dependency.
---

# Dependency Upgrade Assistant

Given a `package` and target `version` (or "latest"):

1. **Baseline first.** Run the existing test suite before touching
   anything - a failure after the bump is meaningless if the suite was
   already red.
2. **Read the actual changelog**, not just the version number. A major
   bump is a strong signal but not the only one - some ecosystems ship
   breaking changes in minor/patch releases; check the package's own
   release notes/CHANGELOG for every version between current and target.
3. **Check the lockfile ecosystem's own semver rules** (npm's `^`/`~`,
   Python's `>=,<`, etc.) before deciding whether a manifest-file edit is
   even needed, or whether re-resolving the lockfile alone gets you there.
4. **Upgrade one dependency at a time** when the ask is a single package -
   bundling multiple upgrades into one commit makes a regression
   impossible to bisect.
5. **Re-run the full test suite** after the bump, plus a manual smoke
   check of any code path the changelog flagged as changed, even if tests
   pass - changelogs often call out behavior tests don't cover.
6. **Check for deprecated API usage** the new version's changelog warns
   about, even if it still compiles/runs - flag it rather than leaving a
   silent future breakage.
7. **Commit the upgrade alone** - lockfile + manifest + any required code
   changes for the new API, nothing unrelated riding along.
8. **Report what changed**: old version, new version, whether tests
   passed, and any manual follow-up still needed.

Never silently widen an unrelated dependency's version range while
touching the lockfile - only the requested package's constraint should
change.
