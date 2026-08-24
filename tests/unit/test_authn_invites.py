from rune_registry.authn.invites import InviteStore
from rune_registry.authn.models import TenantRole


def test_create_and_list_for_tenant(tmp_path):
    store = InviteStore(tmp_path)

    store.create(
        tenant_id="tnt_1",
        email="alice@example.com",
        role=TenantRole.MEMBER,
        invited_by="usr_admin",
    )

    invites = store.list_for_tenant("tnt_1")
    assert len(invites) == 1
    assert invites[0].email == "alice@example.com"
    assert invites[0].role == TenantRole.MEMBER


def test_email_is_normalized_case_insensitively(tmp_path):
    store = InviteStore(tmp_path)
    store.create(
        tenant_id="tnt_1", email="Alice@Example.COM", role=TenantRole.MEMBER, invited_by="usr_admin"
    )

    matches = store.pop_for_email("alice@example.com")

    assert len(matches) == 1
    assert matches[0].email == "alice@example.com"


def test_pop_for_email_removes_the_invite(tmp_path):
    store = InviteStore(tmp_path)
    store.create(
        tenant_id="tnt_1", email="alice@example.com", role=TenantRole.MEMBER, invited_by="usr_admin"
    )

    first = store.pop_for_email("alice@example.com")
    second = store.pop_for_email("alice@example.com")

    assert len(first) == 1
    assert second == []


def test_pop_for_email_finds_invites_across_multiple_tenants(tmp_path):
    store = InviteStore(tmp_path)
    store.create(
        tenant_id="tnt_1", email="alice@example.com", role=TenantRole.MEMBER, invited_by="usr_admin"
    )
    store.create(
        tenant_id="tnt_2", email="alice@example.com", role=TenantRole.ADMIN, invited_by="usr_other"
    )

    matches = store.pop_for_email("alice@example.com")

    assert {m.tenant_id for m in matches} == {"tnt_1", "tnt_2"}


def test_pop_for_email_does_not_affect_a_different_email(tmp_path):
    store = InviteStore(tmp_path)
    store.create(
        tenant_id="tnt_1", email="alice@example.com", role=TenantRole.MEMBER, invited_by="usr_admin"
    )

    assert store.pop_for_email("bob@example.com") == []
    assert len(store.list_for_tenant("tnt_1")) == 1
