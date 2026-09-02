"""Identity data model. ui-design.md §5.1, §6.3.

authn/ is distinct from authz/: authn/ establishes *who* a caller is (Google
sign-in, users, tenants, membership) and mints the registry's own JWTs;
authz/ only ever validates a JWT already minted, unchanged by any of this.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TenantRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class TenantKind(StrEnum):
    PERSONAL = "personal"
    ORGANIZATION = "organization"


@dataclass(frozen=True)
class User:
    id: str
    google_sub: str
    email: str
    name: str
    picture: str | None = None
    # User-set override of `name`, shown everywhere in place of it once set.
    # Unlike `name`/`picture` (refreshed from Google on every sign-in,
    # `users.py::find_or_create`), this is never touched by sign-in — only
    # `users.py::set_display_name` changes it.
    display_name: str | None = None

    @property
    def effective_name(self) -> str:
        return self.display_name or self.name


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    kind: TenantKind = TenantKind.ORGANIZATION


@dataclass(frozen=True)
class Membership:
    user_id: str
    tenant_id: str
    role: TenantRole = TenantRole.MEMBER
