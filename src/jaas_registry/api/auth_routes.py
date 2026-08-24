"""Google sign-in and token refresh. Design ref: ui-design.md §4.2, §7.

Separate router from routes.py (design.md's existing skills/artifact
endpoints), the same way observability_routes.py is split out — this is a
distinct concern (identity) from the skill registry API itself.
"""

from __future__ import annotations

from fastapi import APIRouter

from jaas_registry.api.deps import (
    GoogleVerifierDep,
    InviteStoreDep,
    MembershipStoreDep,
    RefreshTokenStoreDep,
    SettingsDep,
    TenantStoreDep,
    UserStoreDep,
)
from jaas_registry.api.schemas import (
    AuthResponse,
    DevLoginRequest,
    GoogleSignInRequest,
    RefreshRequest,
    RefreshResponse,
    TenantMembershipResponse,
    UserResponse,
)
from jaas_registry.authn.service import AuthResult, AuthService

router = APIRouter(prefix="/api/v1/auth")


def _build_service(
    *,
    settings: SettingsDep,
    user_store: UserStoreDep,
    tenant_store: TenantStoreDep,
    membership_store: MembershipStoreDep,
    refresh_token_store: RefreshTokenStoreDep,
    invite_store: InviteStoreDep | None = None,
    verifier: GoogleVerifierDep = None,
) -> AuthService:
    return AuthService(
        settings=settings,
        verifier=verifier,
        user_store=user_store,
        tenant_store=tenant_store,
        membership_store=membership_store,
        refresh_token_store=refresh_token_store,
        invite_store=invite_store,
    )


def _tenant_list(result: AuthResult) -> list[TenantMembershipResponse]:
    return [
        TenantMembershipResponse(id=t.tenant_id, name=t.tenant_name, role=t.role.value)
        for t in result.tenants
    ]


@router.post("/google", response_model=AuthResponse)
def sign_in_with_google(
    body: GoogleSignInRequest,
    settings: SettingsDep,
    user_store: UserStoreDep,
    tenant_store: TenantStoreDep,
    membership_store: MembershipStoreDep,
    refresh_token_store: RefreshTokenStoreDep,
    invite_store: InviteStoreDep,
    verifier: GoogleVerifierDep,
) -> AuthResponse:
    service = _build_service(
        settings=settings,
        user_store=user_store,
        tenant_store=tenant_store,
        membership_store=membership_store,
        refresh_token_store=refresh_token_store,
        invite_store=invite_store,
        verifier=verifier,
    )
    result = service.sign_in_with_google(body.idToken, requested_tenant_id=body.tenantId)
    return AuthResponse(
        accessToken=result.access_token,
        refreshToken=result.refresh_token,
        user=UserResponse(
            id=result.user.id,
            email=result.user.email,
            name=result.user.name,
            pictureUrl=result.user.picture,
        ),
        tenants=_tenant_list(result),
        activeTenantId=result.active_tenant_id,
    )


@router.post("/login", response_model=AuthResponse)
def sign_in_with_dev_credentials(
    body: DevLoginRequest,
    settings: SettingsDep,
    user_store: UserStoreDep,
    tenant_store: TenantStoreDep,
    membership_store: MembershipStoreDep,
    refresh_token_store: RefreshTokenStoreDep,
    invite_store: InviteStoreDep,
) -> AuthResponse:
    """Local-dev-only alternative to /google — see AuthService.sign_in_with_dev_credentials
    and Settings.dev_login_password."""
    service = _build_service(
        settings=settings,
        user_store=user_store,
        tenant_store=tenant_store,
        membership_store=membership_store,
        refresh_token_store=refresh_token_store,
        invite_store=invite_store,
    )
    result = service.sign_in_with_dev_credentials(
        body.email, body.password, requested_tenant_id=body.tenantId
    )
    return AuthResponse(
        accessToken=result.access_token,
        refreshToken=result.refresh_token,
        user=UserResponse(
            id=result.user.id,
            email=result.user.email,
            name=result.user.name,
            pictureUrl=result.user.picture,
        ),
        tenants=_tenant_list(result),
        activeTenantId=result.active_tenant_id,
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh_session(
    body: RefreshRequest,
    settings: SettingsDep,
    user_store: UserStoreDep,
    tenant_store: TenantStoreDep,
    membership_store: MembershipStoreDep,
    refresh_token_store: RefreshTokenStoreDep,
) -> RefreshResponse:
    service = _build_service(
        settings=settings,
        user_store=user_store,
        tenant_store=tenant_store,
        membership_store=membership_store,
        refresh_token_store=refresh_token_store,
    )
    result = service.refresh(body.refreshToken, requested_tenant_id=body.tenantId)
    return RefreshResponse(
        accessToken=result.access_token,
        tenants=_tenant_list(result),
        activeTenantId=result.active_tenant_id,
    )
