from dataclasses import dataclass

import pytest

from jaas_registry.authn.google import GoogleIdentity
from jaas_registry.authn.invites import InviteStore
from jaas_registry.authn.models import TenantRole
from jaas_registry.authn.service import AuthService
from jaas_registry.authn.tenants import MembershipStore, TenantStore
from jaas_registry.authn.tokens import RefreshTokenStore
from jaas_registry.authn.users import UserStore
from jaas_registry.authz.jwt_validation import decode_token
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError

SECRET = "test-only-shared-secret-at-least-32-bytes!!"


@dataclass(frozen=True)
class FakeGoogleIdentityVerifier:
    identity: GoogleIdentity

    def verify(self, google_id_token_jwt: str) -> GoogleIdentity:
        if google_id_token_jwt != "valid-token":
            raise JaasError(ErrorCode.INVALID_GOOGLE_TOKEN, "bad token")
        return self.identity


def _decode(token: str, settings: Settings):
    return decode_token(
        token, secret=SECRET, issuer=settings.jwt_issuer, audience=settings.jwt_audience
    )


@pytest.fixture
def settings(tmp_path):
    return Settings(
        storage_root=tmp_path / "storage", policy_dir=tmp_path / "policy", jwt_secret=SECRET
    )


@pytest.fixture
def service(settings):
    return AuthService(
        settings=settings,
        verifier=FakeGoogleIdentityVerifier(
            GoogleIdentity(sub="google-1", email="alice@example.com", name="Alice", picture=None)
        ),
        user_store=UserStore(settings.policy_dir),
        tenant_store=TenantStore(settings.policy_dir),
        membership_store=MembershipStore(settings.policy_dir),
        refresh_token_store=RefreshTokenStore(settings.policy_dir),
        invite_store=InviteStore(settings.policy_dir),
    )


def test_dev_login_is_disabled_when_no_password_configured(service):
    with pytest.raises(JaasError) as excinfo:
        service.sign_in_with_dev_credentials("owner@jaas.local", "anything")
    assert excinfo.value.code == ErrorCode.DEV_LOGIN_NOT_CONFIGURED


def test_dev_login_creates_the_seeded_owner_and_admin_as_admins_of_their_own_tenants(
    settings, tmp_path
):
    dev_settings = Settings(
        storage_root=tmp_path / "storage2",
        policy_dir=tmp_path / "policy2",
        jwt_secret=SECRET,
        dev_login_password="shared-dev-password",
    )
    service = AuthService(
        settings=dev_settings,
        verifier=None,
        user_store=UserStore(dev_settings.policy_dir),
        tenant_store=TenantStore(dev_settings.policy_dir),
        membership_store=MembershipStore(dev_settings.policy_dir),
        refresh_token_store=RefreshTokenStore(dev_settings.policy_dir),
    )

    owner = service.sign_in_with_dev_credentials("owner@jaas.local", "shared-dev-password")
    admin = service.sign_in_with_dev_credentials("admin@jaas.local", "shared-dev-password")

    assert owner.user.email == "owner@jaas.local"
    assert owner.tenants[0].role is TenantRole.ADMIN
    assert admin.user.email == "admin@jaas.local"
    assert admin.tenants[0].role is TenantRole.ADMIN
    assert owner.active_tenant_id != admin.active_tenant_id

    # Same password, wrong/unknown email — still rejected.
    with pytest.raises(JaasError) as excinfo:
        service.sign_in_with_dev_credentials("nobody@jaas.local", "shared-dev-password")
    assert excinfo.value.code == ErrorCode.INVALID_DEV_LOGIN

    # Right email, wrong password — rejected.
    with pytest.raises(JaasError) as excinfo:
        service.sign_in_with_dev_credentials("owner@jaas.local", "wrong")
    assert excinfo.value.code == ErrorCode.INVALID_DEV_LOGIN


def test_first_sign_in_creates_user_and_personal_tenant_as_admin(service, settings):
    result = service.sign_in_with_google("valid-token")

    assert result.user.email == "alice@example.com"
    assert len(result.tenants) == 1
    assert result.tenants[0].role == TenantRole.ADMIN
    assert result.active_tenant_id == result.tenants[0].tenant_id

    claims = _decode(result.access_token, settings)
    assert claims.subject == result.user.id
    assert "tenant:admin" in claims.scopes
    # IMPLEMENTATION_PLAN.md Phase 3.4: PUT /skills/{id}/governance is
    # gated on this scope, same owner-or-tenant-admin tier as skills:share
    # — an owner must be able to set governance on their own skill
    # regardless of tenant role, so it belongs on every member's base
    # scope set, not just admins'.
    assert "skills:governance" in claims.scopes


def test_second_sign_in_reuses_the_same_user_and_tenant(service):
    first = service.sign_in_with_google("valid-token")
    second = service.sign_in_with_google("valid-token")

    assert first.user.id == second.user.id
    assert first.active_tenant_id == second.active_tenant_id


def test_invalid_google_token_is_rejected(service):
    with pytest.raises(JaasError) as excinfo:
        service.sign_in_with_google("garbage")
    assert excinfo.value.code == ErrorCode.INVALID_GOOGLE_TOKEN


def test_sign_in_without_a_configured_verifier_fails_closed(settings):
    service = AuthService(
        settings=settings,
        verifier=None,
        user_store=UserStore(settings.policy_dir),
        tenant_store=TenantStore(settings.policy_dir),
        membership_store=MembershipStore(settings.policy_dir),
        refresh_token_store=RefreshTokenStore(settings.policy_dir),
    )

    with pytest.raises(JaasError) as excinfo:
        service.sign_in_with_google("valid-token")
    assert excinfo.value.code == ErrorCode.INVALID_GOOGLE_TOKEN


def test_sign_in_requesting_a_foreign_tenant_is_rejected(service):
    with pytest.raises(JaasError) as excinfo:
        service.sign_in_with_google("valid-token", requested_tenant_id="tnt_not_mine")
    assert excinfo.value.code == ErrorCode.NOT_TENANT_MEMBER


def test_refresh_mints_a_new_access_token_for_the_same_tenant(service, settings):
    signed_in = service.sign_in_with_google("valid-token")

    refreshed = service.refresh(signed_in.refresh_token)

    assert refreshed.active_tenant_id == signed_in.active_tenant_id
    assert refreshed.access_token != signed_in.access_token
    claims = _decode(refreshed.access_token, settings)
    assert claims.subject == signed_in.user.id


def test_refresh_with_invalid_token_is_rejected(service):
    with pytest.raises(JaasError) as excinfo:
        service.refresh("not-a-real-refresh-token")
    assert excinfo.value.code == ErrorCode.INVALID_REFRESH_TOKEN


def test_refresh_can_switch_to_a_second_tenant_the_user_belongs_to(service, settings):
    signed_in = service.sign_in_with_google("valid-token")
    second_tenant = TenantStore(settings.policy_dir).create(name="Acme Corp")
    MembershipStore(settings.policy_dir).add(
        tenant_id=second_tenant.id, user_id=signed_in.user.id, role=TenantRole.MEMBER
    )

    refreshed = service.refresh(signed_in.refresh_token, requested_tenant_id=second_tenant.id)

    assert refreshed.active_tenant_id == second_tenant.id
    claims = _decode(refreshed.access_token, settings)
    assert "tenant:admin" not in claims.scopes  # member role in this second tenant, not admin


def test_pending_invite_becomes_a_real_membership_on_sign_in(service, settings):
    tenant_store = TenantStore(settings.policy_dir)
    invites = InviteStore(settings.policy_dir)
    tenant = tenant_store.create(name="Acme Corp")
    invites.create(
        tenant_id=tenant.id,
        email="alice@example.com",
        role=TenantRole.MEMBER,
        invited_by="usr_admin",
    )

    result = service.sign_in_with_google("valid-token")

    tenant_ids = {t.tenant_id for t in result.tenants}
    assert tenant.id in tenant_ids
    invited_view = next(t for t in result.tenants if t.tenant_id == tenant.id)
    assert invited_view.role == TenantRole.MEMBER
    # resolved exactly once — a second sign-in doesn't duplicate or re-find it
    assert invites.list_for_tenant(tenant.id) == []


def test_invite_for_a_different_email_is_not_resolved(service, settings):
    tenant_store = TenantStore(settings.policy_dir)
    invites = InviteStore(settings.policy_dir)
    tenant = tenant_store.create(name="Acme Corp")
    invites.create(
        tenant_id=tenant.id,
        email="someone-else@example.com",
        role=TenantRole.MEMBER,
        invited_by="usr_admin",
    )

    result = service.sign_in_with_google("valid-token")

    assert tenant.id not in {t.tenant_id for t in result.tenants}
