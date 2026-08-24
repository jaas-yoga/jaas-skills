"""Authorization seam used by the API gateway. Design ref: design.md §3.4, §5.3.1.

Phase 3 wired `AllowAllAuthorizer` as a placeholder; Phase 4 adds `JwtAuthorizer`
(policy.py), a real implementation of this same protocol backed by JWT
validation and hierarchical scope matching.
"""

from __future__ import annotations

from typing import Protocol


class Authorizer(Protocol):
    def check(
        self, *, token: str | None, tenant_header: str | None, required_permissions: tuple[str, ...]
    ) -> None:
        """Raise JaasError(UNAUTHORIZED) if the caller may not access a skill
        requiring `required_permissions`. `token` is the bearer token from the
        Authorization header (if any); `tenant_header` is an optional caller-
        declared tenant context used only when tenant boundary enforcement is on.
        """
        ...


class AllowAllAuthorizer:
    def check(
        self, *, token: str | None, tenant_header: str | None, required_permissions: tuple[str, ...]
    ) -> None:
        return None
