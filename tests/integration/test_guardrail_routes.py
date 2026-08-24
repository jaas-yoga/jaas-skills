from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.common.config import Settings
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.fake_guardrails_client import FAKE_CATALOG, FakeGuardrailsClient


def test_catalog_endpoint_needs_no_auth_and_lists_all_checks(tmp_path):
    """The real 19-rule catalog lives only in the standalone jaas-guardrails
    service and is tested there; this only verifies the proxy endpoint
    forwards whatever the client returns, shape intact."""
    index = InMemoryIndex()
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(storage_root=tmp_path / "storage", policy_dir=tmp_path / "policy")
    app = create_app(
        index=index, store=store, settings=settings, guardrails_client=FakeGuardrailsClient()
    )
    client = TestClient(app)

    resp = client.get("/api/v1/guardrails")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == len(FAKE_CATALOG)
    ids = {item["id"] for item in body}
    assert "secret-scan" in ids
    baseline = next(item for item in body if item["id"] == "secret-scan")
    assert baseline["level"] == 1
    assert baseline["mandatory"] is True
    assert baseline["defaultSeverity"] == "BLOCK"
