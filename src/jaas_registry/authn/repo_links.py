"""Registers which git repo may release a given skill id for a tenant —
a prerequisite check for the git-native release flow (api/release_routes.py).

Prevents skill-id squatting: CI can only release a version under a skill
id the tenant has explicitly pre-registered a link for. This is the same
problem npm's first-publish-wins model has had abuse incidents around; the
fix here is the same one most registries eventually converge on —
explicit, admin-approved registration before the first automated publish,
rather than "whoever runs `publish` first owns the name."

Same file-backed, no-database convention as every other store here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from jaas_registry.common.errors import ErrorCode, JaasError


@dataclass(frozen=True)
class RepoLink:
    id: str
    tenant_id: str
    skill_id: str
    repo_url: str
    created_by: str
    created_at: str
    # Which branches may produce a release, verified via the OIDC token's
    # `environment` claim (see authn/ci_credentials.py) — empty means "no
    # restriction," the default, fully backward compatible with links
    # created before this field existed.
    release_branches: tuple[str, ...] = ()


class RepoLinkStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "repo_links"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str, skill_id: str) -> Path:
        return self._dir / f"{tenant_id}__{skill_id}.json"

    def get(self, *, tenant_id: str, skill_id: str) -> RepoLink | None:
        path = self._path(tenant_id, skill_id)
        if not path.exists():
            return None
        return _from_dict(json.loads(path.read_text()))

    def find_any(self, skill_id: str) -> RepoLink | None:
        """Across every tenant, not just one — anti-squatting only means
        something if a second tenant can't register the same skill id a
        first tenant already claimed, which a per-tenant-only lookup
        wouldn't catch (each tenant's link lives in its own file)."""
        for path in self._dir.glob(f"*__{skill_id}.json"):
            return _from_dict(json.loads(path.read_text()))
        return None

    def list_for_tenant(self, tenant_id: str) -> list[RepoLink]:
        links = [
            _from_dict(json.loads(path.read_text()))
            for path in self._dir.glob(f"{tenant_id}__*.json")
        ]
        return sorted(links, key=lambda link: link.skill_id)

    def create(
        self,
        *,
        tenant_id: str,
        skill_id: str,
        repo_url: str,
        created_by: str,
        release_branches: tuple[str, ...] = (),
    ) -> RepoLink:
        existing = self.find_any(skill_id)
        if existing is not None:
            raise JaasError(
                ErrorCode.SCHEMA_VALIDATION_FAILED,
                f"skill id '{skill_id}' is already linked"
                + ("" if existing.tenant_id == tenant_id else " to a different tenant"),
            )
        link = RepoLink(
            id=f"lnk_{uuid.uuid4().hex[:24]}",
            tenant_id=tenant_id,
            skill_id=skill_id,
            repo_url=repo_url,
            created_by=created_by,
            created_at=datetime.now(UTC).isoformat(),
            release_branches=tuple(release_branches),
        )
        self._path(tenant_id, skill_id).write_text(json.dumps(asdict(link)))
        return link

    def update_release_branches(
        self, *, tenant_id: str, skill_id: str, release_branches: tuple[str, ...]
    ) -> RepoLink:
        """Full-replace, same convention as the guardrail-policy PUT. The
        link must already belong to this tenant — no re-run of the global
        anti-squat check, since ownership of the (tenant_id, skill_id) row
        was already established at creation."""
        existing = self.get(tenant_id=tenant_id, skill_id=skill_id)
        if existing is None:
            raise JaasError(
                ErrorCode.REPO_LINK_NOT_FOUND, f"no repo link for skill id '{skill_id}'"
            )
        updated = replace(existing, release_branches=tuple(release_branches))
        self._path(tenant_id, skill_id).write_text(json.dumps(asdict(updated)))
        return updated

    def delete(self, *, tenant_id: str, skill_id: str) -> bool:
        path = self._path(tenant_id, skill_id)
        if not path.exists():
            return False
        path.unlink()
        return True


def _from_dict(data: dict) -> RepoLink:
    if "release_branches" in data:
        data = {**data, "release_branches": tuple(data["release_branches"])}
    return RepoLink(**data)
