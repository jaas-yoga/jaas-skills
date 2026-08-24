""""Connect GitHub" — the live repo/branch picker behind Connect-a-repo
(tenant_routes.py's repo-links UI). Every route here is tenant-scoped and
membership-checked exactly like tenant_routes.py's repo-links routes,
*except* `github_callback`: GitHub itself hits that one, unauthenticated,
directly from the browser — its entire security story is the signed
`state` param verified via authn/github_oauth.py, not a Bearer token.
See that module's docstring and github_client.py's for the full flow.

`_require_caller`/`_require_membership`/`_require_admin` intentionally
mirror tenant_routes.py's private helpers of the same name rather than
importing them — draft_routes.py does the same thing for its own
`_require_caller`; small per-file duplication of this boilerplate is the
established convention here, not an accidental divergence.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jaas_registry.api.deps import (
    AuthorizerDep,
    GitHubApiClientDep,
    GitHubConnectionStoreDep,
    GitHubOAuthAppStoreDep,
    MembershipStoreDep,
    SettingsDep,
)
from jaas_registry.api.schemas import (
    GithubConnectionResponse,
    GithubConnectUrlResponse,
    GithubOAuthAppRequest,
    GithubOAuthAppResponse,
    GithubRepoResponse,
)
from jaas_registry.authn.github_connections import GitHubConnectionStore
from jaas_registry.authn.github_oauth import build_authorize_url, sign_state, verify_state
from jaas_registry.authn.github_oauth_apps import GitHubOAuthAppStore
from jaas_registry.authn.models import TenantRole
from jaas_registry.authn.tenants import MembershipStore
from jaas_registry.authz.base import Authorizer
from jaas_registry.common.audit import StructuredLogAuditSink, new_github_connection_event
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.sharing.access import CallerContext, resolve_caller_context

router = APIRouter(prefix="/api/v1")
_bearer_scheme = HTTPBearer(auto_error=False)


def _require_caller(
    *, settings: Settings, authorizer: Authorizer, credentials: HTTPAuthorizationCredentials | None
) -> CallerContext:
    authorizer.check(
        token=credentials.credentials if credentials else None,
        tenant_header=None,
        required_permissions=("skills:write",),
    )
    return resolve_caller_context(
        credentials.credentials if credentials else None, settings=settings
    )


def _require_membership(memberships: MembershipStore, tenant_id: str, caller: CallerContext):
    membership = memberships.get(tenant_id=tenant_id, user_id=caller.user_id or "")
    if membership is None:
        raise JaasError(ErrorCode.TENANT_NOT_FOUND, f"tenant '{tenant_id}' not found")
    return membership


def _require_admin(memberships: MembershipStore, tenant_id: str, caller: CallerContext):
    membership = _require_membership(memberships, tenant_id, caller)
    if membership.role is not TenantRole.ADMIN:
        raise JaasError(ErrorCode.UNAUTHORIZED, "only a tenant admin may manage its membership")
    return membership


def _require_oauth_app(github_oauth_app_store: GitHubOAuthAppStore, tenant_id: str):
    app_config = github_oauth_app_store.get(tenant_id)
    if app_config is None:
        raise JaasError(
            ErrorCode.GITHUB_OAUTH_NOT_CONFIGURED,
            f"tenant '{tenant_id}' has not configured a GitHub OAuth App yet",
        )
    return app_config


@router.get("/tenants/{tenant_id}/github/oauth-app", response_model=GithubOAuthAppResponse)
def get_github_oauth_app(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    github_oauth_app_store: GitHubOAuthAppStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> GithubOAuthAppResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_membership(membership_store, tenant_id, caller)  # any member may view

    app_config = github_oauth_app_store.get(tenant_id)
    return GithubOAuthAppResponse(
        configured=app_config is not None,
        clientId=app_config.client_id if app_config else None,
        redirectUri=settings.github_oauth_redirect_uri,
    )


@router.put("/tenants/{tenant_id}/github/oauth-app", response_model=GithubOAuthAppResponse)
def put_github_oauth_app(
    tenant_id: str,
    body: GithubOAuthAppRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    github_oauth_app_store: GitHubOAuthAppStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> GithubOAuthAppResponse:
    """A tenant admin registers this tenant's own GitHub OAuth App here —
    each tenant brings its own Client ID/Secret rather than sharing one
    deployment-wide app, so "Connect GitHub" below only ever becomes
    available once this has been saved."""
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)

    client_id = body.clientId.strip()
    client_secret = body.clientSecret.strip()
    if not client_id or not client_secret:
        raise JaasError(
            ErrorCode.SCHEMA_VALIDATION_FAILED, "clientId and clientSecret are both required"
        )

    app_config = github_oauth_app_store.put(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        configured_by=caller.user_id or "",
    )
    StructuredLogAuditSink().emit_github_connection_change(
        new_github_connection_event(
            actor=caller.user_id or "",
            tenant_id=tenant_id,
            github_login=None,
            action="oauth_app_configured",
        )
    )
    return GithubOAuthAppResponse(
        configured=True,
        clientId=app_config.client_id,
        redirectUri=settings.github_oauth_redirect_uri,
    )


@router.delete("/tenants/{tenant_id}/github/oauth-app", status_code=204)
def delete_github_oauth_app(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    github_oauth_app_store: GitHubOAuthAppStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> None:
    """Only removes this tenant's stored Client ID/Secret — an existing
    "Connect GitHub" connection (github_connections.py) is left alone,
    since its access token still works against GitHub independent of us
    still holding the app's secret. Reconnecting later needs the app
    configured again."""
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)

    if not github_oauth_app_store.delete(tenant_id):
        raise JaasError(
            ErrorCode.GITHUB_OAUTH_NOT_CONFIGURED,
            f"tenant '{tenant_id}' has no OAuth App configured",
        )
    StructuredLogAuditSink().emit_github_connection_change(
        new_github_connection_event(
            actor=caller.user_id or "",
            tenant_id=tenant_id,
            github_login=None,
            action="oauth_app_removed",
        )
    )


@router.get("/tenants/{tenant_id}/github/connection", response_model=GithubConnectionResponse)
def get_github_connection(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    github_connection_store: GitHubConnectionStoreDep,
    github_oauth_app_store: GitHubOAuthAppStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> GithubConnectionResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_membership(membership_store, tenant_id, caller)  # any member may view

    connection = github_connection_store.get(tenant_id)
    return GithubConnectionResponse(
        connected=connection is not None,
        configured=github_oauth_app_store.get(tenant_id) is not None,
        githubLogin=connection.github_login if connection else None,
        githubAvatarUrl=connection.github_avatar_url if connection else None,
        connectedAt=connection.connected_at if connection else None,
    )


@router.get(
    "/tenants/{tenant_id}/github/connect-url", response_model=GithubConnectUrlResponse
)
def get_github_connect_url(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    github_oauth_app_store: GitHubOAuthAppStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> GithubConnectUrlResponse:
    """The one Bearer-authenticated step in the whole flow — everything
    after this is a plain browser redirect chain with no session at all,
    so this is where "is the caller actually a tenant admin?" is checked,
    baked into the signed `state` for the callback to trust later."""
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)
    app_config = _require_oauth_app(github_oauth_app_store, tenant_id)

    state = sign_state(
        tenant_id=tenant_id,
        user_id=caller.user_id or "",
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
    )
    url = build_authorize_url(
        client_id=app_config.client_id,
        redirect_uri=settings.github_oauth_redirect_uri,
        state=state,
    )
    return GithubConnectUrlResponse(authorizeUrl=url)


@router.delete("/tenants/{tenant_id}/github/connection", status_code=204)
def delete_github_connection(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    github_connection_store: GitHubConnectionStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> None:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)

    connection = github_connection_store.get(tenant_id)
    found = github_connection_store.delete(tenant_id)
    if not found:
        raise JaasError(ErrorCode.GITHUB_NOT_CONNECTED, f"tenant '{tenant_id}' has no connection")

    StructuredLogAuditSink().emit_github_connection_change(
        new_github_connection_event(
            actor=caller.user_id or "",
            tenant_id=tenant_id,
            github_login=connection.github_login if connection else None,
            action="disconnected",
        )
    )


def _require_connection(
    github_connection_store: GitHubConnectionStore, tenant_id: str
):
    connection = github_connection_store.get(tenant_id)
    if connection is None:
        raise JaasError(
            ErrorCode.GITHUB_NOT_CONNECTED,
            f"tenant '{tenant_id}' has not connected a GitHub account yet",
        )
    return connection


@router.get(
    "/tenants/{tenant_id}/github/repos", response_model=list[GithubRepoResponse]
)
def list_github_repos(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    github_connection_store: GitHubConnectionStoreDep,
    github_api_client: GitHubApiClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> list[GithubRepoResponse]:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_membership(membership_store, tenant_id, caller)
    connection = _require_connection(github_connection_store, tenant_id)

    repos = github_api_client.list_repos(connection.access_token)
    return [
        GithubRepoResponse(
            fullName=r.full_name,
            owner=r.owner,
            name=r.name,
            private=r.private,
            defaultBranch=r.default_branch,
        )
        for r in repos
    ]


@router.get(
    "/tenants/{tenant_id}/github/repos/{owner}/{repo}/branches", response_model=list[str]
)
def list_github_branches(
    tenant_id: str,
    owner: str,
    repo: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    github_connection_store: GitHubConnectionStoreDep,
    github_api_client: GitHubApiClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> list[str]:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_membership(membership_store, tenant_id, caller)
    connection = _require_connection(github_connection_store, tenant_id)

    return github_api_client.list_branches(connection.access_token, owner=owner, repo=repo)


@router.get("/github/callback", include_in_schema=False)
def github_callback(
    settings: SettingsDep,
    github_connection_store: GitHubConnectionStoreDep,
    github_oauth_app_store: GitHubOAuthAppStoreDep,
    github_api_client: GitHubApiClientDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Hit directly by GitHub's browser redirect — no Bearer token, no
    session, `state` (authn/github_oauth.py) is the entire trust story.
    Always ends in a redirect back to the web app, success or failure,
    never a raw JSON error — there is no frontend code running on this
    response to parse one."""
    fallback_url = f"{settings.web_app_url.rstrip('/')}/skills?github=error"

    if error or not code or not state:
        return RedirectResponse(fallback_url, status_code=307)

    try:
        oauth_state = verify_state(state, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
    except JaasError:
        return RedirectResponse(fallback_url, status_code=307)

    tenant_url = (
        f"{settings.web_app_url.rstrip('/')}/tenants/{oauth_state.tenant_id}/repositories"
    )

    # The tenant's own OAuth App, looked up by the tenant_id baked into
    # `state` — this is what makes the code exchange below use the right
    # app's client_id/secret rather than a shared deployment-wide one.
    app_config = github_oauth_app_store.get(oauth_state.tenant_id)
    if app_config is None:
        return RedirectResponse(f"{tenant_url}?github=error", status_code=307)

    try:
        access_token = github_api_client.exchange_code_for_token(
            code,
            client_id=app_config.client_id,
            client_secret=app_config.client_secret,
            redirect_uri=settings.github_oauth_redirect_uri,
        )
        user = github_api_client.get_authenticated_user(access_token)
    except JaasError:
        return RedirectResponse(f"{tenant_url}?github=error", status_code=307)

    github_connection_store.put(
        tenant_id=oauth_state.tenant_id,
        access_token=access_token,
        github_login=user.login,
        github_avatar_url=user.avatar_url,
        connected_by=oauth_state.user_id,
    )
    StructuredLogAuditSink().emit_github_connection_change(
        new_github_connection_event(
            actor=oauth_state.user_id,
            tenant_id=oauth_state.tenant_id,
            github_login=user.login,
            action="connected",
        )
    )
    return RedirectResponse(f"{tenant_url}?github=connected", status_code=307)
