"""IMPLEMENTATION_PLAN.md Phase 4.1: tests/test_client.py proves request/
response handling against httpx.MockTransport, in isolation from the real
backend. That's necessary but not sufficient -- this file drives
JaasRegistryClient against the *real* jaas_registry FastAPI app (in-process,
via httpx.ASGITransport, no real network) to prove the client's actual
request shapes are ones the real API accepts, matching this session's
established convention of verifying cross-package integrations against real
behavior rather than trusting mocks alone.

Only runs where the `jaas-registry` dev dependency is installed (see this
package's pyproject.toml `[tool.uv.sources]` -- a path dependency on the
sibling backend package, test-time only).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jaas_registry.api.app import create_app
from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.common.config import Settings
from jaas_registry.index.consumer import IndexEventConsumer
from jaas_registry.index.events import InMemoryEventBus
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.observability.tracing import build_tracer
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from jaas_client import JaasRegistryClient
from jaas_client.errors import JaasNotFoundError

MANIFEST = {
    "apiVersion": "v1",
    "id": "acme.text.summarizer",
    "name": "Summarizer",
    "version": "1.2.3",
    "description": "Summarizes text",
    "owner": {"team": "platform", "contact": "platform@acme.com"},
    "entrypoint": "SKILL.md",
    "category": "nlp",
    "tags": ["summarization", "nlp"],
    "runtime": [{"family": "python", "versionRange": ">=3.10.0,<4.0.0"}],
}

SKILL_MD = "# Summarizer\n\nGiven a document, produce a concise summary.\n"


def _write_package_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.yaml").write_text(yaml.safe_dump(MANIFEST))
    (root / "SKILL.md").write_text(SKILL_MD)
    return root


@pytest.fixture
def real_app(tmp_path):
    keypair = generate_dev_keypair()
    store = LocalFilesystemStore(tmp_path / "storage")
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    event_bus = InMemoryEventBus()

    _write_package_dir(tmp_path / "pkg")
    publish_skill(
        source_dir=tmp_path / "pkg",
        store=store,
        signing_key=keypair,
        trust_policy=trust_policy,
        actor="ci-pipeline",
        audit_sink=InMemoryAuditSink(),
        event_bus=event_bus,
    )

    index = InMemoryIndex()
    IndexEventConsumer(index=index, store=store, sleep_fn=lambda _: None).consume_from(event_bus)

    settings = Settings(storage_root=store.root)
    tracer = build_tracer(exporter=InMemorySpanExporter(), batch=True)
    return create_app(
        index=index, store=store, settings=settings, trust_policy=trust_policy, tracer=tracer
    )


def _client_for(app) -> JaasRegistryClient:
    """JaasRegistryClient is a *sync* httpx.Client under the hood, and
    httpx.ASGITransport only supports async requests -- FastAPI's own
    TestClient (itself an httpx.Client subclass, see starlette.testclient)
    is what provides a sync-compatible in-process ASGI transport, so this
    reuses its `_transport` rather than building an ASGITransport by hand."""
    test_client = TestClient(app)
    return JaasRegistryClient("http://testserver", transport=test_client._transport)


def test_search_finds_the_real_published_skill(real_app):
    with _client_for(real_app) as client:
        results = client.search(query="summarizer")

    assert [r.id for r in results] == ["acme.text.summarizer"]
    assert results[0].version == "1.2.3"


def test_get_metadata_returns_the_real_published_record(real_app):
    with _client_for(real_app) as client:
        metadata = client.get_metadata("acme.text.summarizer", "1.2.3")

    assert metadata.description == "Summarizes text"
    assert metadata.owner_team == "platform"
    assert metadata.status == "active"


def test_get_metadata_unknown_skill_raises_not_found_against_the_real_api(real_app):
    with _client_for(real_app) as client:
        with pytest.raises(JaasNotFoundError):
            client.get_metadata("no.such.skill")


def test_pull_downloads_the_real_packaged_files(real_app):
    with _client_for(real_app) as client:
        files = client.pull("acme.text.summarizer", "1.2.3")

    assert files["SKILL.md"].decode() == SKILL_MD
    assert "manifest.yaml" in files


def test_get_entrypoint_content_returns_the_real_skill_md(real_app):
    with _client_for(real_app) as client:
        content = client.get_entrypoint_content("acme.text.summarizer", "1.2.3")

    assert content == SKILL_MD


def test_pull_defaults_to_latest_against_the_real_api(real_app):
    with _client_for(real_app) as client:
        files = client.pull("acme.text.summarizer")

    assert files["SKILL.md"].decode() == SKILL_MD
