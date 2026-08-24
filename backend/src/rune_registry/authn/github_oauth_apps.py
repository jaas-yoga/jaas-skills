"""Per-tenant GitHub OAuth App credentials. Each tenant registers its own
GitHub OAuth App (Client ID + Secret) rather than sharing one deployment-
wide app — "Connect GitHub" (github_connections.py) exchanges a code using
whichever tenant's app the connecting admin configured here first.

Token/secret storage is plaintext-on-disk, matching this codebase's
existing, explicitly-scoped convention (common/config.py: "Local-prototype
scope... no database"). Same file-backed-per-tenant convention as
authn/repo_links.py and authn/github_connections.py.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class GitHubOAuthAppConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    configured_by: str
    configured_at: str


class GitHubOAuthAppStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "github_oauth_apps"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str) -> Path:
        return self._dir / f"{tenant_id}.json"

    def get(self, tenant_id: str) -> GitHubOAuthAppConfig | None:
        path = self._path(tenant_id)
        if not path.exists():
            return None
        return GitHubOAuthAppConfig(**json.loads(path.read_text()))

    def put(
        self, *, tenant_id: str, client_id: str, client_secret: str, configured_by: str
    ) -> GitHubOAuthAppConfig:
        config = GitHubOAuthAppConfig(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            configured_by=configured_by,
            configured_at=datetime.now(UTC).isoformat(),
        )
        self._path(tenant_id).write_text(json.dumps(asdict(config)))
        return config

    def delete(self, tenant_id: str) -> bool:
        path = self._path(tenant_id)
        if not path.exists():
            return False
        path.unlink()
        return True
