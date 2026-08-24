"""In-memory inverted index. Design ref: design.md §3.2.1, §9.3.2.

"Shards" in the design refer to partitioning this structure's memory footprint
within one process, not distribution across replicas — see design.md §3.2 note 5.
This class is the single, full index each stateless replica holds.
"""

from __future__ import annotations

from jaas_registry.index.models import IndexEntry
from jaas_registry.index.semver_resolver import resolve_version


class InMemoryIndex:
    def __init__(self) -> None:
        self._entries: dict[str, dict[str, IndexEntry]] = {}

    def put(self, entry: IndexEntry) -> None:
        """Idempotent upsert, keyed by id+version — used for both cold-start
        bootstrap and incremental event patches (design.md §3.2 notes 1-2)."""
        self._entries.setdefault(entry.id, {})[entry.version] = entry

    def get(self, skill_id: str, version: str) -> IndexEntry | None:
        return self._entries.get(skill_id, {}).get(version)

    def get_resolved(self, skill_id: str, constraint: str | None) -> IndexEntry | None:
        versions = list(self._entries.get(skill_id, {}))
        resolved = resolve_version(versions, constraint)
        if resolved is None:
            return None
        return self.get(skill_id, resolved)

    def list_versions(self, skill_id: str) -> list[str]:
        return sorted(self._entries.get(skill_id, {}))

    def all_ids(self) -> list[str]:
        return sorted(self._entries)
