"""Security test suite: authentication/authorization bypass attempts.

implementation-plan.md Phase 7 task 4. Each test models a specific attack an
adversary might try against the JWT/scope layer, asserting it is rejected
with JaasError(UNAUTHORIZED) — never silently accepted, never an unhandled
exception leaking internals.
"""

import base64
import json

import jwt
import pytest

from jaas_registry.authz.jwt_validation import decode_token
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.errors import ErrorCode, JaasError
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token


def _decode(token: str):
    return decode_token(
        token, secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )


def _b64url(data: dict) -> str:
    raw = json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _authorizer() -> JwtAuthorizer:
    return JwtAuthorizer(secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE)


def test_alg_none_attack_is_rejected():
    """Classic JWT bypass: craft a token with alg=none and no signature, hoping
    a lenient verifier treats the claims as trusted anyway."""
    header = _b64url({"alg": "none", "typ": "JWT"})
    payload = _b64url(
        {"iss": DEFAULT_ISSUER, "aud": DEFAULT_AUDIENCE, "sub": "attacker", "exp": 9999999999}
    )
    forged_token = f"{header}.{payload}."

    with pytest.raises(JaasError) as exc_info:
        _decode(forged_token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_token_missing_expiry_claim_is_rejected():
    """A token minted without `exp` must not be treated as eternally valid."""
    forged_token = jwt.encode(
        {"iss": DEFAULT_ISSUER, "aud": DEFAULT_AUDIENCE, "sub": "attacker"},
        DEFAULT_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(JaasError) as exc_info:
        _decode(forged_token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_payload_tampering_after_signing_is_rejected():
    """Take a validly-signed token, splice in escalated scopes, keep the
    original signature — must fail, since the signature no longer matches."""
    valid_token = make_token(scopes=("fs:read",))
    header_b64, payload_b64, signature_b64 = valid_token.split(".")

    tampered_payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    tampered_payload["scope"] = "fs:read fs:write network:egress admin:*"
    forged_token = f"{header_b64}.{_b64url(tampered_payload)}.{signature_b64}"

    with pytest.raises(JaasError) as exc_info:
        _decode(forged_token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_signed_with_wrong_secret_is_rejected():
    """A token an attacker signs themselves, with a guessed/leaked-elsewhere
    secret, must not verify against our actual secret."""
    forged_token = make_token(secret="a-completely-different-attacker-controlled-secret!!")
    with pytest.raises(JaasError) as exc_info:
        _decode(forged_token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_issuer_substitution_is_rejected():
    """A token legitimately issued by some *other* trusted-elsewhere issuer
    must not be accepted here just because it's otherwise well-formed."""
    forged_token = make_token(issuer="some-other-companys-idp")
    with pytest.raises(JaasError) as exc_info:
        _decode(forged_token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_audience_substitution_is_rejected():
    """A token minted for a different downstream service must not be replayed
    against this registry (classic token-passthrough confusion attack)."""
    forged_token = make_token(audience="some-other-service")
    with pytest.raises(JaasError) as exc_info:
        _decode(forged_token)
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_empty_bearer_token_is_rejected():
    authorizer = _authorizer()
    with pytest.raises(JaasError) as exc_info:
        authorizer.check(token="", tenant_header=None, required_permissions=("fs:read",))
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_scope_prefix_confusion_does_not_grant_unrelated_permission():
    """A scope like 'fs:readiness' must not be mistaken for covering 'fs:read'
    (naive substring/startswith matching would fall for this)."""
    authorizer = _authorizer()
    token = make_token(scopes=("fs:readiness",))
    with pytest.raises(JaasError) as exc_info:
        authorizer.check(token=token, tenant_header=None, required_permissions=("fs:read",))
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_wildcard_scope_does_not_leak_across_top_level_namespaces():
    """'fs:*' must not satisfy a requirement in a totally different namespace."""
    authorizer = _authorizer()
    token = make_token(scopes=("fs:*",))
    with pytest.raises(JaasError) as exc_info:
        authorizer.check(token=token, tenant_header=None, required_permissions=("admin:full",))
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_tenant_boundary_cannot_be_bypassed_by_omitting_tenant_header():
    """With tenant enforcement on, a caller can't dodge the check by simply not
    sending a tenant header — token tenant vs None must still be compared."""
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET,
        issuer=DEFAULT_ISSUER,
        audience=DEFAULT_AUDIENCE,
        enforce_tenant_boundary=True,
    )
    token = make_token(scopes=("fs:read",), tenant="tenant-a")
    with pytest.raises(JaasError) as exc_info:
        authorizer.check(token=token, tenant_header=None, required_permissions=("fs:read",))
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_malformed_token_does_not_crash_with_unhandled_exception():
    """Garbage input at the auth boundary must degrade to a clean 401/403-style
    rejection, never an unhandled exception that could leak a stack trace."""
    for garbage in ("", "not.a.jwt", "a" * 10_000, "🎉.🎉.🎉", "..", "null"):
        with pytest.raises(JaasError) as exc_info:
            _decode(garbage)
        assert exc_info.value.code == ErrorCode.UNAUTHORIZED
