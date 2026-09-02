"""ui-implementation-plan.md Phase 7: personal access tokens — create, list,
revoke, and (critically) that revocation actually blocks further use."""

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.api.deps import get_google_verifier
from jaas_registry.authn.google import GoogleIdentity
from jaas_registry.authz.policy import build_authorizer_from_settings
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.jwt_tokens import make_token


class FakeGoogleIdentityVerifier:
    def __init__(self, identities: dict[str, GoogleIdentity]):
        self._identities = identities

    def verify(self, google_id_token_jwt: str) -> GoogleIdentity:
        identity = self._identities.get(google_id_token_jwt)
        if identity is None:
            raise JaasError(ErrorCode.INVALID_GOOGLE_TOKEN, "unknown test token")
        return identity


@pytest.fixture
def client(tmp_path):
    index = InMemoryIndex()
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(storage_root=tmp_path / "storage", policy_dir=tmp_path / "policy")
    # build_authorizer_from_settings, not a bare JwtAuthorizer(...) — that's
    # what actually wires the PatStore, the same way production does
    # (see cli.py's cmd_serve). A JwtAuthorizer without one fails closed on
    # every PAT (correct behavior, but not what this test wants to exercise).
    authorizer = build_authorizer_from_settings(settings)
    app = create_app(index=index, store=store, settings=settings, authorizer=authorizer)
    app.dependency_overrides[get_google_verifier] = lambda: FakeGoogleIdentityVerifier(
        {
            "alice-token": GoogleIdentity(
                sub="google-alice", email="alice@example.com", name="Alice", picture=None
            ),
        }
    )
    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sign_in(client: TestClient) -> str:
    resp = client.post("/api/v1/auth/google", json={"idToken": "alice-token"})
    assert resp.status_code == 200, resp.text
    return resp.json()["accessToken"]


class TestCreatePat:
    def test_create_returns_a_usable_token(self, client):
        session_token = _sign_in(client)

        resp = client.post(
            "/api/v1/account/tokens",
            json={"name": "laptop CLI"},
            headers=_auth(session_token),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "laptop CLI"
        assert body["token"]

        # the minted PAT itself works as a bearer token
        pat_resp = client.get("/api/v1/account/tokens", headers=_auth(body["token"]))
        assert pat_resp.status_code == 200

    def test_ttl_is_capped(self, client):
        session_token = _sign_in(client)

        resp = client.post(
            "/api/v1/account/tokens",
            json={"name": "too-long", "ttlSeconds": 10**12},
            headers=_auth(session_token),
        )

        assert resp.status_code == 200  # capped, not rejected

    def test_non_positive_ttl_is_rejected(self, client):
        session_token = _sign_in(client)

        resp = client.post(
            "/api/v1/account/tokens",
            json={"name": "x", "ttlSeconds": 0},
            headers=_auth(session_token),
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "SCHEMA_VALIDATION_FAILED"

    def test_token_with_no_backing_user_record_is_rejected(self, client):
        # A hand-minted token (bypassing real sign-in) has a subject with no
        # User record at all — defensive, but a real possibility for any
        # token that isn't one AuthService itself minted.
        token = make_token(subject="usr_never_signed_in", scopes=("skills:write",))

        resp = client.post("/api/v1/account/tokens", json={"name": "x"}, headers=_auth(token))

        assert resp.status_code == 403
        assert resp.json()["code"] == "UNAUTHORIZED"

    def test_requires_auth(self, client):
        resp = client.post("/api/v1/account/tokens", json={"name": "x"})
        assert resp.status_code == 403


class TestListAndRevoke:
    def test_list_shows_created_tokens_without_the_raw_secret(self, client):
        session_token = _sign_in(client)
        client.post("/api/v1/account/tokens", json={"name": "a"}, headers=_auth(session_token))
        client.post("/api/v1/account/tokens", json={"name": "b"}, headers=_auth(session_token))

        resp = client.get("/api/v1/account/tokens", headers=_auth(session_token))

        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()}
        assert names == {"a", "b"}
        assert all("token" not in t for t in resp.json())

    def test_revoked_pat_can_no_longer_authenticate(self, client):
        session_token = _sign_in(client)
        created = client.post(
            "/api/v1/account/tokens", json={"name": "laptop"}, headers=_auth(session_token)
        ).json()

        # works before revocation
        before = client.get("/api/v1/account/tokens", headers=_auth(created["token"]))
        assert before.status_code == 200

        revoke_resp = client.delete(
            f"/api/v1/account/tokens/{created['id']}", headers=_auth(session_token)
        )
        assert revoke_resp.status_code == 204

        # the exact same PAT bearer string is now rejected
        after = client.get("/api/v1/account/tokens", headers=_auth(created["token"]))
        assert after.status_code == 403

    def test_revoking_someone_elses_token_is_rejected(self, client):
        session_token = _sign_in(client)
        created = client.post(
            "/api/v1/account/tokens", json={"name": "laptop"}, headers=_auth(session_token)
        ).json()

        other_token = make_other_user_session_token(client)
        resp = client.delete(
            f"/api/v1/account/tokens/{created['id']}", headers=_auth(other_token)
        )

        assert resp.status_code == 404


class TestUpdateProfile:
    def test_sets_display_name(self, client):
        session_token = _sign_in(client)

        resp = client.patch(
            "/api/v1/account/profile",
            json={"displayName": "Ali"},
            headers=_auth(session_token),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Ali"
        assert body["displayName"] == "Ali"

    def test_blank_display_name_resets_to_google_name(self, client):
        session_token = _sign_in(client)
        client.patch(
            "/api/v1/account/profile",
            json={"displayName": "Ali"},
            headers=_auth(session_token),
        )

        resp = client.patch(
            "/api/v1/account/profile",
            json={"displayName": "   "},
            headers=_auth(session_token),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Alice"
        assert body["displayName"] is None

    def test_persists_across_sign_ins(self, client):
        session_token = _sign_in(client)
        client.patch(
            "/api/v1/account/profile",
            json={"displayName": "Ali"},
            headers=_auth(session_token),
        )

        resp = client.post("/api/v1/auth/google", json={"idToken": "alice-token"})

        assert resp.status_code == 200
        assert resp.json()["user"]["name"] == "Ali"
        assert resp.json()["user"]["displayName"] == "Ali"

    def test_token_with_no_backing_user_record_is_rejected(self, client):
        token = make_token(subject="usr_never_signed_in", scopes=("skills:write",))

        resp = client.patch(
            "/api/v1/account/profile", json={"displayName": "x"}, headers=_auth(token)
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "UNAUTHORIZED"

    def test_requires_auth(self, client):
        resp = client.patch("/api/v1/account/profile", json={"displayName": "x"})
        assert resp.status_code == 403


def make_other_user_session_token(client: TestClient) -> str:
    # Re-uses the app's dependency override, which only knows "alice-token" —
    # add a second identity so this test has a genuinely different user.
    from jaas_registry.api.deps import get_google_verifier

    client.app.dependency_overrides[get_google_verifier] = lambda: FakeGoogleIdentityVerifier(
        {
            "alice-token": GoogleIdentity(
                sub="google-alice", email="alice@example.com", name="Alice", picture=None
            ),
            "bob-token": GoogleIdentity(
                sub="google-bob", email="bob@example.com", name="Bob", picture=None
            ),
        }
    )
    resp = client.post("/api/v1/auth/google", json={"idToken": "bob-token"})
    assert resp.status_code == 200
    return resp.json()["accessToken"]
