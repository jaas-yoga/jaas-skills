"""Scratch space for a custom guardrail rule being authored, before it's
published into CustomGuardrailRuleStore's immutable version history.
Mirrors drafts/store.py's shape (one JSON file per draft, deleted on
successful publish) — far simpler content since a rule is one record, not
a package of files needing git-sync/packaging.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from jaas_registry.guardrails.custom_rules import CustomGuardrailRule


@dataclass(frozen=True)
class CustomGuardrailRuleDraft:
    id: str  # "cgrdraft_<hex>"
    tenant_id: str
    slug: str
    name: str
    description: str
    category: str
    severity: str
    standard_ref: str
    kind: str
    config: dict
    version: str
    # None for a brand-new rule; the version this draft was forked from
    # when editing an already-published rule (ui-design-analogous "New
    # Version" on a skill) — purely informational, doesn't constrain what
    # `version` itself can be set to.
    forked_from_version: str | None
    created_by: str
    created_at: str
    updated_at: str


def _next_patch_version(version: str) -> str:
    """"1.2.3" -> "1.2.4" — a starting suggestion for a forked draft, not
    an enforced constraint (the author can set any version at publish
    time). Falls back to the input unchanged if it isn't three dot-
    separated integers, rather than raising — this is only ever a
    pre-filled form value the author can freely edit."""
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return version
    major, minor, patch = parts
    return f"{major}.{minor}.{int(patch) + 1}"


class CustomGuardrailRuleDraftStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "custom_guardrail_drafts"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, draft_id: str) -> Path:
        return self._dir / f"{draft_id}.json"

    def get(self, draft_id: str) -> CustomGuardrailRuleDraft | None:
        path = self._path(draft_id)
        if not path.exists():
            return None
        return CustomGuardrailRuleDraft(**json.loads(path.read_text()))

    def list_for_tenant(self, tenant_id: str) -> list[CustomGuardrailRuleDraft]:
        drafts = [
            CustomGuardrailRuleDraft(**json.loads(path.read_text()))
            for path in self._dir.glob("*.json")
        ]
        return sorted(
            (d for d in drafts if d.tenant_id == tenant_id),
            key=lambda d: d.created_at,
            reverse=True,
        )

    def create(
        self,
        *,
        tenant_id: str,
        created_by: str,
        fork_from: CustomGuardrailRule | None = None,
    ) -> CustomGuardrailRuleDraft:
        now = datetime.now(UTC).isoformat()
        draft = CustomGuardrailRuleDraft(
            id=f"cgrdraft_{secrets.token_hex(12)}",
            tenant_id=tenant_id,
            slug=fork_from.slug if fork_from else "",
            name=fork_from.name if fork_from else "",
            description=fork_from.description if fork_from else "",
            category=fork_from.category if fork_from else "",
            severity=fork_from.severity if fork_from else "WARN",
            standard_ref=fork_from.standard_ref if fork_from else "",
            kind=fork_from.kind if fork_from else "",
            config=fork_from.config if fork_from else {},
            version=_next_patch_version(fork_from.version) if fork_from else "1.0.0",
            forked_from_version=fork_from.version if fork_from else None,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self._path(draft.id).write_text(json.dumps(asdict(draft)))
        return draft

    def update(
        self,
        draft_id: str,
        *,
        slug: str,
        name: str,
        description: str,
        category: str,
        severity: str,
        standard_ref: str,
        kind: str,
        config: dict,
        version: str,
    ) -> CustomGuardrailRuleDraft | None:
        existing = self.get(draft_id)
        if existing is None:
            return None
        updated = CustomGuardrailRuleDraft(
            id=existing.id,
            tenant_id=existing.tenant_id,
            slug=slug,
            name=name,
            description=description,
            category=category,
            severity=severity,
            standard_ref=standard_ref,
            kind=kind,
            config=config,
            version=version,
            forked_from_version=existing.forked_from_version,
            created_by=existing.created_by,
            created_at=existing.created_at,
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._path(updated.id).write_text(json.dumps(asdict(updated)))
        return updated

    def delete(self, draft_id: str) -> bool:
        path = self._path(draft_id)
        if not path.exists():
            return False
        path.unlink()
        return True
