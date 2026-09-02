"""User persistence. ui-design.md §5.1, §7.

Local-prototype scope: one JSON file per user under `<policy_dir>/users/`,
the same no-database convention as `artifact/trust.py`'s trusted-key store.
The user id is deterministically derived from the Google `sub` (not a random
uuid), so `find_or_create` needs no index file and no lock: two concurrent
first-sign-ins for the same Google account compute the identical id and
converge on the same file, rather than racing to create two user records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from jaas_registry.authn.models import User


def derive_user_id(google_sub: str) -> str:
    return f"usr_{hashlib.sha256(google_sub.encode()).hexdigest()[:24]}"


class UserStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "users"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str) -> Path:
        return self._dir / f"{user_id}.json"

    def get(self, user_id: str) -> User | None:
        path = self._path(user_id)
        if not path.exists():
            return None
        return User(**json.loads(path.read_text()))

    def find_by_google_sub(self, google_sub: str) -> User | None:
        return self.get(derive_user_id(google_sub))

    def find_by_email(self, email: str) -> User | None:
        """Directory scan — there's no by-email index (ids are derived from
        google_sub, not email), but the user count at this prototype's scale
        makes a scan fine, same tradeoff as sharing/grants.py's lookups."""
        normalized = email.strip().lower()
        for path in self._dir.glob("*.json"):
            user = User(**json.loads(path.read_text()))
            if user.email.lower() == normalized:
                return user
        return None

    def find_or_create(
        self, *, google_sub: str, email: str, name: str, picture: str | None
    ) -> User:
        """Creates the user on first sign-in; on every later sign-in,
        refreshes name/picture/email from the latest Google profile (a
        user's display name or avatar can change) while keeping the same
        stable id. `display_name` (a local override, set only via
        `set_display_name`) is preserved across this refresh — Google
        sign-in never touches it."""
        existing = self.get(derive_user_id(google_sub))
        user = User(
            id=derive_user_id(google_sub),
            google_sub=google_sub,
            email=email,
            name=name,
            picture=picture,
            display_name=existing.display_name if existing else None,
        )
        self._path(user.id).write_text(json.dumps(asdict(user)))
        return user

    def set_display_name(self, user_id: str, display_name: str | None) -> User | None:
        """Sets (or, with None, clears) the caller's own display-name
        override. Returns None if user_id doesn't resolve to a real user —
        callers decide how to surface that (account_routes.py raises)."""
        existing = self.get(user_id)
        if existing is None:
            return None
        updated = User(
            id=existing.id,
            google_sub=existing.google_sub,
            email=existing.email,
            name=existing.name,
            picture=existing.picture,
            display_name=display_name,
        )
        self._path(updated.id).write_text(json.dumps(asdict(updated)))
        return updated
