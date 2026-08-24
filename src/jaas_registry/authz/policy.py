"""Deny-by-default authorization policy. Design ref: design.md §3.4 design note 1,
§7.2.3, implementation-plan.md Phase 4 tasks 3-4.

Every path that doesn't affirmatively pass (missing token, invalid token,
missing scope, tenant mismatch) raises JaasError(UNAUTHORIZED) — there is no
implicit-allow branch.
"""

from __future__ import annotations

from dataclasses import dataclass

from jaas_registry.authn.pat import PatStore
from jaas_registry.authz.jwt_validation import decode_token
from jaas_registry.authz.scopes import has_all_required_scopes
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.observability.metrics import authz_denied_total
from jaas_registry.observability.tracing import annotate_current_span_error


@dataclass(frozen=True)
class JwtAuthorizer:
    secret: str
    issuer: str
    audience: str
    enforce_tenant_boundary: bool = False
    # ui-design.md §4.4: only ever set on a personal-access-token claim
    # (authn/pat.py) — a normal session token has no pat_id, so this lookup
    # never runs for one. None here means "PAT revocation isn't checked",
    # not "PATs are trusted unconditionally" — see build_authorizer_from_settings.
    pat_store: PatStore | None = None

    def check(
        self, *, token: str | None, tenant_header: str | None, required_permissions: tuple[str, ...]
    ) -> None:
        """design.md §10.1.5 and §10.3.2: every denial path here increments
        authz_denied_total and annotates the current trace span, regardless of
        which specific check rejected the request."""
        try:
            self._check(
                token=token, tenant_header=tenant_header, required_permissions=required_permissions
            )
        except JaasError as exc:
            authz_denied_total.inc()
            annotate_current_span_error(exc)
            raise

    def _check(
        self, *, token: str | None, tenant_header: str | None, required_permissions: tuple[str, ...]
    ) -> None:
        if not token:
            raise JaasError(ErrorCode.UNAUTHORIZED, "missing bearer token")

        claims = decode_token(token, secret=self.secret, issuer=self.issuer, audience=self.audience)

        if claims.pat_id is not None:
            record = self.pat_store.get(claims.pat_id) if self.pat_store else None
            if record is None:
                raise JaasError(ErrorCode.UNAUTHORIZED, "personal access token has been revoked")

        if not has_all_required_scopes(claims.scopes, required_permissions):
            raise JaasError(
                ErrorCode.UNAUTHORIZED,
                f"token is missing required scope(s): {required_permissions}",
            )

        if self.enforce_tenant_boundary and claims.tenant != tenant_header:
            raise JaasError(
                ErrorCode.UNAUTHORIZED, "token tenant does not match request tenant context"
            )


def build_authorizer_from_settings(settings: Settings) -> JwtAuthorizer:
    return JwtAuthorizer(
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        enforce_tenant_boundary=settings.feature_flags.tenant_boundary_enforcement,
        pat_store=PatStore(settings.policy_dir),
    )
