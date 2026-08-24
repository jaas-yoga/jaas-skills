"""Cold-start index builder: rebuild the full in-memory index from storage alone.

Design ref: design.md §3.2 design note 1, §8.2.1 ("restart and rebuild index
from storage metadata"), §9.1.4 (SLO), implementation-plan.md Phase 5 task 1.
"""

from __future__ import annotations

import time

from jaas_registry.index.ingest import parse_published_record
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.observability.metrics import index_build_duration_seconds
from jaas_registry.storage.base import ObjectStore
from jaas_registry.storage.keys import TAG_MANIFEST_SUFFIX, TAG_PREFIX


def bootstrap_index(store: ObjectStore) -> InMemoryIndex:
    """List every published tag under the storage root and rebuild the index
    entirely from those records — no database, per design.md §1.1.5. Duration
    is observed against the design.md §9.1.4 cold-start SLO (<= 120s)."""
    start = time.monotonic()
    index = InMemoryIndex()
    for key in store.list_prefix(TAG_PREFIX):
        if not key.endswith(TAG_MANIFEST_SUFFIX):
            continue
        entry = parse_published_record(store.read(key))
        index.put(entry)
    index_build_duration_seconds.observe(time.monotonic() - start)
    return index
