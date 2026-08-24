"""Tenant-owned custom guardrail rules — reusable, named rules a tenant
defines once (via the web UI or `runectl guardrails push`) and applies
across many skills, either tenant-wide or per-skill via a
`.rune/guardrails.yaml` `apply:` list (see guardrails/skill_config.py).

This service never executes rule logic — that's the standalone
rune-guardrails service's job, reached only through `guardrails/client.py`.
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

from rune_registry.common.errors import ErrorCode, RuneError

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


def make_id(tenant_id: str, slug: str) -> str:
    """Namespaced so a tenant's custom rule id can never collide with or
    shadow a platform catalog id, nor another tenant's rule. The
    guardrails service trusts this prefix structurally — it doesn't know
    what a "tenant" is, so nothing on that side ever needs to enforce
    uniqueness across tenants; this store is the only place that does."""
    return f"custom:{tenant_id}:{slug}"


def validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise RuneError(
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

    def get(self, tenant_id: str, slug: str) -> CustomGuardrailRule | None:
        path = self._path(tenant_id, slug)
        if not path.exists():
            return None
        return _from_dict(json.loads(path.read_text()))

    def list_for_tenant(self, tenant_id: str) -> list[CustomGuardrailRule]:
        rules = [
            _from_dict(json.loads(path.read_text()))
            for path in self._dir.glob(f"{tenant_id}__*.json")
        ]
        return sorted(rules, key=lambda r: r.slug)

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
    ) -> CustomGuardrailRule:
        validate_slug(slug)
        is_new = self.get(tenant_id, slug) is None
        if is_new and len(self.list_for_tenant(tenant_id)) >= MAX_RULES_PER_TENANT:
            raise RuneError(
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
        )
        self._path(tenant_id, slug).write_text(json.dumps(asdict(rule)))
        return rule

    def delete(self, tenant_id: str, slug: str) -> bool:
        path = self._path(tenant_id, slug)
        if not path.exists():
            return False
        path.unlink()
        return True


def _from_dict(data: dict) -> CustomGuardrailRule:
    return CustomGuardrailRule(**data)
