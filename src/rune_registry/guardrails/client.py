"""HTTP client for the standalone rune-guardrails service
(https://github.com/balakrishna-maduru/rune-guardrails-catalog). This is
the **only** point of contact between this codebase and that one — no
shared Python types, no vendored code, no in-process execution. Everything
downstream of `GuardrailsClient` only ever sees the mirror types in
`guardrails/models.py`.
"""

from __future__ import annotations

import base64
from typing import Protocol

import httpx

from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.guardrails.models import (
    GuardrailDefinition,
    GuardrailFinding,
    GuardrailLevel,
    GuardrailScanResult,
    GuardrailSeverity,
)
from rune_registry.validation.models import DependencyDeclaration, ManifestDocument


class CustomRuleInput(Protocol):
    """Structural shape `scan()`/`validate_rule()` need from a custom rule
    — matches guardrails/custom_rules.py's CustomGuardrailRule, but this
    module doesn't import that one to avoid a dependency in the direction
    tenant-policy code shouldn't need (this file is the HTTP boundary; it
    only needs to read these seven fields off whatever it's handed)."""

    id: str
    name: str
    description: str
    category: str
    severity: str
    standard_ref: str
    kind: str
    config: dict


class GuardrailsClient(Protocol):
    def fetch_catalog(self) -> list[GuardrailDefinition]: ...

    def scan(
        self,
        *,
        files: dict[str, bytes],
        manifest: ManifestDocument,
        permissions: list[str],
        dependencies: list[DependencyDeclaration],
        enabled_check_ids: frozenset[str],
        existing_skill_ids: frozenset[str] = frozenset(),
        custom_rules: tuple[CustomRuleInput, ...] = (),
    ) -> GuardrailScanResult: ...

    def validate_rule(
        self,
        *,
        id: str,
        name: str,
        description: str,
        category: str,
        severity: str,
        standard_ref: str,
        kind: str,
        config: dict,
    ) -> str | None:
        """Returns None if the rule is valid, else a human-readable error."""
        ...


def _finding_from_json(item: dict) -> GuardrailFinding:
    return GuardrailFinding(
        check_id=item["checkId"],
        file=item["file"],
        message=item["message"],
        severity=GuardrailSeverity(item["severity"]),
    )


def _custom_rule_to_json(rule: CustomRuleInput) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "category": rule.category,
        "severity": rule.severity,
        "standardRef": rule.standard_ref,
        "kind": rule.kind,
        "config": rule.config,
    }


def _definition_from_json(item: dict) -> GuardrailDefinition:
    return GuardrailDefinition(
        id=item["id"],
        name=item["name"],
        description=item["description"],
        category=item["category"],
        level=GuardrailLevel(item["level"]),
        mandatory=item["mandatory"],
        default_enabled=item["defaultEnabled"],
        severity=GuardrailSeverity(item["defaultSeverity"]),
        standard_ref=item["standardRef"],
    )


class HttpGuardrailsClient:
    def __init__(self, base_url: str, *, timeout: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _unavailable(self, exc: Exception) -> RuneError:
        return RuneError(
            ErrorCode.GUARDRAILS_SERVICE_UNAVAILABLE,
            f"guardrails service unreachable at {self._base_url} — is it running? "
            f"(see the rune-guardrails-catalog repo's run.sh): {exc}",
        )

    def fetch_catalog(self) -> list[GuardrailDefinition]:
        try:
            resp = httpx.get(f"{self._base_url}/catalog", timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise self._unavailable(exc) from exc
        return [_definition_from_json(item) for item in resp.json()]

    def scan(
        self,
        *,
        files: dict[str, bytes],
        manifest: ManifestDocument,
        permissions: list[str],
        dependencies: list[DependencyDeclaration],
        enabled_check_ids: frozenset[str],
        existing_skill_ids: frozenset[str] = frozenset(),
        custom_rules: tuple[CustomRuleInput, ...] = (),
    ) -> GuardrailScanResult:
        body = {
            "files": {
                path: base64.b64encode(content).decode("ascii") for path, content in files.items()
            },
            "manifest": {
                "entrypoint": manifest.entrypoint,
                "runtimeFamilies": [rc.family for rc in manifest.runtime],
                "contact": manifest.owner.contact,
            },
            "permissions": list(permissions),
            "dependencies": [
                {"id": dep.id, "versionConstraint": dep.version_constraint}
                for dep in dependencies
            ],
            "enabledCheckIds": sorted(enabled_check_ids),
            "existingSkillIds": sorted(existing_skill_ids),
            "customRules": [_custom_rule_to_json(r) for r in custom_rules],
        }
        try:
            resp = httpx.post(f"{self._base_url}/scan", json=body, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise self._unavailable(exc) from exc
        if resp.status_code == 400:
            # A customRules entry didn't validate — the service caught it
            # at scan time (validate_rule() should normally catch this
            # earlier, before a rule is ever saved, but nothing stops the
            # underlying catalog contract from changing between then and
            # now). A caller error, not a service outage — don't wrap it
            # as GUARDRAILS_SERVICE_UNAVAILABLE.
            raise RuneError(
                ErrorCode.INVALID_CUSTOM_GUARDRAIL,
                "guardrails service rejected a custom rule",
                details=resp.json() if resp.content else {},
            )
        try:
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise self._unavailable(exc) from exc

        data = resp.json()
        return GuardrailScanResult(
            blocking=tuple(_finding_from_json(f) for f in data["blocking"]),
            warnings=tuple(_finding_from_json(f) for f in data["warnings"]),
        )

    def validate_rule(
        self,
        *,
        id: str,
        name: str,
        description: str,
        category: str,
        severity: str,
        standard_ref: str,
        kind: str,
        config: dict,
    ) -> str | None:
        body = {
            "rule": {
                "id": id,
                "name": name,
                "description": description,
                "category": category,
                "severity": severity,
                "standardRef": standard_ref,
                "kind": kind,
                "config": config,
            }
        }
        try:
            resp = httpx.post(f"{self._base_url}/validate-rule", json=body, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise self._unavailable(exc) from exc
        data = resp.json()
        return None if data["valid"] else data.get("error")
