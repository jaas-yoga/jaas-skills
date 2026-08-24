import pytest

from rune_registry.authn.pat import PatStore
from rune_registry.authz.policy import JwtAuthorizer, build_authorizer_from_settings
from rune_registry.common.config import Settings
from rune_registry.common.errors import ErrorCode, RuneError
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token


def make_authorizer(**overrides) -> JwtAuthorizer:
    defaults = dict(secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE)
    defaults.update(overrides)
    return JwtAuthorizer(**defaults)


def test_missing_token_denied_by_default():
    authorizer = make_authorizer()
    with pytest.raises(RuneError) as exc_info:
        authorizer.check(token=None, tenant_header=None, required_permissions=("fs:read",))
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_invalid_token_denied():
    authorizer = make_authorizer()
    with pytest.raises(RuneError) as exc_info:
        authorizer.check(token="garbage", tenant_header=None, required_permissions=())
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_exact_scope_permitted():
    authorizer = make_authorizer()
    token = make_token(scopes=("fs:read",))
    authorizer.check(token=token, tenant_header=None, required_permissions=("fs:read",))  # no raise


def test_missing_required_scope_denied():
    authorizer = make_authorizer()
    token = make_token(scopes=("fs:read",))
    with pytest.raises(RuneError) as exc_info:
        authorizer.check(token=token, tenant_header=None, required_permissions=("network:egress",))
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_wildcard_scope_permitted():
    authorizer = make_authorizer()
    token = make_token(scopes=("fs:*",))
    authorizer.check(token=token, tenant_header=None, required_permissions=("fs:read", "fs:write"))


def test_no_required_permissions_permitted_with_any_valid_token():
    authorizer = make_authorizer()
    token = make_token(scopes=())
    authorizer.check(token=token, tenant_header=None, required_permissions=())


def test_partial_scope_match_denied():
    authorizer = make_authorizer()
    token = make_token(scopes=("fs:read",))
    with pytest.raises(RuneError) as exc_info:
        authorizer.check(
            token=token, tenant_header=None, required_permissions=("fs:read", "fs:write")
        )
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_tenant_boundary_disabled_ignores_mismatch():
    authorizer = make_authorizer(enforce_tenant_boundary=False)
    token = make_token(scopes=("fs:read",), tenant="acme")
    authorizer.check(token=token, tenant_header="other-tenant", required_permissions=("fs:read",))


def test_tenant_boundary_enabled_matching_tenant_permitted():
    authorizer = make_authorizer(enforce_tenant_boundary=True)
    token = make_token(scopes=("fs:read",), tenant="acme")
    authorizer.check(token=token, tenant_header="acme", required_permissions=("fs:read",))


def test_tenant_boundary_enabled_mismatched_tenant_denied():
    authorizer = make_authorizer(enforce_tenant_boundary=True)
    token = make_token(scopes=("fs:read",), tenant="acme")
    with pytest.raises(RuneError) as exc_info:
        authorizer.check(
            token=token, tenant_header="other-tenant", required_permissions=("fs:read",)
        )
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_tenant_boundary_enabled_no_tenant_claim_denied():
    authorizer = make_authorizer(enforce_tenant_boundary=True)
    token = make_token(scopes=("fs:read",))  # no tenant claim
    with pytest.raises(RuneError) as exc_info:
        authorizer.check(token=token, tenant_header="acme", required_permissions=("fs:read",))
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_build_authorizer_from_settings_uses_config():
    settings = Settings(jwt_secret="s", jwt_issuer="i", jwt_audience="a")
    authorizer = build_authorizer_from_settings(settings)
    assert authorizer.secret == "s"
    assert authorizer.issuer == "i"
    assert authorizer.audience == "a"
    assert authorizer.enforce_tenant_boundary is False


class TestPersonalAccessTokenRevocation:
    """ui-design.md §4.4 — a PAT is JWT-shaped like any session token, but
    carries a pat_id claim so it can actually be revoked before expiry."""

    def test_active_pat_is_accepted(self, tmp_path):
        pat_store = PatStore(tmp_path)
        pat = pat_store.create(owner_user="usr_1", name="laptop", ttl_seconds=3600)
        authorizer = make_authorizer(pat_store=pat_store)
        token = make_token(scopes=("fs:read",), pat_id=pat.id)

        authorizer.check(token=token, tenant_header=None, required_permissions=("fs:read",))

    def test_revoked_pat_is_rejected(self, tmp_path):
        pat_store = PatStore(tmp_path)
        pat = pat_store.create(owner_user="usr_1", name="laptop", ttl_seconds=3600)
        pat_store.revoke(pat_id=pat.id, owner_user="usr_1")
        authorizer = make_authorizer(pat_store=pat_store)
        token = make_token(scopes=("fs:read",), pat_id=pat.id)

        with pytest.raises(RuneError) as exc_info:
            authorizer.check(token=token, tenant_header=None, required_permissions=("fs:read",))
        assert exc_info.value.code == ErrorCode.UNAUTHORIZED

    def test_pat_id_referencing_nothing_is_rejected(self, tmp_path):
        authorizer = make_authorizer(pat_store=PatStore(tmp_path))
        token = make_token(scopes=("fs:read",), pat_id="pat_never_existed")

        with pytest.raises(RuneError):
            authorizer.check(token=token, tenant_header=None, required_permissions=("fs:read",))

    def test_regular_session_token_is_unaffected_by_an_unconfigured_pat_store(self):
        """A normal session token has no pat_id claim at all, so it's never
        subject to this check regardless of whether pat_store is wired."""
        authorizer = make_authorizer()  # no pat_store
        token = make_token(scopes=("fs:read",))
        authorizer.check(token=token, tenant_header=None, required_permissions=("fs:read",))

    def test_build_authorizer_from_settings_wires_a_pat_store(self, tmp_path):
        settings = Settings(jwt_secret="s", jwt_issuer="i", jwt_audience="a", policy_dir=tmp_path)
        authorizer = build_authorizer_from_settings(settings)
        assert authorizer.pat_store is not None
