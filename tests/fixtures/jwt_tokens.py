import time

import jwt

DEFAULT_SECRET = "dev-only-shared-secret-not-for-prod!!"  # >= 32 bytes for HS256 (RFC 7518 §3.2)
DEFAULT_ISSUER = "jaas-registry-dev"
DEFAULT_AUDIENCE = "jaas-registry"


def make_token(
    *,
    secret: str = DEFAULT_SECRET,
    issuer: str = DEFAULT_ISSUER,
    audience: str = DEFAULT_AUDIENCE,
    subject: str = "user-1",
    scopes: tuple[str, ...] = (),
    tenant: str | None = None,
    expires_in: int = 300,
    pat_id: str | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": now,
        "exp": now + expires_in,
        "scope": " ".join(scopes),
    }
    if tenant is not None:
        payload["tenant"] = tenant
    if pat_id is not None:
        payload["pat_id"] = pat_id
    return jwt.encode(payload, secret, algorithm="HS256")
