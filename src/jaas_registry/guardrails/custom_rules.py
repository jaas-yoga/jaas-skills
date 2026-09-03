"""Tenant-owned custom guardrail rules — reusable, named rules a tenant
defines once (via the web UI or `jaasctl guardrails push`) and applies
across many skills, either tenant-wide or per-skill via a
`.jaas/guardrails.yaml` `apply:` list (see guardrails/skill_config.py).

This service never executes rule logic — that's the standalone
jaas-guardrails service's job, reached only through `guardrails/client.py`.
This store only owns *what custom rules exist for which tenant*; every
scan resends the relevant rule definitions as `customRules`, the same way
tenant policy resends `enabledCheckIds` (guardrails/policy.py).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from jaas_registry.common.errors import ErrorCode, JaasError

MAX_RULES_PER_TENANT = 100
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True)
class CustomGuardrailRule:
    id: str  # "custom:<tenant_id>:<slug>" — see make_id()
    tenant_id: str
    slug: str
    name: str
    description: str
    category: str
    severity: str
    standard_ref: str
    kind: str
    config: dict
    created_by: str
    created_at: str
    # SemVer, same convention as a skill's manifest `version` — "1.0.0" is
    # the default for every rule published before this field existed
    # (dataclass default, not written by any pre-existing on-disk record).
    version: str = "1.0.0"


def make_id(tenant_id: str, slug: str) -> str:
    """Namespaced so a tenant's custom rule id can never collide with or
    shadow a platform catalog id, nor another tenant's rule. The
    guardrails service trusts this prefix structurally — it doesn't know
    what a "tenant" is, so nothing on that side ever needs to enforce
    uniqueness across tenants; this store is the only place that does."""
    return f"custom:{tenant_id}:{slug}"


def validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise JaasError(
            ErrorCode.INVALID_CUSTOM_GUARDRAIL,
            f"'{slug}' is not a valid rule slug (lowercase letters, digits, "
            f"hyphens only, e.g. 'no-internal-hostnames')",
        )


class CustomGuardrailRuleStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "custom_guardrails"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str, slug: str) -> Path:
        return self._dir / f"{tenant_id}__{slug}.json"

    def _version_path(self, tenant_id: str, slug: str, version: str) -> Path:
        # Separate "versions" subdirectory (not just a differently-named
        # file alongside _path()'s current-pointer file) so list_for_tenant's
        # glob keeps matching exactly one file per rule, unchanged.
        return self._dir / "versions" / f"{tenant_id}__{slug}__{version}.json"

    def get(self, tenant_id: str, slug: str) -> CustomGuardrailRule | None:
        path = self._path(tenant_id, slug)
        if not path.exists():
            return None
        return _from_dict(json.loads(path.read_text()))

    def list_for_tenant(self, tenant_id: str) -> list[CustomGuardrailRule]:
        # Non-recursive glob — never descends into versions/, so this only
        # ever matches the one current-pointer file per rule.
        rules = [
            _from_dict(json.loads(path.read_text()))
            for path in self._dir.glob(f"{tenant_id}__*.json")
        ]
        return sorted(rules, key=lambda r: r.slug)

    def list_versions(self, tenant_id: str, slug: str) -> list[CustomGuardrailRule]:
        """Every version ever published for this rule, oldest first —
        immutable snapshots, unaffected by later publishes. Plain string
        sort (same caveat as index/store.py's list_versions: fine for
        display, not for "highest SemVer" — this rule set is small enough
        that nothing here needs that)."""
        versions_dir = self._dir / "versions"
        if not versions_dir.is_dir():
            return []
        rules = [
            _from_dict(json.loads(path.read_text()))
            for path in versions_dir.glob(f"{tenant_id}__{slug}__*.json")
        ]
        return sorted(rules, key=lambda r: r.version)

    def put(
        self,
        *,
        tenant_id: str,
        slug: str,
        name: str,
        description: str,
        category: str,
        severity: str,
        standard_ref: str,
        kind: str,
        config: dict,
        created_by: str,
        version: str = "1.0.0",
    ) -> CustomGuardrailRule:
        validate_slug(slug)
        is_new = self.get(tenant_id, slug) is None
        if is_new and len(self.list_for_tenant(tenant_id)) >= MAX_RULES_PER_TENANT:
            raise JaasError(
                ErrorCode.GUARDRAIL_RULE_LIMIT_EXCEEDED,
                f"tenant '{tenant_id}' already has the maximum of "
                f"{MAX_RULES_PER_TENANT} custom guardrail rules",
            )
        rule = CustomGuardrailRule(
            id=make_id(tenant_id, slug),
            tenant_id=tenant_id,
            slug=slug,
            name=name,
            description=description,
            category=category,
            severity=severity,
            standard_ref=standard_ref,
            kind=kind,
            config=config,
            created_by=created_by,
            created_at=datetime.now(UTC).isoformat(),
            version=version,
        )
        serialized = json.dumps(asdict(rule))

        # Not a hard immutability guarantee like a skill's published
        # artifact — `jaasctl guardrails push` (predates versioning
        # entirely) legitimately re-puts the same slug at the same
        # implicit "1.0.0" version with different content on every push,
        # and that must keep working unchanged. The version snapshot
        # simply reflects whatever was last published *at that version
        # string* — real history only accumulates when a caller (the
        # draft/publish UI flow) actually advances `version` itself.
        version_path = self._version_path(tenant_id, slug, version)
        version_path.parent.mkdir(parents=True, exist_ok=True)
        version_path.write_text(serialized)

        self._path(tenant_id, slug).write_text(serialized)
        return rule

    def delete(self, tenant_id: str, slug: str) -> bool:
        path = self._path(tenant_id, slug)
        if not path.exists():
            return False
        path.unlink()
        for version_path in (self._dir / "versions").glob(f"{tenant_id}__{slug}__*.json"):
            version_path.unlink()
        return True


def _from_dict(data: dict) -> CustomGuardrailRule:
    return CustomGuardrailRule(**data)
