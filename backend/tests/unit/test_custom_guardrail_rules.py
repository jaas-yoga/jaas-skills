import pytest

from rune_registry.common.errors import RuneError
from rune_registry.guardrails.custom_rules import (
    MAX_RULES_PER_TENANT,
    CustomGuardrailRuleStore,
    make_id,
)


def _put(store, tenant_id="tnt_1", slug="no-todo", **overrides):
    kwargs = dict(
        tenant_id=tenant_id,
        slug=slug,
        name="No TODO",
        description="Flags TODO comments.",
        category="CODE_SAFETY",
        severity="WARN",
        standard_ref="",
        kind="regex_file_scan",
        config={"scope": "all_files", "patterns": [{"name": "todo", "regex": "TODO"}]},
        created_by="usr_1",
    )
    kwargs.update(overrides)
    return store.put(**kwargs)


def test_make_id_is_namespaced_by_tenant():
    assert make_id("tnt_1", "no-todo") == "custom:tnt_1:no-todo"
    assert make_id("tnt_2", "no-todo") != make_id("tnt_1", "no-todo")


def test_put_then_get_round_trips(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    rule = _put(store)
    fetched = store.get("tnt_1", "no-todo")
    assert fetched == rule
    assert fetched.id == "custom:tnt_1:no-todo"


def test_get_returns_none_when_missing(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    assert store.get("tnt_1", "does-not-exist") is None


def test_list_for_tenant_is_isolated_per_tenant(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    _put(store, tenant_id="tnt_1", slug="a")
    _put(store, tenant_id="tnt_2", slug="b")
    assert [r.slug for r in store.list_for_tenant("tnt_1")] == ["a"]
    assert [r.slug for r in store.list_for_tenant("tnt_2")] == ["b"]


def test_put_rejects_invalid_slug(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    with pytest.raises(RuneError, match="not a valid rule slug"):
        _put(store, slug="Not A Slug!")


def test_delete_returns_false_when_missing(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    assert store.delete("tnt_1", "does-not-exist") is False


def test_delete_removes_rule(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    _put(store)
    assert store.delete("tnt_1", "no-todo") is True
    assert store.get("tnt_1", "no-todo") is None


def test_put_enforces_per_tenant_rule_limit(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    for i in range(MAX_RULES_PER_TENANT):
        _put(store, slug=f"rule-{i}")

    with pytest.raises(RuneError, match="maximum"):
        _put(store, slug="one-too-many")


def test_put_updating_an_existing_rule_does_not_count_against_the_limit(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    for i in range(MAX_RULES_PER_TENANT):
        _put(store, slug=f"rule-{i}")

    # Re-putting an existing slug is an update, not a new rule — must not
    # be rejected just because the tenant is already at the cap.
    updated = _put(store, slug="rule-0", name="Renamed")
    assert updated.name == "Renamed"
