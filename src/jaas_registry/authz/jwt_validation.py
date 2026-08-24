"""JWT validation: issuer, audience, signature, expiry.

Design ref: design.md §3.4.1, §7.2.1, implementation-plan.md Phase 4 task 1.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt as pyjwt

from jaas_registry.common.errors import ErrorCode, JaasError


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    scopes: tuple[str, ...]
    tenant: str | None = None
    # Present only on a personal access token (authn/pat.py) minted via
    # /api/v1/account/tokens — absent on a normal session token. Lets
    # policy.py check revocation without adding any lookup cost to the
    # session-token hot path (search/metadata never even reach that check).
    pat_id: str | None = None


def decode_token(token: str, *, secret: str, issuer: str, audience: str) -> TokenClaims:
    """Validates signature, issuer, audience, and expiry. `exp` is explicitly
    required (not just checked-if-present) — pyjwt only verifies an expiry
    claim if one exists, so a token minted without `exp` would otherwise never
    expire, defeating the whole short-lived-access model. Raises
    JaasError(UNAUTHORIZED) — never a raw pyjwt exception — so every rejection
    reason at this boundary carries the same stable code.
    """
    try:
        payload = pyjwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp"]},
        )
    except pyjwt.PyJWTError as exc:
        raise JaasError(ErrorCode.UNAUTHORIZED, f"invalid token: {exc}") from exc

    scope_claim = payload.get("scope", "")
    scopes = tuple(scope_claim.split()) if isinstance(scope_claim, str) else tuple(scope_claim)
    return TokenClaims(
        subject=payload.get("sub", ""),
        scopes=scopes,
        tenant=payload.get("tenant"),
        pat_id=payload.get("pat_id"),
    )
