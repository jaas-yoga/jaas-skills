from jaas_registry.sharing.grants import GrantStore
from jaas_registry.sharing.models import GranteeType, SharePermission


def test_create_and_list_for_skill(tmp_path):
    store = GrantStore(tmp_path)

    grant = store.create(
        skill_id="acme.text.summarizer",
        grantee_type=GranteeType.USER,
        grantee_id="usr_1",
        permission=SharePermission.READ,
        granted_by="usr_owner",
    )

    assert grant.id.startswith("grant_")
    assert store.get(skill_id="acme.text.summarizer", grant_id=grant.id) == grant
    assert store.list_for_skill("acme.text.summarizer") == [grant]


def test_list_for_skill_only_returns_that_skills_grants(tmp_path):
    store = GrantStore(tmp_path)
    store.create(
        skill_id="acme.text.summarizer",
        grantee_type=GranteeType.USER,
        grantee_id="usr_1",
        permission=SharePermission.READ,
        granted_by="usr_owner",
    )
    store.create(
        skill_id="acme.vision.classifier",
        grantee_type=GranteeType.USER,
        grantee_id="usr_1",
        permission=SharePermission.READ,
        granted_by="usr_owner",
    )

    assert len(store.list_for_skill("acme.text.summarizer")) == 1
    assert len(store.list_for_skill("acme.vision.classifier")) == 1


def test_list_for_grantee_finds_grants_across_skills(tmp_path):
    store = GrantStore(tmp_path)
    store.create(
        skill_id="acme.text.summarizer",
        grantee_type=GranteeType.USER,
        grantee_id="usr_1",
        permission=SharePermission.READ,
        granted_by="usr_owner",
    )
    store.create(
        skill_id="acme.vision.classifier",
        grantee_type=GranteeType.TENANT,
        grantee_id="tnt_1",
        permission=SharePermission.READ,
        granted_by="usr_owner",
    )

    user_grants = store.list_for_grantee(grantee_type=GranteeType.USER, grantee_id="usr_1")
    assert {g.skill_id for g in user_grants} == {"acme.text.summarizer"}

    tenant_grants = store.list_for_grantee(grantee_type=GranteeType.TENANT, grantee_id="tnt_1")
    assert {g.skill_id for g in tenant_grants} == {"acme.vision.classifier"}


def test_revoke_removes_the_grant(tmp_path):
    store = GrantStore(tmp_path)
    grant = store.create(
        skill_id="acme.text.summarizer",
        grantee_type=GranteeType.USER,
        grantee_id="usr_1",
        permission=SharePermission.READ,
        granted_by="usr_owner",
    )

    revoked = store.revoke(skill_id="acme.text.summarizer", grant_id=grant.id)

    assert revoked is True
    assert store.get(skill_id="acme.text.summarizer", grant_id=grant.id) is None
    assert store.list_for_skill("acme.text.summarizer") == []


def test_revoke_unknown_grant_returns_false(tmp_path):
    store = GrantStore(tmp_path)
    assert store.revoke(skill_id="acme.text.summarizer", grant_id="grant_ghost") is False


def test_get_unknown_grant_returns_none(tmp_path):
    store = GrantStore(tmp_path)
    assert store.get(skill_id="acme.text.summarizer", grant_id="grant_ghost") is None
