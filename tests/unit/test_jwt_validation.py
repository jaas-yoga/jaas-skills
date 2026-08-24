import pytest

from rune_registry.authz.jwt_validation import decode_token
from rune_registry.common.errors import ErrorCode, RuneError
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token


def _decode(token):
    return decode_token(
        token, secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )


def test_valid_token_decodes_claims():
    token = make_token(subject="alice", scopes=("fs:read", "fs:write"), tenant="acme")
    claims = _decode(token)
    assert claims.subject == "alice"
    assert claims.scopes == ("fs:read", "fs:write")
    assert claims.tenant == "acme"


def test_token_without_tenant_claim_has_none():
    token = make_token(scopes=("fs:read",))
    claims = _decode(token)
    assert claims.tenant is None


def test_wrong_secret_rejected():
    token = make_token(secret="not-the-real-secret-but-still-long-enough")
    with pytest.raises(RuneError) as exc_info:
        _decode(token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_wrong_issuer_rejected():
    token = make_token(issuer="some-other-issuer")
    with pytest.raises(RuneError) as exc_info:
        _decode(token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_wrong_audience_rejected():
    token = make_token(audience="some-other-audience")
    with pytest.raises(RuneError) as exc_info:
        _decode(token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_expired_token_rejected():
    token = make_token(expires_in=-10)
    with pytest.raises(RuneError) as exc_info:
        _decode(token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_malformed_token_rejected():
    with pytest.raises(RuneError) as exc_info:
        _decode("not-a-jwt-at-all")
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
