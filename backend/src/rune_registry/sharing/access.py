"""Visibility/sharing access rule. ui-design.md §5.4, §6.2.

`can_view` implements the exact rule design.md's search/metadata endpoints
must apply for every request:

    visibility == PUBLIC
      OR owner_tenant == caller.tenant
      OR exists ShareGrant(skill_id, grantee_type=USER, grantee_id=caller.user)
      OR exists ShareGrant(skill_id, grantee_type=TENANT, grantee_id=caller.tenant)

Evaluated per-request against the caller's claims — never baked into the
index itself, since the same index entry is visible/invisible to different
callers (ui-design.md §5.4).
"""

from __future__ import annotations

from dataclasses import dataclass

from rune_registry.authn.pat import PatStore
from rune_registry.authn.tenants import MembershipStore
from rune_registry.authz.jwt_validation import decode_token
from rune_registry.common.config import Settings
from rune_registry.common.errors import RuneError
from rune_registry.index.models import IndexEntry, Visibility
from rune_registry.sharing.grants import GrantStore
from rune_registry.sharing.models import GranteeType


@dataclass(frozen=True)
class CallerContext:
    """The identity a request is evaluated against. Both fields are None for
    an anonymous (no bearer token, or an invalid/expired one) caller — search
    and metadata stay reachable without auth (design.md's existing behavior),
    just scoped down to PUBLIC-only for that caller."""

    user_id: str | None = None
    tenant_id: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None


ANONYMOUS = CallerContext()


def resolve_caller_context(
    token: str | None, *, settings: Settings, pat_store: PatStore | None = None
) -> CallerContext:
    """Best-effort: search/metadata stay reachable without auth at all
    (design.md's pre-existing behavior), so a missing, expired, or otherwise
    invalid token degrades to ANONYMOUS rather than rejecting the request —
    unlike authz/policy.py's JwtAuthorizer, which is deny-by-default for the
    endpoints that actually require a permission grant. Presenting a bad
    token here isn't a permission failure, it's just not being able to
    personalize the result. A revoked personal access token (ui-design.md
    §4.4) degrades the same way, for the same reason."""
    if not token:
        return ANONYMOUS
    try:
        claims = decode_token(
            token,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    except RuneError:
        return ANONYMOUS
    if claims.pat_id is not None:
        record = pat_store.get(claims.pat_id) if pat_store else None
        if record is None:
            return ANONYMOUS
    return CallerContext(user_id=claims.subject, tenant_id=claims.tenant)


def can_view(entry: IndexEntry, *, caller: CallerContext, grants: GrantStore | None = None) -> bool:
    if entry.visibility == Visibility.PUBLIC:
        return True
    if not caller.is_authenticated:
        return False
    if caller.tenant_id is not None and entry.owner_tenant == caller.tenant_id:
        return True
    if grants is None:
        return False
    for grant in grants.list_for_skill(entry.id):
        if grant.grantee_type == GranteeType.USER and grant.grantee_id == caller.user_id:
            return True
        if grant.grantee_type == GranteeType.TENANT and grant.grantee_id == caller.tenant_id:
            return True
    return False


def can_manage_sharing(
    entry: IndexEntry, *, caller: CallerContext, memberships: MembershipStore
) -> bool:
    """Who may create/revoke share grants on a skill (ui-design.md §5.2):
    the skill's owning user, or an admin of its owning tenant."""
    if caller.user_id is None:
        return False
    if caller.user_id == entry.owner_user:
        return True
    membership = memberships.get(tenant_id=entry.owner_tenant, user_id=caller.user_id)
    return membership is not None and membership.role.value == "admin"
