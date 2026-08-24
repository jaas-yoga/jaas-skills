"""Per-tenant guardrail policy. Design ref: design.md §4.5, §7.2.

Same file-backed, no-database convention as authn/tenants.py's
MembershipStore: one JSON file per tenant under `<policy_dir>/guardrail_policies/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.guardrails.models import GuardrailDefinition


@dataclass(frozen=True)
class GuardrailPolicy:
    tenant_id: str
    enabled_check_ids: frozenset[str]


def default_policy(tenant_id: str, catalog: list[GuardrailDefinition]) -> GuardrailPolicy:
    """A tenant with no policy file yet runs every mandatory check (forced
    on regardless, per engine.py) plus every configurable check whose
    catalog entry defaults to enabled."""
    ids = frozenset(d.id for d in catalog if d.mandatory or d.default_enabled)
    return GuardrailPolicy(tenant_id=tenant_id, enabled_check_ids=ids)


class GuardrailPolicyStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "guardrail_policies"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str) -> Path:
        return self._dir / f"{tenant_id}.json"

    def get(self, tenant_id: str, catalog: list[GuardrailDefinition]) -> GuardrailPolicy:
        path = self._path(tenant_id)
        if not path.exists():
            return default_policy(tenant_id, catalog)
        data = json.loads(path.read_text())
        return GuardrailPolicy(
            tenant_id=tenant_id, enabled_check_ids=frozenset(data.get("enabledCheckIds", []))
        )

    def put(
        self,
        *,
        tenant_id: str,
        enabled_check_ids: frozenset[str],
        catalog: list[GuardrailDefinition],
    ) -> GuardrailPolicy:
        known_ids = {d.id for d in catalog}
        unknown = enabled_check_ids - known_ids
        if unknown:
            raise RuneError(
                ErrorCode.SCHEMA_VALIDATION_FAILED,
                f"unknown guardrail check id(s): {sorted(unknown)}",
            )
        # Mandatory checks are force-run by the engine regardless of policy
        # content (design.md §4.5) — dropped here too, defense in depth
        # against a hand-edited or corrupted policy file granting a false
        # impression that they're "off".
        mandatory_ids = {d.id for d in catalog if d.mandatory}
        stored_ids = frozenset(enabled_check_ids - mandatory_ids)
        self._path(tenant_id).write_text(json.dumps({"enabledCheckIds": sorted(stored_ids)}))
        return GuardrailPolicy(tenant_id=tenant_id, enabled_check_ids=stored_ids)
