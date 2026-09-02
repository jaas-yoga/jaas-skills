"""Governance record: business purpose, systems accessed, review date.

IMPLEMENTATION_PLAN.md Phase 3.3 — the Cloud Security Alliance's Agentic
Trust Framework (cited by ROADMAP.md) recommends a registry record per
agent identity: owning team, business purpose, systems accessed, review
date. "Owning team" reuses IndexEntry.owner_team (the publish-time
manifest owner) rather than a new field here — see IMPLEMENTATION_PLAN.md
Phase 3.3 for that decision.

Same sidecar pattern as artifact/yank.py (a mutable file written via
ObjectStore.write_object, overlaid onto an IndexEntry read from a tag by
index/bootstrap.py and index/consumer.py) — but keyed by skill_id alone,
not skill_id+version: a skill's business purpose doesn't vary per version
the way yank status does.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

from jaas_registry.index.models import IndexEntry
from jaas_registry.storage.base import ObjectStore
from jaas_registry.storage.keys import governance_key


@dataclass(frozen=True)
class GovernanceRecord:
    business_purpose: str | None
    systems_accessed: tuple[str, ...]
    review_date: str | None  # ISO date, e.g. "2026-12-01"
    updated_by: str
    updated_at: str  # ISO timestamp


def write_governance(store: ObjectStore, *, skill_id: str, record: GovernanceRecord) -> None:
    store.write_object(
        governance_key(skill_id),
        json.dumps(
            {
                "business_purpose": record.business_purpose,
                "systems_accessed": list(record.systems_accessed),
                "review_date": record.review_date,
                "updated_by": record.updated_by,
                "updated_at": record.updated_at,
            }
        ).encode(),
    )


def read_governance(store: ObjectStore, *, skill_id: str) -> GovernanceRecord | None:
    key = governance_key(skill_id)
    if not store.exists(key):
        return None
    obj = json.loads(store.read(key))
    return GovernanceRecord(
        business_purpose=obj.get("business_purpose"),
        systems_accessed=tuple(obj.get("systems_accessed") or ()),
        review_date=obj.get("review_date"),
        updated_by=obj["updated_by"],
        updated_at=obj["updated_at"],
    )


def apply_governance(entry: IndexEntry, record: GovernanceRecord | None) -> IndexEntry:
    """No-op when no sidecar exists yet — the entry's own None/()-default
    fields already cover that case (index/models.py)."""
    if record is None:
        return entry
    return dataclasses.replace(
        entry,
        business_purpose=record.business_purpose,
        systems_accessed=record.systems_accessed,
        governance_review_date=record.review_date,
    )
