import time

import jwt as pyjwt
import pytest

from rune_registry.authn.github_oauth import (
    GITHUB_AUTHORIZE_URL,
    GitHubOAuthState,
    build_authorize_url,
    sign_state,
    verify_state,
)
from rune_registry.common.errors import RuneError

SECRET = "dev-only-shared-secret-not-for-prod!!"
ISSUER = "rune-registry-dev"


class TestSignAndVerifyState:
    def test_round_trips_tenant_and_user_id(self):
        state = sign_state(tenant_id="tnt_1", user_id="usr_1", secret=SECRET, issuer=ISSUER)

        result = verify_state(state, secret=SECRET, issuer=ISSUER)

        assert result == GitHubOAuthState(tenant_id="tnt_1", user_id="usr_1")

    def test_rejects_wrong_secret(self):
        state = sign_state(tenant_id="tnt_1", user_id="usr_1", secret=SECRET, issuer=ISSUER)

        with pytest.raises(RuneError, match="invalid OAuth state"):
            verify_state(state, secret="a-different-secret-thats-also-long-enough", issuer=ISSUER)

    def test_rejects_wrong_issuer(self):
        state = sign_state(tenant_id="tnt_1", user_id="usr_1", secret=SECRET, issuer=ISSUER)

        with pytest.raises(RuneError, match="invalid OAuth state"):
            verify_state(state, secret=SECRET, issuer="not-the-real-issuer")

    def test_rejects_expired_state(self):
        now = int(time.time())
        payload = {
            "tenant_id": "tnt_1",
            "user_id": "usr_1",
            "iss": ISSUER,
            "aud": "rune-github-oauth-state",
            "iat": now - 700,
            "exp": now - 100,
        }
        expired = pyjwt.encode(payload, SECRET, algorithm="HS256")

        with pytest.raises(RuneError, match="invalid OAuth state"):
            verify_state(expired, secret=SECRET, issuer=ISSUER)

    def test_rejects_a_session_token_reused_as_state(self):
        """Session tokens (authn/tokens.py) and OAuth state share the same
        secret/issuer but must never be interchangeable — the distinct
        `aud` claim is what stops a leaked session token from being replayed
        here."""
        now = int(time.time())
        session_shaped_payload = {
            "sub": "usr_1",
            "tenant": "tnt_1",
            "iss": ISSUER,
            "aud": "rune-registry",  # session token audience, not oauth-state
            "iat": now,
            "exp": now + 300,
        }
        forged = pyjwt.encode(session_shaped_payload, SECRET, algorithm="HS256")

        with pytest.raises(RuneError, match="invalid OAuth state"):
            verify_state(forged, secret=SECRET, issuer=ISSUER)

    def test_rejects_state_missing_tenant_id(self):
        now = int(time.time())
        payload = {
            "user_id": "usr_1",
            "iss": ISSUER,
            "aud": "rune-github-oauth-state",
            "iat": now,
            "exp": now + 300,
        }
        state = pyjwt.encode(payload, SECRET, algorithm="HS256")

        with pytest.raises(RuneError, match="missing tenant_id"):
            verify_state(state, secret=SECRET, issuer=ISSUER)


class TestBuildAuthorizeUrl:
    def test_includes_client_id_redirect_uri_and_state(self):
        url = build_authorize_url(
            client_id="client-123", redirect_uri="https://api.example.com/cb", state="opaque-state"
        )

        assert url.startswith(GITHUB_AUTHORIZE_URL)
        assert "client_id=client-123" in url
        assert "state=opaque-state" in url
        assert "redirect_uri=https%3A%2F%2Fapi.example.com%2Fcb" in url
        assert "scope=repo" in url
