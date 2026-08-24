"""Tenant and membership persistence. ui-design.md §5.1-5.2, §7.

Same local-prototype, no-database convention as users.py. A user's personal
tenant id is deterministically derived from their user id (one per user, by
construction — `ensure_personal_tenant` is idempotent with no index needed,
the same trick users.py uses for google_sub -> user id).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from jaas_registry.authn.models import Membership, Tenant, TenantKind, TenantRole


def personal_tenant_id(user_id: str) -> str:
    """Public so callers that need the id without touching the store can
    compute it too (e.g. index/demo_seed.py, which needs an owner_tenant
    before that user has ever actually signed in and had the tenant
    created)."""
    return f"tnt_personal_{user_id.removeprefix('usr_')}"


class TenantStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "tenants"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str) -> Path:
        return self._dir / f"{tenant_id}.json"

    def get(self, tenant_id: str) -> Tenant | None:
        path = self._path(tenant_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return Tenant(id=data["id"], name=data["name"], kind=TenantKind(data["kind"]))

    def create(self, *, name: str, kind: TenantKind = TenantKind.ORGANIZATION) -> Tenant:
        tenant = Tenant(id=f"tnt_{uuid.uuid4().hex[:24]}", name=name, kind=kind)
        self._path(tenant.id).write_text(json.dumps(asdict(tenant)))
        return tenant

    def ensure_personal_tenant(self, *, user_id: str, display_name: str) -> Tenant:
        tenant_id = personal_tenant_id(user_id)
        existing = self.get(tenant_id)
        if existing is not None:
            return existing
        tenant = Tenant(id=tenant_id, name=f"{display_name}'s Workspace", kind=TenantKind.PERSONAL)
        self._path(tenant.id).write_text(json.dumps(asdict(tenant)))
        return tenant


class MembershipStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "memberships"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str, user_id: str) -> Path:
        return self._dir / f"{tenant_id}__{user_id}.json"

    def add(self, *, tenant_id: str, user_id: str, role: TenantRole) -> Membership:
        membership = Membership(user_id=user_id, tenant_id=tenant_id, role=role)
        self._path(tenant_id, user_id).write_text(json.dumps(asdict(membership)))
        return membership

    def get(self, *, tenant_id: str, user_id: str) -> Membership | None:
        path = self._path(tenant_id, user_id)
        if not path.exists():
            return None
        return _membership_from_dict(json.loads(path.read_text()))

    def list_for_user(self, user_id: str) -> list[Membership]:
        return [
            _membership_from_dict(json.loads(path.read_text()))
            for path in self._dir.glob(f"*__{user_id}.json")
        ]

    def list_for_tenant(self, tenant_id: str) -> list[Membership]:
        return [
            _membership_from_dict(json.loads(path.read_text()))
            for path in self._dir.glob(f"{tenant_id}__*.json")
        ]


def _membership_from_dict(data: dict) -> Membership:
    return Membership(
        user_id=data["user_id"], tenant_id=data["tenant_id"], role=TenantRole(data["role"])
    )
