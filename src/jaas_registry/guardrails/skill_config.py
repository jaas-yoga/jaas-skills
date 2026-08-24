"""Parses a skill package's optional `.jaas/guardrails.yaml` — lets a
skill author apply guardrails to just their own skill, reviewed in the
same PR/commit as the code, on top of whatever the tenant's baseline
policy already enables (guardrails/policy.py).

```yaml
apply:
  - custom:tnt_acme:no-internal-hostname   # a tenant-wide custom rule id
  - pii-pattern-scan                       # or a platform catalog id
rules:
  - slug: no-todo
    name: No TODO
    category: CODE_SAFETY
    severity: WARN
    kind: regex_file_scan
    config: { scope: all_files, patterns: [{ name: todo, regex: "TODO" }] }
```

This file can only ever *add* checks on top of the tenant's policy — it
can never remove one the tenant enabled (that's an admin decision, made
in guardrails/policy.py), and it can never disable a mandatory check
(force-run server-side by the guardrails service itself, regardless of
what any caller asks for).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.guardrails.custom_rules import CustomGuardrailRule, CustomGuardrailRuleStore
from jaas_registry.guardrails.custom_rules import validate_slug as _validate_slug
from jaas_registry.guardrails.policy import GuardrailPolicy

MAX_INLINE_RULES = 20
_REQUIRED_INLINE_KEYS = {"slug", "name", "category", "severity", "kind", "config"}

GUARDRAILS_CONFIG_PATH = ".jaas/guardrails.yaml"


@dataclass(frozen=True)
class InlineCustomRule:
    slug: str
    name: str
    description: str
    category: str
    severity: str
    standard_ref: str
    kind: str
    config: dict


@dataclass(frozen=True)
class SkillGuardrailConfig:
    apply: tuple[str, ...]
    inline_rules: tuple[InlineCustomRule, ...]


EMPTY_SKILL_GUARDRAIL_CONFIG = SkillGuardrailConfig(apply=(), inline_rules=())


def read_skill_guardrail_config(source_dir: Path) -> bytes | None:
    """None if the skill package simply doesn't have this file — that's
    the common, valid case, not an error condition."""
    path = source_dir / GUARDRAILS_CONFIG_PATH
    return path.read_bytes() if path.is_file() else None


def parse_skill_guardrail_config(raw: bytes | str | None) -> SkillGuardrailConfig:
    """`None`/empty input is perfectly valid — most skills won't have this
    file at all, and that means "apply nothing beyond the tenant's
    baseline policy", not an error."""
    if not raw:
        return EMPTY_SKILL_GUARDRAIL_CONFIG

    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise JaasError(
            ErrorCode.INVALID_CUSTOM_GUARDRAIL, f"{GUARDRAILS_CONFIG_PATH} is not valid YAML: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise JaasError(
            ErrorCode.INVALID_CUSTOM_GUARDRAIL, f"{GUARDRAILS_CONFIG_PATH} must be a mapping"
        )

    apply_ids = data.get("apply", [])
    if not isinstance(apply_ids, list) or not all(isinstance(i, str) for i in apply_ids):
        raise JaasError(
            ErrorCode.INVALID_CUSTOM_GUARDRAIL, "'apply' must be a list of rule id strings"
        )

    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise JaasError(ErrorCode.INVALID_CUSTOM_GUARDRAIL, "'rules' must be a list")
    if len(raw_rules) > MAX_INLINE_RULES:
        raise JaasError(
            ErrorCode.GUARDRAIL_RULE_LIMIT_EXCEEDED,
            f"{GUARDRAILS_CONFIG_PATH} may define at most {MAX_INLINE_RULES} inline rules",
        )

    inline_rules = []
    for item in raw_rules:
        if not isinstance(item, dict):
            raise JaasError(
                ErrorCode.INVALID_CUSTOM_GUARDRAIL, "each entry in 'rules' must be a mapping"
            )
        missing = _REQUIRED_INLINE_KEYS - item.keys()
        if missing:
            raise JaasError(
                ErrorCode.INVALID_CUSTOM_GUARDRAIL,
                f"inline rule is missing keys: {sorted(missing)}",
            )
        _validate_slug(item["slug"])
        inline_rules.append(
            InlineCustomRule(
                slug=item["slug"],
                name=item["name"],
                description=item.get("description", ""),
                category=item["category"],
                severity=item["severity"],
                standard_ref=item.get("standard_ref", ""),
                kind=item["kind"],
                config=item["config"],
            )
        )

    return SkillGuardrailConfig(apply=tuple(apply_ids), inline_rules=tuple(inline_rules))


def resolve_guardrails_for_skill(
    *,
    tenant_id: str,
    skill_id: str,
    policy: GuardrailPolicy,
    catalog_ids: frozenset[str],
    skill_config: SkillGuardrailConfig,
    custom_rule_store: CustomGuardrailRuleStore,
) -> tuple[frozenset[str], tuple[CustomGuardrailRule, ...]]:
    """Combines the tenant's baseline policy with what this specific
    skill's own `.jaas/guardrails.yaml` additionally applies. Returns
    exactly the two things `GuardrailsClient.scan()` needs:
    `enabled_check_ids` (catalog ids) and `custom_rules` (ad-hoc
    definitions, tenant-owned or inline-to-this-skill)."""
    enabled_ids = set(policy.enabled_check_ids)
    custom_rules: list[CustomGuardrailRule] = []
    prefix = f"custom:{tenant_id}:"

    for rule_id in skill_config.apply:
        if rule_id in catalog_ids:
            enabled_ids.add(rule_id)
            continue
        if rule_id.startswith(prefix):
            slug = rule_id.removeprefix(prefix)
            tenant_rule = custom_rule_store.get(tenant_id, slug)
            if tenant_rule is not None:
                custom_rules.append(tenant_rule)
                continue
        raise JaasError(
            ErrorCode.INVALID_CUSTOM_GUARDRAIL,
            f"{GUARDRAILS_CONFIG_PATH} applies unknown rule id '{rule_id}'",
        )

    for inline in skill_config.inline_rules:
        custom_rules.append(
            CustomGuardrailRule(
                id=f"custom:{tenant_id}:{skill_id}:{inline.slug}",
                tenant_id=tenant_id,
                slug=inline.slug,
                name=inline.name,
                description=inline.description,
                category=inline.category,
                severity=inline.severity,
                standard_ref=inline.standard_ref,
                kind=inline.kind,
                config=inline.config,
                # Never persisted — this rule only exists for the duration
                # of this one scan, sourced fresh from the skill's own repo
                # every time. created_by/created_at are meaningless here.
                created_by="",
                created_at="",
            )
        )

    return frozenset(enabled_ids), tuple(custom_rules)
