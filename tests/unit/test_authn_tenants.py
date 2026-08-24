from jaas_registry.authn.models import TenantKind, TenantRole
from jaas_registry.authn.tenants import MembershipStore, TenantStore


def test_ensure_personal_tenant_is_idempotent(tmp_path):
    store = TenantStore(tmp_path)

    first = store.ensure_personal_tenant(user_id="usr_abc", display_name="Alice")
    second = store.ensure_personal_tenant(user_id="usr_abc", display_name="Alice")

    assert first.id == second.id
    assert first.kind == TenantKind.PERSONAL


def test_different_users_get_different_personal_tenants(tmp_path):
    store = TenantStore(tmp_path)

    a = store.ensure_personal_tenant(user_id="usr_a", display_name="A")
    b = store.ensure_personal_tenant(user_id="usr_b", display_name="B")

    assert a.id != b.id


def test_create_organization_tenant(tmp_path):
    store = TenantStore(tmp_path)
    tenant = store.create(name="Acme Corp")

    assert tenant.kind == TenantKind.ORGANIZATION
    assert store.get(tenant.id) == tenant


def test_membership_store_round_trip(tmp_path):
    store = MembershipStore(tmp_path)

    store.add(tenant_id="tnt_1", user_id="usr_1", role=TenantRole.ADMIN)
    store.add(tenant_id="tnt_1", user_id="usr_2", role=TenantRole.MEMBER)
    store.add(tenant_id="tnt_2", user_id="usr_1", role=TenantRole.MEMBER)

    assert store.get(tenant_id="tnt_1", user_id="usr_1").role == TenantRole.ADMIN

    user_1_memberships = store.list_for_user("usr_1")
    assert {m.tenant_id for m in user_1_memberships} == {"tnt_1", "tnt_2"}

    tenant_1_members = store.list_for_tenant("tnt_1")
    assert {m.user_id for m in tenant_1_members} == {"usr_1", "usr_2"}


def test_membership_get_missing_returns_none(tmp_path):
    store = MembershipStore(tmp_path)
    assert store.get(tenant_id="tnt_x", user_id="usr_x") is None
