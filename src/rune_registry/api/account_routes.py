"""Personal access tokens. ui-design.md §4.4.

A PAT lets `runectl` (no browser, can't run the OAuth dance) authenticate
against a real deployment. Minted with the exact same scopes/tenant the
caller's own current session has — a PAT is "clone my current access into a
long-lived, revocable credential," not a separately-configured privilege
level.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rune_registry.api.deps import AuthorizerDep, PatStoreDep, SettingsDep, UserStoreDep
from rune_registry.api.schemas import CreatePatRequest, CreatePatResponse, PatSummaryResponse
from rune_registry.authn.models import TenantRole
from rune_registry.authn.tokens import mint_access_token
from rune_registry.authz.base import Authorizer
from rune_registry.authz.jwt_validation import TokenClaims, decode_token
from rune_registry.common.config import Settings
from rune_registry.common.errors import ErrorCode, RuneError

router = APIRouter(prefix="/api/v1/account/tokens")
_bearer_scheme = HTTPBearer(auto_error=False)

# ui-design.md §4.4: bounded so a PAT can't outlive a normal token
# indefinitely by accident — 1 year is generous for a CLI credential without
# being "effectively forever."
_MAX_TTL_SECONDS = 60 * 60 * 24 * 365


def _require_claims(
    *,
    settings: Settings,
    authorizer: Authorizer,
    credentials: HTTPAuthorizationCredentials | None,
) -> TokenClaims:
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


@router.post("", response_model=CreatePatResponse)
def create_pat(
    body: CreatePatRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    pat_store: PatStoreDep,
    user_store: UserStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> CreatePatResponse:
    claims = _require_claims(settings=settings, authorizer=authorizer, credentials=credentials)
    user = user_store.get(claims.subject)
    if user is None:
        raise RuneError(ErrorCode.UNAUTHORIZED, "caller has no user record")

    ttl_seconds = min(body.ttlSeconds, _MAX_TTL_SECONDS)
    if ttl_seconds <= 0:
        raise RuneError(ErrorCode.SCHEMA_VALIDATION_FAILED, "ttlSeconds must be positive")

    pat = pat_store.create(owner_user=user.id, name=body.name, ttl_seconds=ttl_seconds)
    tenant_role = TenantRole.ADMIN if "tenant:admin" in claims.scopes else TenantRole.MEMBER
    token = mint_access_token(
        user_id=user.id,
        email=user.email,
        name=user.name,
        tenant_id=claims.tenant or "",
        tenant_role=tenant_role,
        scopes=claims.scopes,
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        ttl_seconds=ttl_seconds,
        pat_id=pat.id,
    )
    return CreatePatResponse(id=pat.id, name=pat.name, token=token, expiresAt=pat.expires_at)


@router.get("", response_model=list[PatSummaryResponse])
def list_pats(
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    pat_store: PatStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> list[PatSummaryResponse]:
    claims = _require_claims(settings=settings, authorizer=authorizer, credentials=credentials)
    return [
        PatSummaryResponse(id=p.id, name=p.name, createdAt=p.created_at, expiresAt=p.expires_at)
        for p in pat_store.list_for_user(claims.subject)
    ]


@router.delete("/{pat_id}", status_code=204)
def revoke_pat(
    pat_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    pat_store: PatStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> Response:
    claims = _require_claims(settings=settings, authorizer=authorizer, credentials=credentials)
    if not pat_store.revoke(pat_id=pat_id, owner_user=claims.subject):
        raise RuneError(ErrorCode.PAT_NOT_FOUND, f"personal access token '{pat_id}' not found")
    return Response(status_code=204)
