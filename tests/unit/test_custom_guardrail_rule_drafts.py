from jaas_registry.guardrails.custom_rule_drafts import CustomGuardrailRuleDraftStore
from jaas_registry.guardrails.custom_rules import CustomGuardrailRuleStore


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


def test_create_blank_draft_has_placeholder_fields(tmp_path):
    store = CustomGuardrailRuleDraftStore(tmp_path)
    draft = store.create(tenant_id="tnt_1", created_by="usr_1")

    assert draft.id.startswith("cgrdraft_")
    assert draft.tenant_id == "tnt_1"
    assert draft.slug == ""
    assert draft.version == "1.0.0"
    assert draft.forked_from_version is None


def test_create_forking_a_published_rule_copies_its_fields_and_bumps_patch(tmp_path):
    rule_store = CustomGuardrailRuleStore(tmp_path)
    rule = _put(rule_store, version="1.2.3")
    draft_store = CustomGuardrailRuleDraftStore(tmp_path)

    draft = draft_store.create(tenant_id="tnt_1", created_by="usr_2", fork_from=rule)

    assert draft.slug == "no-todo"
    assert draft.name == "No TODO"
    assert draft.config == rule.config
    assert draft.version == "1.2.4"
    assert draft.forked_from_version == "1.2.3"


def test_get_then_update_round_trips(tmp_path):
    store = CustomGuardrailRuleDraftStore(tmp_path)
    draft = store.create(tenant_id="tnt_1", created_by="usr_1")

    updated = store.update(
        draft.id,
        slug="no-secrets",
        name="No Secrets",
        description="",
        category="SECRET",
        severity="BLOCK",
        standard_ref="",
        kind="regex_file_scan",
        config={},
        version="1.0.0",
    )

    assert updated.slug == "no-secrets"
    assert store.get(draft.id).slug == "no-secrets"
    # created_at/created_by/forked_from_version survive an update untouched
    assert updated.created_by == "usr_1"


def test_update_unknown_draft_returns_none(tmp_path):
    store = CustomGuardrailRuleDraftStore(tmp_path)
    result = store.update(
        "cgrdraft_does_not_exist",
        slug="x",
        name="x",
        description="",
        category="x",
        severity="WARN",
        standard_ref="",
        kind="x",
        config={},
        version="1.0.0",
    )
    assert result is None


def test_list_for_tenant_is_isolated_per_tenant_and_newest_first(tmp_path):
    store = CustomGuardrailRuleDraftStore(tmp_path)
    first = store.create(tenant_id="tnt_1", created_by="usr_1")
    second = store.create(tenant_id="tnt_1", created_by="usr_1")
    store.create(tenant_id="tnt_2", created_by="usr_2")

    ids = [d.id for d in store.list_for_tenant("tnt_1")]
    assert ids == [second.id, first.id]


def test_delete_removes_draft(tmp_path):
    store = CustomGuardrailRuleDraftStore(tmp_path)
    draft = store.create(tenant_id="tnt_1", created_by="usr_1")

    assert store.delete(draft.id) is True
    assert store.get(draft.id) is None


def test_delete_returns_false_when_missing(tmp_path):
    store = CustomGuardrailRuleDraftStore(tmp_path)
    assert store.delete("cgrdraft_does_not_exist") is False
