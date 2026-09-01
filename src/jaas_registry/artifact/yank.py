"""Yank/unyank: a reversible post-publish status flag.

Publishing is immutable by design (storage/base.py's write_tag_if_absent) —
this deliberately does not touch that guarantee. Status lives in a sidecar
file next to the tag manifest (storage/keys.py's status_key), written via
the new ObjectStore.write_object (the one write path in that interface that
*is* meant to be overwritten), and is overlaid onto an IndexEntry read from
the tag by index/bootstrap.py and index/consumer.py — never folded into
index/ingest.py's (de)serialization of the manifest record itself.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

from jaas_registry.index.models import ArtifactStatus, IndexEntry
from jaas_registry.storage.base import ObjectStore
from jaas_registry.storage.keys import status_key


@dataclass(frozen=True)
class YankRecord:
    status: ArtifactStatus
    reason: str | None
    actor: str
    at: str  # ISO timestamp


def write_status(store: ObjectStore, *, skill_id: str, version: str, record: YankRecord) -> None:
    store.write_object(
        status_key(skill_id, version),
        json.dumps(
            {
                "status": record.status.value,
                "reason": record.reason,
                "actor": record.actor,
                "at": record.at,
            }
        ).encode(),
    )


def read_status(store: ObjectStore, *, skill_id: str, version: str) -> YankRecord | None:
    key = status_key(skill_id, version)
    if not store.exists(key):
        return None
    obj = json.loads(store.read(key))
    return YankRecord(
        status=ArtifactStatus(obj["status"]),
        reason=obj.get("reason"),
        actor=obj["actor"],
        at=obj["at"],
    )


def apply_status(entry: IndexEntry, record: YankRecord | None) -> IndexEntry:
    """No-op when no sidecar exists yet — the entry's own ACTIVE default
    already covers that case (index/models.py)."""
    if record is None:
        return entry
    return dataclasses.replace(entry, status=record.status)
