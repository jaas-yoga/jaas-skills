"""Runtime compatibility filtering. Design ref: design.md §8.1.6 ("Runtime
mismatch: exclude during search"), implementation-plan.md Phase 3 task 4.

Query format: "family" (matches any skill declaring that runtime family) or
"family@version" (also checks the declared version range covers that version).
"""

from __future__ import annotations

import semantic_version

from rune_registry.index.models import IndexEntry


def runtime_matches(entry: IndexEntry, runtime_query: str) -> bool:
    family, _, version = runtime_query.partition("@")
    if family not in entry.runtime_families:
        return False
    if not version:
        return True
    version_range = entry.runtime_ranges.get(family)
    if version_range is None:
        return False
    return semantic_version.SimpleSpec(version_range).match(semantic_version.Version(version))
