"""SemVer resolution: exact versions, range constraints, and alias channels.

Design ref: design.md §3.2.3 ("Resolve semantic versions and aliases"),
implementation-plan.md Phase 3 task 3.
"""

from __future__ import annotations

from functools import lru_cache

import semantic_version

ALIAS_LATEST = "latest"
ALIAS_STABLE = "stable"


@lru_cache(maxsize=8192)
def _parse_version(version: str) -> semantic_version.Version:
    return semantic_version.Version(version)


def resolve_version(versions: list[str], constraint: str | None) -> str | None:
    """Return the highest version in `versions` satisfying `constraint`.

    - `None` or "stable": highest non-prerelease version (falls back to the
      highest prerelease if there is no stable version at all).
    - "latest": highest version overall, prerelease included.
    - anything else: treated as a SimpleSpec range (e.g. ">=1.0.0,<2.0.0").

    Returns None if no version satisfies the constraint.

    A load test surfaced this as a hot path (implementation-plan.md Phase 7
    task 2, "tune... allocations"): search re-resolves every skill's version
    on every call, and the *same* version strings get re-parsed from scratch
    each time. `_parse_version` memoizes that parse process-wide.
    """
    if not versions:
        return None
    parsed = [_parse_version(v) for v in versions]

    if constraint in (None, ALIAS_STABLE):
        stable = [v for v in parsed if not v.prerelease]
        pool = stable or parsed
    elif constraint == ALIAS_LATEST:
        pool = parsed
    else:
        spec = semantic_version.SimpleSpec(constraint)
        pool = [v for v in parsed if spec.match(v)]

    if not pool:
        return None
    return str(max(pool))
