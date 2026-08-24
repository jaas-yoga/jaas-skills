"""Pending tenant invites, keyed by email. ui-design.md §6, §10.5's "People"
tab fallback: inviting someone who hasn't signed in yet stores a pending
membership, resolved into a real one on that email's first Google sign-in
(see AuthService.sign_in_with_google).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from rune_registry.authn.models import TenantRole


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _email_key(email: str) -> str:
    return hashlib.sha256(_normalize_email(email).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class PendingInvite:
    tenant_id: str
    email: str
    role: TenantRole
    invited_by: str
    invited_at: str


class InviteStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "pending_invites"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str, email: str) -> Path:
        return self._dir / f"{tenant_id}__{_email_key(email)}.json"

    def create(
        self, *, tenant_id: str, email: str, role: TenantRole, invited_by: str
    ) -> PendingInvite:
        invite = PendingInvite(
            tenant_id=tenant_id,
            email=_normalize_email(email),
            role=role,
            invited_by=invited_by,
            invited_at=datetime.now(UTC).isoformat(),
        )
        self._path(tenant_id, email).write_text(json.dumps(asdict(invite)))
        return invite

    def list_for_tenant(self, tenant_id: str) -> list[PendingInvite]:
        invites = []
        for path in self._dir.glob(f"{tenant_id}__*.json"):
            data = json.loads(path.read_text())
            invites.append(PendingInvite(**{**data, "role": TenantRole(data["role"])}))
        return invites

    def pop_for_email(self, email: str) -> list[PendingInvite]:
        """Finds every pending invite for this email across all tenants,
        deletes them, and returns what was found — called once per sign-in
        so each invite is resolved into a real membership exactly once."""
        normalized = _normalize_email(email)
        matches = []
        for path in self._dir.glob(f"*__{_email_key(normalized)}.json"):
            data = json.loads(path.read_text())
            matches.append(PendingInvite(**{**data, "role": TenantRole(data["role"])}))
            path.unlink(missing_ok=True)
        return matches
