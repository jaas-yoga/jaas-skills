"""Short-lived artifact access tokens. Design ref: design.md §3.3.2, §5.3.

Prototype scope: an opaque token mapped in-process to a blob key (plus the
digest/signature needed for an optional high-assurance recheck at redemption)
with a TTL, standing in for a presigned S3 URL or OCI pull reference — same
short-lived-access shape, different backing mechanism. Like a real presigned
URL, a token is reusable until it expires — redemption is not single-use.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactToken:
    token: str
    blob_key: str
    digest: str
    signature: str
    expires_at: float


class ArtifactTokenIssuer:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._tokens: dict[str, ArtifactToken] = {}

    def issue(self, *, blob_key: str, digest: str, signature: str) -> ArtifactToken:
        record = ArtifactToken(
            token=secrets.token_urlsafe(32),
            blob_key=blob_key,
            digest=digest,
            signature=signature,
            expires_at=time.time() + self.ttl_seconds,
        )
        self._tokens[record.token] = record
        return record

    def redeem(self, token: str) -> ArtifactToken | None:
        record = self._tokens.get(token)
        if record is None or record.expires_at < time.time():
            return None
        return record
