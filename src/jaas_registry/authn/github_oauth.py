"""The stateless half of the "Connect GitHub" flow: signing/verifying the
OAuth `state` param and building the authorize URL. No network calls here
— see authn/github_client.py for the code-exchange/API-call half, kept
separate so this module is trivially unit-testable.

Why `state` needs to be signed, not just random: GitHub OAuth Apps only
support a small, fixed set of registered redirect URIs, so the callback
(api/github_routes.py::github_callback) can't carry a tenant_id path
segment the way every other route here does — it has to travel inside
`state` instead. Signing it (reusing the same jwt_secret/pyjwt machinery
as session tokens, but a distinct audience so a session token could never
be replayed here) makes `state` the entire authentication story for that
otherwise-unauthenticated callback request: only a value minted here,
after admin auth was already checked in the connect-url endpoint, can
verify.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import jwt as pyjwt

from jaas_registry.common.errors import ErrorCode, JaasError

_STATE_AUDIENCE = "jaas-github-oauth-state"
_STATE_TTL_SECONDS = 600  # 10 minutes — long enough to approve on GitHub, no longer

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"


@dataclass(frozen=True)
class GitHubOAuthState:
    tenant_id: str
    user_id: str


def sign_state(*, tenant_id: str, user_id: str, secret: str, issuer: str) -> str:
    now = int(time.time())
    payload = {
        "tenant_id": tenant_id,
        # The callback (api/github_routes.py::github_callback) is an
        # unauthenticated hit from GitHub, not a normal Bearer-authenticated
        # request — user_id travels here so connected_by/the audit actor
        # can still record who actually initiated the connection, not just
        # which tenant it belongs to.
        "user_id": user_id,
        "jti": secrets.token_urlsafe(8),
        "iss": issuer,
        "aud": _STATE_AUDIENCE,
        "iat": now,
        "exp": now + _STATE_TTL_SECONDS,
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def verify_state(state: str, *, secret: str, issuer: str) -> GitHubOAuthState:
    """Raises JaasError(INVALID_GITHUB_STATE) on any signature/expiry/
    audience mismatch — never a raw pyjwt exception."""
    try:
        payload = pyjwt.decode(
            state,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=_STATE_AUDIENCE,
            options={"require": ["exp", "iss", "aud"]},
        )
    except pyjwt.PyJWTError as exc:
        raise JaasError(ErrorCode.INVALID_GITHUB_STATE, f"invalid OAuth state: {exc}") from exc

    tenant_id = payload.get("tenant_id")
    user_id = payload.get("user_id")
    if not tenant_id or not user_id:
        raise JaasError(
            ErrorCode.INVALID_GITHUB_STATE, "OAuth state is missing tenant_id/user_id"
        )
    return GitHubOAuthState(tenant_id=tenant_id, user_id=user_id)


def build_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        # Classic OAuth App scope — coarse (full repo read/write on
        # whatever the connecting user can access), the known trade-off of
        # OAuth App vs. GitHub App's per-repo installation scoping. We
        # only ever read (list repos/branches) despite the broader grant.
        "scope": "repo",
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"
