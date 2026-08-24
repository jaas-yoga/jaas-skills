import time

from rune_registry.authn.models import TenantRole
from rune_registry.authn.tokens import RefreshTokenStore, mint_access_token
from rune_registry.authz.jwt_validation import decode_token

SECRET = "test-only-shared-secret-at-least-32-bytes!!"
ISSUER = "rune-registry-test"
AUDIENCE = "rune-registry"


def test_minted_access_token_is_decodable_by_the_existing_validator():
    """authn/tokens.py is the producer counterpart to
    authz/jwt_validation.decode_token — this is the contract test proving
    the two sides actually agree on shape."""
    token = mint_access_token(
        user_id="usr_1",
        email="a@example.com",
        name="Alice",
        tenant_id="tnt_1",
        tenant_role=TenantRole.ADMIN,
        scopes=("skills:read", "skills:write", "tenant:admin"),
        secret=SECRET,
        issuer=ISSUER,
        audience=AUDIENCE,
        ttl_seconds=900,
    )

    claims = decode_token(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE)

    assert claims.subject == "usr_1"
    assert claims.tenant == "tnt_1"
    assert set(claims.scopes) == {"skills:read", "skills:write", "tenant:admin"}


def test_refresh_token_round_trip(tmp_path):
    store = RefreshTokenStore(tmp_path)

    raw = store.issue(user_id="usr_1", ttl_seconds=3600)
    record = store.redeem(raw)

    assert record is not None
    assert record.user_id == "usr_1"


def test_refresh_token_is_reusable_until_expiry(tmp_path):
    store = RefreshTokenStore(tmp_path)
    raw = store.issue(user_id="usr_1", ttl_seconds=3600)

    first = store.redeem(raw)
    second = store.redeem(raw)

    assert first is not None
    assert second is not None


def test_expired_refresh_token_is_rejected(tmp_path):
    store = RefreshTokenStore(tmp_path)
    raw = store.issue(user_id="usr_1", ttl_seconds=-1)

    assert store.redeem(raw) is None


def test_revoked_refresh_token_is_rejected(tmp_path):
    store = RefreshTokenStore(tmp_path)
    raw = store.issue(user_id="usr_1", ttl_seconds=3600)

    store.revoke(raw)

    assert store.redeem(raw) is None


def test_unknown_refresh_token_is_rejected(tmp_path):
    store = RefreshTokenStore(tmp_path)
    assert store.redeem("not-a-real-token") is None


def test_refresh_token_file_never_stores_the_raw_token(tmp_path):
    store = RefreshTokenStore(tmp_path)
    raw = store.issue(user_id="usr_1", ttl_seconds=3600)

    stored_files = list((tmp_path / "refresh_tokens").glob("*.json"))
    assert len(stored_files) == 1
    assert raw not in stored_files[0].read_text()
    assert raw not in stored_files[0].name


def test_time_travel_does_not_resurrect_an_expired_token(tmp_path, monkeypatch):
    store = RefreshTokenStore(tmp_path)
    raw = store.issue(user_id="usr_1", ttl_seconds=1)

    future = time.time() + 10
    monkeypatch.setattr(time, "time", lambda: future)

    assert store.redeem(raw) is None
