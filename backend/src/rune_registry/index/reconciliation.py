"""Reconciliation: periodic scan that repairs index drift against storage.

Design ref: design.md §8.2.2 ("periodic reconciliation scan repairs index
drift"), implementation-plan.md Phase 5 task 3.

Deletions aren't modeled: design.md's storage layer is append-only/immutable
(§2.1.1), so a published tag never disappears — reconciliation only needs to
repair missing or stale entries, never remove ones no longer in storage.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from rune_registry.index.bootstrap import bootstrap_index
from rune_registry.index.store import InMemoryIndex
from rune_registry.storage.base import ObjectStore


def compute_checksum(index: InMemoryIndex) -> str:
    parts = []
    for skill_id in index.all_ids():
        for version in index.list_versions(skill_id):
            entry = index.get(skill_id, version)
            parts.append(f"{skill_id}@{version}:{entry.digest}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


@dataclass(frozen=True)
class ReconciliationReport:
    repaired: tuple[str, ...]
    checksum_before: str
    checksum_after: str

    @property
    def drift_detected(self) -> bool:
        return self.checksum_before != self.checksum_after


def reconcile(index: InMemoryIndex, store: ObjectStore) -> ReconciliationReport:
    """Rebuild a fresh view from storage and overwrite any index entry that
    doesn't match it — repairs both missing entries (event never arrived) and
    stale ones (event applied against out-of-date data)."""
    checksum_before = compute_checksum(index)
    authoritative = bootstrap_index(store)

    repaired = []
    for skill_id in authoritative.all_ids():
        for version in authoritative.list_versions(skill_id):
            authoritative_entry = authoritative.get(skill_id, version)
            if index.get(skill_id, version) != authoritative_entry:
                index.put(authoritative_entry)
                repaired.append(f"{skill_id}@{version}")

    checksum_after = compute_checksum(index)
    return ReconciliationReport(
        repaired=tuple(repaired), checksum_before=checksum_before, checksum_after=checksum_after
    )
