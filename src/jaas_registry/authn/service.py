"""Sign-in orchestration. ui-design.md §4.2 sequence diagram, §6.3.

Ties together google.py (verify), users.py/tenants.py (find-or-create), and
tokens.py (mint) into the single flow `POST /api/v1/auth/google` and
`POST /api/v1/auth/refresh` need. Kept separate from the route handlers
(api/auth_routes.py) so this orchestration is unit-testable without spinning
up FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass

from jaas_registry.authn.google import GoogleIdentityVerifier
from jaas_registry.authn.invites import InviteStore
from jaas_registry.authn.models import Membership, TenantRole, User
from jaas_registry.authn.tenants import MembershipStore, TenantStore
from jaas_registry.authn.tokens import RefreshTokenStore, mint_access_token
from jaas_registry.authn.users import UserStore
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError

# ui-design.md §6.1: base scopes every member gets; tenant:admin is layered
# on top for admins. skills:share lets an owner create/revoke share grants
# on their own skills regardless of tenant role (ui-design.md §5.2).
# skills:governance is the same story for PUT /skills/{id}/governance
# (IMPLEMENTATION_PLAN.md Phase 3.4) — an owner sets their own skill's
# governance record regardless of tenant role, same authorization tier as
# skills:share underneath (_require_share_management_access).
_MEMBER_SCOPES = ("skills:read", "skills:write", "skills:share", "skills:governance")
_ADMIN_SCOPES = (*_MEMBER_SCOPES, "tenant:admin")

# Local-dev-only stand-in for Google sign-in (Settings.dev_login_password).
# Keyed by email; the google_sub-shaped id keeps these on the exact same
# UserStore/TenantStore code path as a real Google identity (own personal
# tenant, ADMIN of it) rather than a parallel one.
_DEV_LOGIN_USERS: dict[str, str] = {
    "owner@jaas.local": "App Owner",
    "admin@jaas.local": "Admin",
}


def _scopes_for_role(role: TenantRole) -> tuple[str, ...]:
    return _ADMIN_SCOPES if role is TenantRole.ADMIN else _MEMBER_SCOPES


@dataclass(frozen=True)
class TenantMembershipView:
    tenant_id: str
    tenant_name: str
    role: TenantRole


@dataclass(frozen=True)
class AuthResult:
    access_token: str
    refresh_token: str
    user: User
    tenants: tuple[TenantMembershipView, ...]
    active_tenant_id: str


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        user_store: UserStore,
        tenant_store: TenantStore,
        membership_store: MembershipStore,
        refresh_token_store: RefreshTokenStore,
        invite_store: InviteStore | None = None,
        verifier: GoogleIdentityVerifier | None = None,
    ):
        self._settings = settings
        self._verifier = verifier
        self._users = user_store
        self._tenants = tenant_store
        self._memberships = membership_store
        self._refresh_tokens = refresh_token_store
        self._invites = invite_store

    def _tenant_views(self, memberships: list[Membership]) -> tuple[TenantMembershipView, ...]:
        views = []
        for membership in memberships:
            tenant = self._tenants.get(membership.tenant_id)
            if tenant is None:
                continue  # pragma: no cover - defensive; membership always created with its tenant
            views.append(
                TenantMembershipView(
                    tenant_id=tenant.id, tenant_name=tenant.name, role=membership.role
                )
            )
        return tuple(views)

    def _mint_for(self, *, user: User, tenant_id: str, role: TenantRole) -> str:
        return mint_access_token(
            user_id=user.id,
            email=user.email,
            name=user.name,
            tenant_id=tenant_id,
            tenant_role=role,
            scopes=_scopes_for_role(role),
            secret=self._settings.jwt_secret,
            issuer=self._settings.jwt_issuer,
            audience=self._settings.jwt_audience,
            ttl_seconds=self._settings.access_token_ttl_seconds,
        )

    def sign_in_with_google(
        self, google_id_token_jwt: str, *, requested_tenant_id: str | None = None
    ) -> AuthResult:
        if self._verifier is None:
            raise JaasError(
                ErrorCode.INVALID_GOOGLE_TOKEN,
                "Google sign-in is not configured for this deployment "
                "(JAAS_GOOGLE_CLIENT_ID unset)",
            )
        identity = self._verifier.verify(google_id_token_jwt)

        is_new_user = self._users.find_by_google_sub(identity.sub) is None
        user = self._users.find_or_create(
            google_sub=identity.sub,
            email=identity.email,
            name=identity.name,
            picture=identity.picture,
        )

        return self._finish_sign_in(
            user, is_new_user=is_new_user, requested_tenant_id=requested_tenant_id
        )

    def sign_in_with_dev_credentials(
        self, email: str, password: str, *, requested_tenant_id: str | None = None
    ) -> AuthResult:
        """Local-dev-only alternative to Google sign-in — a fixed pair of
        seeded accounts (_DEV_LOGIN_USERS) behind one shared password, for
        environments where a real Google OAuth client isn't worth setting
        up. Off by default: JAAS_DEV_LOGIN_PASSWORD must be set."""
        if not self._settings.dev_login_password:
            raise JaasError(
                ErrorCode.DEV_LOGIN_NOT_CONFIGURED,
                "dev credential sign-in is not enabled for this deployment "
                "(JAAS_DEV_LOGIN_PASSWORD unset)",
            )
        normalized_email = email.strip().lower()
        name = _DEV_LOGIN_USERS.get(normalized_email)
        # Constant-shape check (both lookups always run) so a mistyped
        # email doesn't respond measurably faster than a wrong password.
        password_ok = password == self._settings.dev_login_password
        if name is None or not password_ok:
            raise JaasError(ErrorCode.INVALID_DEV_LOGIN, "invalid email or password")

        google_sub = f"local:{normalized_email}"
        is_new_user = self._users.find_by_google_sub(google_sub) is None
        user = self._users.find_or_create(
            google_sub=google_sub, email=normalized_email, name=name, picture=None
        )

        return self._finish_sign_in(
            user, is_new_user=is_new_user, requested_tenant_id=requested_tenant_id
        )

    def _finish_sign_in(
        self, user: User, *, is_new_user: bool, requested_tenant_id: str | None
    ) -> AuthResult:
        if is_new_user:
            personal_tenant = self._tenants.ensure_personal_tenant(
                user_id=user.id, display_name=user.name
            )
            self._memberships.add(
                tenant_id=personal_tenant.id, user_id=user.id, role=TenantRole.ADMIN
            )

        # ui-design.md §10.5 "People" tab fallback: resolve every pending
        # invite for this email into a real membership, on every sign-in
        # (not just the first) — an existing user can still receive a fresh
        # invite to a tenant they aren't in yet.
        if self._invites is not None:
            for invite in self._invites.pop_for_email(user.email):
                if self._memberships.get(tenant_id=invite.tenant_id, user_id=user.id) is None:
                    self._memberships.add(
                        tenant_id=invite.tenant_id, user_id=user.id, role=invite.role
                    )

        memberships = self._memberships.list_for_user(user.id)
        if not memberships:
            # Defensive: a pre-existing user record with no memberships at
            # all (e.g. an older local registry state) still gets a home.
            personal_tenant = self._tenants.ensure_personal_tenant(
                user_id=user.id, display_name=user.name
            )
            memberships = [
                self._memberships.add(
                    tenant_id=personal_tenant.id, user_id=user.id, role=TenantRole.ADMIN
                )
            ]

        active_membership = self._resolve_active_membership(memberships, requested_tenant_id)
        access_token = self._mint_for(
            user=user, tenant_id=active_membership.tenant_id, role=active_membership.role
        )
        refresh_token = self._refresh_tokens.issue(
            user_id=user.id, ttl_seconds=self._settings.refresh_token_ttl_seconds
        )

        return AuthResult(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user,
            tenants=self._tenant_views(memberships),
            active_tenant_id=active_membership.tenant_id,
        )

    def refresh(
        self, raw_refresh_token: str, *, requested_tenant_id: str | None = None
    ) -> AuthResult:
        record = self._refresh_tokens.redeem(raw_refresh_token)
        if record is None:
            raise JaasError(
                ErrorCode.INVALID_REFRESH_TOKEN, "refresh token is invalid or has expired"
            )

        user = self._users.get(record.user_id)
        if user is None:
            raise JaasError(
                ErrorCode.INVALID_REFRESH_TOKEN, "refresh token's user no longer exists"
            )

        memberships = self._memberships.list_for_user(user.id)
        active_membership = self._resolve_active_membership(memberships, requested_tenant_id)
        access_token = self._mint_for(
            user=user, tenant_id=active_membership.tenant_id, role=active_membership.role
        )

        return AuthResult(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            user=user,
            tenants=self._tenant_views(memberships),
            active_tenant_id=active_membership.tenant_id,
        )

    def _resolve_active_membership(
        self, memberships: list[Membership], requested_tenant_id: str | None
    ) -> Membership:
        if requested_tenant_id is not None:
            for membership in memberships:
                if membership.tenant_id == requested_tenant_id:
                    return membership
            raise JaasError(
                ErrorCode.NOT_TENANT_MEMBER,
                f"caller is not a member of tenant '{requested_tenant_id}'",
            )
        # ui-design.md §5.1: default to the user's personal tenant when no
        # explicit tenant is requested (e.g. first sign-in, or a refresh call
        # that doesn't specify one), never an arbitrary/first-found tenant.
        for membership in memberships:
            if membership.tenant_id.startswith("tnt_personal_"):
                return membership
        return memberships[0]
