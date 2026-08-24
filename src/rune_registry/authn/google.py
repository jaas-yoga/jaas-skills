"""Google ID token verification. ui-design.md §4.1, §6.3.

Verifies a Google-issued ID token's signature (against Google's published
certs), audience, and issuer before treating any of its claims as trustworthy
— never decodes-and-trusts an unverified token, the same fail-closed posture
as `authz/jwt_validation.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from rune_registry.common.errors import ErrorCode, RuneError

_VALID_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str
    picture: str | None = None


class GoogleIdentityVerifier(Protocol):
    def verify(self, google_id_token_jwt: str) -> GoogleIdentity: ...


@dataclass(frozen=True)
class RealGoogleIdentityVerifier:
    """Verifies against Google's live certificate endpoint. `client_id` is
    the audience every accepted token must have been minted for — a token
    valid for a *different* Google OAuth client must never be accepted here."""

    client_id: str

    def verify(self, google_id_token_jwt: str) -> GoogleIdentity:
        try:
            payload = google_id_token.verify_oauth2_token(
                google_id_token_jwt, google_requests.Request(), self.client_id
            )
        except Exception as exc:
            raise RuneError(
                ErrorCode.INVALID_GOOGLE_TOKEN, f"invalid Google ID token: {exc}"
            ) from exc

        if payload.get("iss") not in _VALID_ISSUERS:
            raise RuneError(ErrorCode.INVALID_GOOGLE_TOKEN, "unexpected token issuer")

        sub = payload.get("sub")
        email = payload.get("email")
        if not sub or not email:
            raise RuneError(ErrorCode.INVALID_GOOGLE_TOKEN, "token is missing sub/email claims")
        if not payload.get("email_verified", False):
            raise RuneError(ErrorCode.INVALID_GOOGLE_TOKEN, "Google account email is not verified")

        return GoogleIdentity(
            sub=sub,
            email=email,
            name=payload.get("name") or email,
            picture=payload.get("picture"),
        )
