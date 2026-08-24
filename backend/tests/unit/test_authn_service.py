from dataclasses import dataclass

import pytest

from rune_registry.authn.google import GoogleIdentity
from rune_registry.authn.invites import InviteStore
from rune_registry.authn.models import TenantRole
from rune_registry.authn.service import AuthService
from rune_registry.authn.tenants import MembershipStore, TenantStore
from rune_registry.authn.tokens import RefreshTokenStore
from rune_registry.authn.users import UserStore
from rune_registry.authz.jwt_validation import decode_token
from rune_registry.common.config import Settings
from rune_registry.common.errors import ErrorCode, RuneError

SECRET = "test-only-shared-secret-at-least-32-bytes!!"


@dataclass(frozen=True)
class FakeGoogleIdentityVerifier:
    identity: GoogleIdentity

    def verify(self, google_id_token_jwt: str) -> GoogleIdentity:
        if google_id_token_jwt != "valid-token":
            raise RuneError(ErrorCode.INVALID_GOOGLE_TOKEN, "bad token")
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


def test_first_sign_in_creates_user_and_personal_tenant_as_admin(service, settings):
    result = service.sign_in_with_google("valid-token")

    assert result.user.email == "alice@example.com"
    assert len(result.tenants) == 1
    assert result.tenants[0].role == TenantRole.ADMIN
    assert result.active_tenant_id == result.tenants[0].tenant_id

    claims = _decode(result.access_token, settings)
    assert claims.subject == result.user.id
    assert "tenant:admin" in claims.scopes


def test_second_sign_in_reuses_the_same_user_and_tenant(service):
    first = service.sign_in_with_google("valid-token")
    second = service.sign_in_with_google("valid-token")

    assert first.user.id == second.user.id
    assert first.active_tenant_id == second.active_tenant_id


def test_invalid_google_token_is_rejected(service):
    with pytest.raises(RuneError) as excinfo:
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

    with pytest.raises(RuneError) as excinfo:
        service.sign_in_with_google("valid-token")
    assert excinfo.value.code == ErrorCode.INVALID_GOOGLE_TOKEN


def test_sign_in_requesting_a_foreign_tenant_is_rejected(service):
    with pytest.raises(RuneError) as excinfo:
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
    with pytest.raises(RuneError) as excinfo:
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
