from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from rune_registry.api.app import create_app
from rune_registry.api.deps import get_google_verifier
from rune_registry.authn.google import GoogleIdentity
from rune_registry.common.config import Settings
from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.index.store import InMemoryIndex
from rune_registry.storage.local_filesystem import LocalFilesystemStore


@dataclass(frozen=True)
class FakeGoogleIdentityVerifier:
    identity: GoogleIdentity

    def verify(self, google_id_token_jwt: str) -> GoogleIdentity:
        if google_id_token_jwt != "valid-token":
            raise RuneError(ErrorCode.INVALID_GOOGLE_TOKEN, "bad token")
        return self.identity


@pytest.fixture
def client(tmp_path):
    settings = Settings(storage_root=tmp_path / "storage", policy_dir=tmp_path / "policy")
    app = create_app(
        index=InMemoryIndex(), store=LocalFilesystemStore(tmp_path / "storage"), settings=settings
    )
    app.dependency_overrides[get_google_verifier] = lambda: FakeGoogleIdentityVerifier(
        GoogleIdentity(sub="google-1", email="alice@example.com", name="Alice", picture=None)
    )
    return TestClient(app)


def test_google_sign_in_returns_tokens_and_a_personal_tenant(client):
    resp = client.post("/api/v1/auth/google", json={"idToken": "valid-token"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["accessToken"]
    assert body["refreshToken"]
    assert len(body["tenants"]) == 1
    assert body["tenants"][0]["role"] == "admin"
    assert body["activeTenantId"] == body["tenants"][0]["id"]


def test_google_sign_in_with_bad_token_is_401(client):
    resp = client.post("/api/v1/auth/google", json={"idToken": "garbage"})

    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_GOOGLE_TOKEN"


def test_refresh_mints_a_new_access_token(client):
    sign_in = client.post("/api/v1/auth/google", json={"idToken": "valid-token"}).json()

    resp = client.post("/api/v1/auth/refresh", json={"refreshToken": sign_in["refreshToken"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["accessToken"] != sign_in["accessToken"]
    assert body["activeTenantId"] == sign_in["activeTenantId"]


def test_refresh_with_bad_token_is_401(client):
    resp = client.post("/api/v1/auth/refresh", json={"refreshToken": "not-a-real-token"})

    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_REFRESH_TOKEN"


def test_google_sign_in_without_a_configured_verifier_fails_closed(tmp_path):
    """No dependency_overrides here — exercises the real get_google_verifier,
    which returns None when settings.google_client_id is unset."""
    settings = Settings(storage_root=tmp_path / "storage", policy_dir=tmp_path / "policy")
    app = create_app(
        index=InMemoryIndex(), store=LocalFilesystemStore(tmp_path / "storage"), settings=settings
    )
    client = TestClient(app)

    resp = client.post("/api/v1/auth/google", json={"idToken": "valid-token"})

    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_GOOGLE_TOKEN"
