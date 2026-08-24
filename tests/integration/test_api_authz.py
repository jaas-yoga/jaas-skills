import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.config import Settings
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token


@pytest.fixture
def client(tmp_path):
    index = InMemoryIndex()
    index.put(
        make_entry(
            id="acme.text.summarizer",
            version="1.0.0",
            permissions=("fs:read",),
        )
    )
    store = LocalFilesystemStore(tmp_path)
    settings = Settings(storage_root=tmp_path)
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(index=index, store=store, settings=settings, authorizer=authorizer)
    return TestClient(app)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_artifact_token_without_bearer_is_403(client):
    resp = client.post("/api/v1/skills/acme.text.summarizer/versions/1.0.0/artifact-token")
    assert resp.status_code == 403
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_artifact_token_with_insufficient_scope_is_403(client):
    token = make_token(scopes=("network:egress",))
    resp = client.post(
        "/api/v1/skills/acme.text.summarizer/versions/1.0.0/artifact-token",
        headers=_auth_header(token),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_artifact_token_with_required_scope_succeeds(client):
    token = make_token(scopes=("fs:read",))
    resp = client.post(
        "/api/v1/skills/acme.text.summarizer/versions/1.0.0/artifact-token",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["token"]


def test_artifact_token_with_wildcard_scope_succeeds(client):
    token = make_token(scopes=("fs:*",))
    resp = client.post(
        "/api/v1/skills/acme.text.summarizer/versions/1.0.0/artifact-token",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200


def test_search_and_metadata_remain_open_without_auth(client):
    assert client.get("/api/v1/skills").status_code == 200
    assert (
        client.get("/api/v1/skills/acme.text.summarizer/versions/1.0.0").status_code == 200
    )
