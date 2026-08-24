"""Persists a tenant's "Connect GitHub" OAuth token — the live repo/branch
picker in Connect-a-repo (api/github_routes.py) uses this to call GitHub's
API on the tenant's behalf. One connection per tenant, same file-backed
convention as authn/repo_links.py.

Token storage is plaintext-on-disk, matching this codebase's existing,
explicitly-scoped convention (common/config.py: "Local-prototype scope...
no database" — the signing key and jwt_secret are stored/configured the
same unencrypted way). A production deployment should encrypt this at
rest; flagged here deliberately rather than silently decided.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class GitHubConnection:
    tenant_id: str
    access_token: str
    github_login: str
    github_avatar_url: str | None
    connected_by: str
    connected_at: str


class GitHubConnectionStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "github_connections"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str) -> Path:
        return self._dir / f"{tenant_id}.json"

    def get(self, tenant_id: str) -> GitHubConnection | None:
        path = self._path(tenant_id)
        if not path.exists():
            return None
        return GitHubConnection(**json.loads(path.read_text()))

    def put(
        self,
        *,
        tenant_id: str,
        access_token: str,
        github_login: str,
        github_avatar_url: str | None,
        connected_by: str,
    ) -> GitHubConnection:
        connection = GitHubConnection(
            tenant_id=tenant_id,
            access_token=access_token,
            github_login=github_login,
            github_avatar_url=github_avatar_url,
            connected_by=connected_by,
            connected_at=datetime.now(UTC).isoformat(),
        )
        self._path(tenant_id).write_text(json.dumps(asdict(connection)))
        return connection

    def delete(self, tenant_id: str) -> bool:
        path = self._path(tenant_id)
        if not path.exists():
            return False
        path.unlink()
        return True
