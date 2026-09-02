"""The caller's own profile. jaas_ui Account/Profile tab.

Split out of account_routes.py (personal access tokens) — a distinct
concern from PAT management, sharing only the same "act on the caller's
own account, identified by their token" shape.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jaas_registry.api.deps import AuthorizerDep, SettingsDep, UserStoreDep
from jaas_registry.api.schemas import UpdateDisplayNameRequest, UserResponse
from jaas_registry.authz.base import Authorizer
from jaas_registry.authz.jwt_validation import TokenClaims, decode_token
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError

router = APIRouter(prefix="/api/v1/account")
_bearer_scheme = HTTPBearer(auto_error=False)


def _require_claims(
    *,
    settings: Settings,
    authorizer: Authorizer,
    credentials: HTTPAuthorizationCredentials | None,
) -> TokenClaims:
    # Same "any real signed-in member" gate as account_routes.py's PAT
    # routes — editing your own display name isn't a distinct permission,
    # every member scope set already includes skills:write.
    authorizer.check(
        token=credentials.credentials if credentials else None,
        tenant_header=None,
        required_permissions=("skills:write",),
    )
    raw_token = credentials.credentials if credentials else ""
    return decode_token(
        raw_token,
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )


@router.patch("/profile", response_model=UserResponse)
def update_profile(
    body: UpdateDisplayNameRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    user_store: UserStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> UserResponse:
    claims = _require_claims(settings=settings, authorizer=authorizer, credentials=credentials)
    display_name = (body.displayName or "").strip() or None
    user = user_store.set_display_name(claims.subject, display_name)
    if user is None:
        raise JaasError(ErrorCode.UNAUTHORIZED, "caller has no user record")
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.effective_name,
        pictureUrl=user.picture,
        displayName=user.display_name,
    )
