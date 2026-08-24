"""JWT minting and refresh-token persistence. ui-design.md §4.3-4.4, §6.3.

`mint_access_token` is the producer counterpart to
`authz/jwt_validation.decode_token` — same secret/issuer/audience
configuration, just the other side of the mint/verify pair; nothing in
authz/ changes. Refresh tokens are file-backed (unlike the in-memory,
short-lived `ArtifactTokenIssuer`) because a 30-day-lived token must survive
a `jaasctl serve` restart — a restart must not silently log every user out.
The raw token is never stored: only its SHA-256 hash is persisted, so
filesystem read access to `policy_dir` (e.g. a misconfigured backup) can't
be used to mint valid sessions.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import jwt as pyjwt

from jaas_registry.authn.models import TenantRole


def mint_access_token(
    *,
    user_id: str,
    email: str,
    name: str,
    tenant_id: str,
    tenant_role: TenantRole,
    scopes: tuple[str, ...],
    secret: str,
    issuer: str,
    audience: str,
    ttl_seconds: int,
    pat_id: str | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "tenant": tenant_id,
        "tenant_role": tenant_role.value,
        "scope": " ".join(scopes),
        # JWT encoding is deterministic for identical claims, and iat/exp
        # only have second resolution — without a per-mint nonce, two
        # tokens minted for the same user/tenant within the same second
        # would be byte-for-byte identical.
        "jti": secrets.token_urlsafe(8),
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if pat_id is not None:
        payload["pat_id"] = pat_id
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


@dataclass(frozen=True)
class RefreshTokenRecord:
    user_id: str
    expires_at: float


class RefreshTokenStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "refresh_tokens"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, raw_token: str) -> Path:
        return self._dir / f"{_hash_token(raw_token)}.json"

    def issue(self, *, user_id: str, ttl_seconds: int) -> str:
        raw_token = secrets.token_urlsafe(32)
        record = RefreshTokenRecord(user_id=user_id, expires_at=time.time() + ttl_seconds)
        self._path(raw_token).write_text(json.dumps(asdict(record)))
        return raw_token

    def redeem(self, raw_token: str) -> RefreshTokenRecord | None:
        """Reusable until expiry or explicit revoke — not rotated on each
        use, matching this codebase's existing short-lived-token convention
        (artifact/tokens.py's ArtifactTokenIssuer)."""
        path = self._path(raw_token)
        if not path.exists():
            return None
        record = RefreshTokenRecord(**json.loads(path.read_text()))
        if record.expires_at < time.time():
            path.unlink(missing_ok=True)
            return None
        return record

    def revoke(self, raw_token: str) -> None:
        self._path(raw_token).unlink(missing_ok=True)
