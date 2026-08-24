"""Share grant persistence. ui-design.md §5.1 item 4, §7.

Same local-prototype, no-database convention as authn/. Grants are keyed
`<skill_id>__<grant_id>.json` so `list_for_skill` (the common case: rendering
a skill's ShareDialog) is a direct glob, not a full scan; `list_for_grantee`
("shared with me") does scan every grant file, which is fine at the grant
counts a local prototype actually has (see ui-implementation-plan.md risk
register item 2 for what changes if that stops being true).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from jaas_registry.sharing.models import GranteeType, ShareGrant, SharePermission


def _grant_from_dict(data: dict) -> ShareGrant:
    return ShareGrant(
        id=data["id"],
        skill_id=data["skill_id"],
        grantee_type=GranteeType(data["grantee_type"]),
        grantee_id=data["grantee_id"],
        permission=SharePermission(data["permission"]),
        granted_by=data["granted_by"],
        granted_at=data["granted_at"],
    )


class GrantStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "share_grants"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, skill_id: str, grant_id: str) -> Path:
        return self._dir / f"{skill_id}__{grant_id}.json"

    def create(
        self,
        *,
        skill_id: str,
        grantee_type: GranteeType,
        grantee_id: str,
        permission: SharePermission,
        granted_by: str,
    ) -> ShareGrant:
        grant = ShareGrant(
            id=f"grant_{uuid.uuid4().hex[:20]}",
            skill_id=skill_id,
            grantee_type=grantee_type,
            grantee_id=grantee_id,
            permission=permission,
            granted_by=granted_by,
            granted_at=datetime.now(UTC).isoformat(),
        )
        self._path(skill_id, grant.id).write_text(json.dumps(asdict(grant)))
        return grant

    def get(self, *, skill_id: str, grant_id: str) -> ShareGrant | None:
        path = self._path(skill_id, grant_id)
        if not path.exists():
            return None
        return _grant_from_dict(json.loads(path.read_text()))

    def revoke(self, *, skill_id: str, grant_id: str) -> bool:
        path = self._path(skill_id, grant_id)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed

    def list_for_skill(self, skill_id: str) -> list[ShareGrant]:
        return [
            _grant_from_dict(json.loads(path.read_text()))
            for path in self._dir.glob(f"{skill_id}__*.json")
        ]

    def list_for_grantee(self, *, grantee_type: GranteeType, grantee_id: str) -> list[ShareGrant]:
        matches = []
        for path in self._dir.glob("*.json"):
            grant = _grant_from_dict(json.loads(path.read_text()))
            if grant.grantee_type == grantee_type and grant.grantee_id == grantee_id:
                matches.append(grant)
        return matches
