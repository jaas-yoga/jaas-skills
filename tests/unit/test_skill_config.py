import pytest

from jaas_registry.common.errors import JaasError
from jaas_registry.guardrails.custom_rules import CustomGuardrailRuleStore
from jaas_registry.guardrails.policy import GuardrailPolicy
from jaas_registry.guardrails.skill_config import (
    MAX_INLINE_RULES,
    SkillGuardrailConfig,
    parse_skill_guardrail_config,
    resolve_guardrails_for_skill,
)


class TestParse:
    def test_none_input_is_an_empty_config(self):
        assert parse_skill_guardrail_config(None) == SkillGuardrailConfig(
            apply=(), inline_rules=()
        )

    def test_empty_bytes_is_an_empty_config(self):
        assert parse_skill_guardrail_config(b"") == SkillGuardrailConfig(apply=(), inline_rules=())

    def test_apply_only(self):
        config = parse_skill_guardrail_config(b"apply:\n  - pii-pattern-scan\n")
        assert config.apply == ("pii-pattern-scan",)
        assert config.inline_rules == ()

    def test_inline_rule(self):
        raw = b"""
rules:
  - slug: no-todo
    name: No TODO
    category: CODE_SAFETY
    severity: WARN
    kind: regex_file_scan
    config:
      scope: all_files
      patterns: [{name: todo, regex: "TODO"}]
"""
        config = parse_skill_guardrail_config(raw)
        assert len(config.inline_rules) == 1
        rule = config.inline_rules[0]
        assert rule.slug == "no-todo"
        assert rule.kind == "regex_file_scan"

    def test_rejects_invalid_yaml(self):
        with pytest.raises(JaasError, match="not valid YAML"):
            parse_skill_guardrail_config(b"apply: [unterminated")

    def test_rejects_non_mapping_top_level(self):
        with pytest.raises(JaasError, match="must be a mapping"):
            parse_skill_guardrail_config(b"- a\n- b\n")

    def test_rejects_apply_not_a_list_of_strings(self):
        with pytest.raises(JaasError, match="'apply' must be a list"):
            parse_skill_guardrail_config(b"apply: not-a-list-but-a-string\n")

    def test_rejects_too_many_inline_rules(self):
        one_rule = (
            "  - slug: rule-{i}\n"
            "    name: X\n"
            "    category: CODE_SAFETY\n"
            "    severity: WARN\n"
            "    kind: regex_file_scan\n"
            "    config: {{scope: all_files, patterns: []}}\n"
        )
        rules_yaml = "rules:\n" + "".join(
            one_rule.format(i=i) for i in range(MAX_INLINE_RULES + 1)
        )
        with pytest.raises(JaasError, match="at most"):
            parse_skill_guardrail_config(rules_yaml.encode())

    def test_rejects_inline_rule_missing_keys(self):
        raw = b"rules:\n  - slug: no-todo\n    name: No TODO\n"
        with pytest.raises(JaasError, match="missing keys"):
            parse_skill_guardrail_config(raw)

    def test_rejects_invalid_slug(self):
        raw = b"""
rules:
  - slug: "Not A Slug!"
    name: X
    category: CODE_SAFETY
    severity: WARN
    kind: regex_file_scan
    config: {}
"""
        with pytest.raises(JaasError, match="not a valid rule slug"):
            parse_skill_guardrail_config(raw)


CATALOG_IDS = frozenset({"secret-scan", "pii-pattern-scan"})


def _policy(enabled=frozenset({"secret-scan"})):
    return GuardrailPolicy(tenant_id="tnt_1", enabled_check_ids=enabled)


class TestResolve:
    def test_no_config_returns_tenant_policy_unchanged(self, tmp_path):
        store = CustomGuardrailRuleStore(tmp_path)
        enabled, custom = resolve_guardrails_for_skill(
            tenant_id="tnt_1",
            skill_id="acme.tool.x",
            policy=_policy(),
            catalog_ids=CATALOG_IDS,
            skill_config=SkillGuardrailConfig(apply=(), inline_rules=()),
            custom_rule_store=store,
        )
        assert enabled == frozenset({"secret-scan"})
        assert custom == ()

    def test_apply_adds_a_catalog_id_on_top_of_tenant_policy(self, tmp_path):
        store = CustomGuardrailRuleStore(tmp_path)
        enabled, _ = resolve_guardrails_for_skill(
            tenant_id="tnt_1",
            skill_id="acme.tool.x",
            policy=_policy(),
            catalog_ids=CATALOG_IDS,
            skill_config=SkillGuardrailConfig(apply=("pii-pattern-scan",), inline_rules=()),
            custom_rule_store=store,
        )
        assert enabled == frozenset({"secret-scan", "pii-pattern-scan"})

    def test_apply_a_tenant_custom_rule_id(self, tmp_path):
        store = CustomGuardrailRuleStore(tmp_path)
        store.put(
            tenant_id="tnt_1",
            slug="no-todo",
            name="No TODO",
            description="",
            category="CODE_SAFETY",
            severity="WARN",
            standard_ref="",
            kind="regex_file_scan",
            config={"scope": "all_files", "patterns": []},
            created_by="usr_1",
        )
        _, custom = resolve_guardrails_for_skill(
            tenant_id="tnt_1",
            skill_id="acme.tool.x",
            policy=_policy(),
            catalog_ids=CATALOG_IDS,
            skill_config=SkillGuardrailConfig(apply=("custom:tnt_1:no-todo",), inline_rules=()),
            custom_rule_store=store,
        )
        assert len(custom) == 1
        assert custom[0].id == "custom:tnt_1:no-todo"

    def test_apply_unknown_id_raises(self, tmp_path):
        store = CustomGuardrailRuleStore(tmp_path)
        with pytest.raises(JaasError, match="unknown rule id"):
            resolve_guardrails_for_skill(
                tenant_id="tnt_1",
                skill_id="acme.tool.x",
                policy=_policy(),
                catalog_ids=CATALOG_IDS,
                skill_config=SkillGuardrailConfig(apply=("not-a-real-id",), inline_rules=()),
                custom_rule_store=store,
            )

    def test_apply_another_tenants_custom_rule_id_is_rejected(self, tmp_path):
        store = CustomGuardrailRuleStore(tmp_path)
        store.put(
            tenant_id="tnt_2",
            slug="no-todo",
            name="No TODO",
            description="",
            category="CODE_SAFETY",
            severity="WARN",
            standard_ref="",
            kind="regex_file_scan",
            config={"scope": "all_files", "patterns": []},
            created_by="usr_1",
        )
        with pytest.raises(JaasError, match="unknown rule id"):
            resolve_guardrails_for_skill(
                tenant_id="tnt_1",
                skill_id="acme.tool.x",
                policy=_policy(),
                catalog_ids=CATALOG_IDS,
                skill_config=SkillGuardrailConfig(
                    apply=("custom:tnt_2:no-todo",), inline_rules=()
                ),
                custom_rule_store=store,
            )

    def test_inline_rule_gets_a_skill_scoped_id_and_is_never_persisted(self, tmp_path):
        from jaas_registry.guardrails.skill_config import InlineCustomRule

        store = CustomGuardrailRuleStore(tmp_path)
        inline = InlineCustomRule(
            slug="no-todo",
            name="No TODO",
            description="",
            category="CODE_SAFETY",
            severity="WARN",
            standard_ref="",
            kind="regex_file_scan",
            config={"scope": "all_files", "patterns": []},
        )
        _, custom = resolve_guardrails_for_skill(
            tenant_id="tnt_1",
            skill_id="acme.tool.x",
            policy=_policy(),
            catalog_ids=CATALOG_IDS,
            skill_config=SkillGuardrailConfig(apply=(), inline_rules=(inline,)),
            custom_rule_store=store,
        )
        assert custom[0].id == "custom:tnt_1:acme.tool.x:no-todo"
        assert store.list_for_tenant("tnt_1") == []  # never persisted
