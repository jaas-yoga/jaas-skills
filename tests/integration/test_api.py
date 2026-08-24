import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.common.config import Settings
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry


@pytest.fixture
def client(tmp_path):
    index = InMemoryIndex()
    index.put(
        make_entry(
            id="acme.text.summarizer",
            name="Summarizer",
            category="nlp",
            tags=("summarization", "nlp"),
            version="1.0.0",
            dependencies=(("acme.util.tokenizer", ">=1.0.0,<2.0.0"),),
        )
    )
    index.put(
        make_entry(
            id="acme.util.tokenizer",
            name="Tokenizer",
            category="nlp-utils",
            tags=("tokenizer",),
            version="1.2.0",
            dependencies=(),
        )
    )
    store = LocalFilesystemStore(tmp_path)
    settings = Settings(storage_root=tmp_path)
    app = create_app(index=index, store=store, settings=settings)
    return TestClient(app)


def test_search_returns_matching_items(client):
    resp = client.get("/api/v1/skills", params={"query": "summarizer"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["id"] == "acme.text.summarizer"
    assert body["page"]["total"] == 1


def test_search_with_no_query_returns_all(client):
    resp = client.get("/api/v1/skills")
    assert resp.status_code == 200
    assert resp.json()["page"]["total"] == 2


def test_search_category_filter(client):
    resp = client.get("/api/v1/skills", params={"category": "nlp-utils"})
    body = resp.json()
    assert [i["id"] for i in body["items"]] == ["acme.util.tokenizer"]


def test_search_tags_filter(client):
    resp = client.get("/api/v1/skills", params={"tags": "tokenizer"})
    body = resp.json()
    assert [i["id"] for i in body["items"]] == ["acme.util.tokenizer"]


def test_search_pagination(client):
    resp = client.get("/api/v1/skills", params={"page": 1, "pageSize": 1})
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["page"]["nextPageToken"] == "2"


def test_get_metadata_resolves_dependencies(client):
    resp = client.get("/api/v1/skills/acme.text.summarizer/versions/1.0.0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "acme.text.summarizer"
    assert body["dependencies"][0]["id"] == "acme.util.tokenizer"
    assert body["dependencies"][0]["resolvedVersion"] == "1.2.0"


def test_get_metadata_supports_stable_alias(client):
    resp = client.get("/api/v1/skills/acme.text.summarizer/versions/stable")
    assert resp.status_code == 200
    assert resp.json()["version"] == "1.0.0"


def test_get_metadata_unknown_skill_returns_404_with_code(client):
    resp = client.get("/api/v1/skills/no.such.skill/versions/1.0.0")
    assert resp.status_code == 404
    assert resp.json()["code"] == "SKILL_NOT_FOUND"


def test_get_metadata_unknown_version_returns_404_with_code(client):
    resp = client.get("/api/v1/skills/acme.text.summarizer/versions/9.9.9")
    assert resp.status_code == 404
    assert resp.json()["code"] == "VERSION_NOT_FOUND"


def test_artifact_token_issued_for_known_skill(client):
    resp = client.post("/api/v1/skills/acme.text.summarizer/versions/1.0.0/artifact-token")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["ttlSeconds"] == 120


def test_artifact_token_unknown_skill_returns_404(client):
    resp = client.post("/api/v1/skills/no.such.skill/versions/1.0.0/artifact-token")
    assert resp.status_code == 404
    assert resp.json()["code"] == "SKILL_NOT_FOUND"
