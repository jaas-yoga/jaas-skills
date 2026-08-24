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
