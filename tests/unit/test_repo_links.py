import pytest

from jaas_registry.authn.repo_links import RepoLinkStore
from jaas_registry.common.errors import JaasError


def test_create_then_get_round_trips(tmp_path):
    store = RepoLinkStore(tmp_path)
    link = store.create(
        tenant_id="tnt_1",
        skill_id="acme.tool.x",
        repo_url="https://github.com/acme/tool-x",
        created_by="usr_1",
    )
    fetched = store.get(tenant_id="tnt_1", skill_id="acme.tool.x")
    assert fetched == link


def test_get_returns_none_when_missing(tmp_path):
    store = RepoLinkStore(tmp_path)
    assert store.get(tenant_id="tnt_1", skill_id="acme.tool.x") is None


def test_list_for_tenant_is_isolated_per_tenant(tmp_path):
    store = RepoLinkStore(tmp_path)
    store.create(tenant_id="tnt_1", skill_id="a", repo_url="u1", created_by="usr_1")
    store.create(tenant_id="tnt_2", skill_id="b", repo_url="u2", created_by="usr_1")
    assert [link.skill_id for link in store.list_for_tenant("tnt_1")] == ["a"]
    assert [link.skill_id for link in store.list_for_tenant("tnt_2")] == ["b"]


def test_create_rejects_duplicate_within_same_tenant(tmp_path):
    store = RepoLinkStore(tmp_path)
    store.create(tenant_id="tnt_1", skill_id="acme.tool.x", repo_url="u1", created_by="usr_1")
    with pytest.raises(JaasError, match="already linked"):
        store.create(tenant_id="tnt_1", skill_id="acme.tool.x", repo_url="u2", created_by="usr_1")


def test_create_rejects_skill_id_already_claimed_by_another_tenant(tmp_path):
    """Anti-squatting: a skill id link is globally unique across tenants,
    not just unique within one — otherwise two tenants could each believe
    they own the right to release the same skill id."""
    store = RepoLinkStore(tmp_path)
    store.create(tenant_id="tnt_1", skill_id="acme.tool.x", repo_url="u1", created_by="usr_1")
    with pytest.raises(JaasError, match="different tenant"):
        store.create(tenant_id="tnt_2", skill_id="acme.tool.x", repo_url="u2", created_by="usr_2")


def test_delete_returns_false_when_missing(tmp_path):
    store = RepoLinkStore(tmp_path)
    assert store.delete(tenant_id="tnt_1", skill_id="acme.tool.x") is False


def test_delete_removes_link(tmp_path):
    store = RepoLinkStore(tmp_path)
    store.create(tenant_id="tnt_1", skill_id="acme.tool.x", repo_url="u1", created_by="usr_1")
    assert store.delete(tenant_id="tnt_1", skill_id="acme.tool.x") is True
    assert store.get(tenant_id="tnt_1", skill_id="acme.tool.x") is None


def test_release_branches_default_to_empty():
    from jaas_registry.authn.repo_links import RepoLink

    link = RepoLink(
        id="lnk_1",
        tenant_id="tnt_1",
        skill_id="acme.tool.x",
        repo_url="u1",
        created_by="usr_1",
        created_at="2026-01-01T00:00:00Z",
    )
    assert link.release_branches == ()


def test_create_stores_release_branches_and_round_trips(tmp_path):
    store = RepoLinkStore(tmp_path)
    link = store.create(
        tenant_id="tnt_1",
        skill_id="acme.tool.x",
        repo_url="u1",
        created_by="usr_1",
        release_branches=("main", "staging"),
    )
    assert link.release_branches == ("main", "staging")
    fetched = store.get(tenant_id="tnt_1", skill_id="acme.tool.x")
    assert fetched.release_branches == ("main", "staging")


def test_pre_existing_link_json_without_release_branches_key_still_loads(tmp_path):
    """A link written before this field existed has no key at all in its
    JSON file — must default to (), not crash."""
    import json

    store = RepoLinkStore(tmp_path)
    store.create(tenant_id="tnt_1", skill_id="acme.tool.x", repo_url="u1", created_by="usr_1")
    path = tmp_path / "repo_links" / "tnt_1__acme.tool.x.json"
    data = json.loads(path.read_text())
    del data["release_branches"]
    path.write_text(json.dumps(data))

    fetched = store.get(tenant_id="tnt_1", skill_id="acme.tool.x")
    assert fetched.release_branches == ()


def test_update_release_branches_replaces_the_list(tmp_path):
    store = RepoLinkStore(tmp_path)
    store.create(
        tenant_id="tnt_1",
        skill_id="acme.tool.x",
        repo_url="u1",
        created_by="usr_1",
        release_branches=("main",),
    )
    updated = store.update_release_branches(
        tenant_id="tnt_1", skill_id="acme.tool.x", release_branches=("main", "staging")
    )
    assert updated.release_branches == ("main", "staging")
    assert store.get(tenant_id="tnt_1", skill_id="acme.tool.x").release_branches == (
        "main",
        "staging",
    )


def test_update_release_branches_raises_when_link_missing(tmp_path):
    store = RepoLinkStore(tmp_path)
    with pytest.raises(JaasError, match="no repo link"):
        store.update_release_branches(
            tenant_id="tnt_1", skill_id="acme.tool.x", release_branches=("main",)
        )


def test_update_release_branches_cannot_reach_another_tenants_link(tmp_path):
    """The store method itself is tenant-scoped by construction (the file
    key is tenant_id__skill_id) — a caller passing tenant_id="tnt_2" simply
    finds no link, it can never mutate tnt_1's."""
    store = RepoLinkStore(tmp_path)
    store.create(
        tenant_id="tnt_1",
        skill_id="acme.tool.x",
        repo_url="u1",
        created_by="usr_1",
        release_branches=("main",),
    )
    with pytest.raises(JaasError, match="no repo link"):
        store.update_release_branches(
            tenant_id="tnt_2", skill_id="acme.tool.x", release_branches=("evil",)
        )
    assert store.get(tenant_id="tnt_1", skill_id="acme.tool.x").release_branches == ("main",)
