import pytest

from jaas_registry.common.errors import JaasError
from jaas_registry.guardrails.custom_rules import (
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
    with pytest.raises(JaasError, match="not a valid rule slug"):
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

    with pytest.raises(JaasError, match="maximum"):
        _put(store, slug="one-too-many")


def test_put_updating_an_existing_rule_does_not_count_against_the_limit(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    for i in range(MAX_RULES_PER_TENANT):
        _put(store, slug=f"rule-{i}")

    # Re-putting an existing slug is an update, not a new rule — must not
    # be rejected just because the tenant is already at the cap.
    updated = _put(store, slug="rule-0", name="Renamed")
    assert updated.name == "Renamed"


def test_put_defaults_to_version_1_0_0(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    rule = _put(store)
    assert rule.version == "1.0.0"


def test_put_records_a_version_snapshot(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    _put(store, version="1.0.0")
    _put(store, version="1.1.0", name="Renamed")

    versions = store.list_versions("tnt_1", "no-todo")
    assert [v.version for v in versions] == ["1.0.0", "1.1.0"]
    assert versions[0].name == "No TODO"
    assert versions[1].name == "Renamed"


def test_put_at_an_existing_version_overwrites_that_snapshot(tmp_path):
    # jaasctl guardrails push repeatedly re-puts the same slug at the same
    # implicit "1.0.0" version with edited content — this must keep
    # working exactly as it did before versioning existed, not be treated
    # as violating some new immutability guarantee.
    store = CustomGuardrailRuleStore(tmp_path)
    _put(store, version="1.0.0", name="First")
    _put(store, version="1.0.0", name="Second")

    versions = store.list_versions("tnt_1", "no-todo")
    assert len(versions) == 1
    assert versions[0].name == "Second"
    assert store.get("tnt_1", "no-todo").name == "Second"


def test_list_versions_is_empty_for_a_rule_that_was_never_published(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    assert store.list_versions("tnt_1", "does-not-exist") == []


def test_delete_removes_version_snapshots_too(tmp_path):
    store = CustomGuardrailRuleStore(tmp_path)
    _put(store, version="1.0.0")
    _put(store, version="1.1.0")

    assert store.delete("tnt_1", "no-todo") is True
    assert store.list_versions("tnt_1", "no-todo") == []
