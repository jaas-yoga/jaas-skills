"""Personal access token records. ui-design.md §4.4.

A PAT is shaped exactly like a normal session access token (same
mint_access_token, same JwtAuthorizer validation path) plus one extra
`pat_id` claim — it's what makes revocation possible at all: a bare JWT
can't be revoked before its natural expiry, but authz/policy.py checks
`PatStore.get(pat_id)` and rejects if the record is gone. Regular session
tokens have no `pat_id` claim, so they never pay for this lookup.

The raw token is shown to the user exactly once (at creation) and never
stored — only this metadata persists, the same principle as
authn/tokens.py's RefreshTokenStore, for the same reason (filesystem read
access to policy_dir must never be enough to mint a usable credential).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class PersonalAccessToken:
    id: str
    owner_user: str
    name: str
    created_at: str
    expires_at: str


class PatStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "personal_access_tokens"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, pat_id: str) -> Path:
        return self._dir / f"{pat_id}.json"

    def create(self, *, owner_user: str, name: str, ttl_seconds: int) -> PersonalAccessToken:
        now = datetime.now(UTC)
        pat = PersonalAccessToken(
            id=f"pat_{uuid.uuid4().hex[:20]}",
            owner_user=owner_user,
            name=name,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
        )
        self._path(pat.id).write_text(json.dumps(asdict(pat)))
        return pat

    def get(self, pat_id: str) -> PersonalAccessToken | None:
        path = self._path(pat_id)
        if not path.exists():
            return None
        return PersonalAccessToken(**json.loads(path.read_text()))

    def list_for_user(self, owner_user: str) -> list[PersonalAccessToken]:
        tokens = []
        for path in self._dir.glob("*.json"):
            data = json.loads(path.read_text())
            if data["owner_user"] == owner_user:
                tokens.append(PersonalAccessToken(**data))
        return sorted(tokens, key=lambda t: t.created_at, reverse=True)

    def revoke(self, *, pat_id: str, owner_user: str) -> bool:
        """Only the owner can revoke their own token — checked by the
        caller (api/account_routes.py) before this is reached; `owner_user`
        is re-checked here too so this method is safe to call on its own."""
        pat = self.get(pat_id)
        if pat is None or pat.owner_user != owner_user:
            return False
        self._path(pat_id).unlink(missing_ok=True)
        return True
