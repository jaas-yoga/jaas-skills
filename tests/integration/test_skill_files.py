"""Read-only file viewer for a published version (companion to the /shares
and /drafts file endpoints) — GET .../files (list) and .../files/{path}
(content), scoped by the same visibility rule as get_skill_metadata."""

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.common.config import Settings
from jaas_registry.index.consumer import IndexEventConsumer
from jaas_registry.index.events import InMemoryEventBus
from jaas_registry.index.models import Visibility
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.package_dir import write_package_dir


@pytest.fixture
def system(tmp_path):
    keypair = generate_dev_keypair()
    store = LocalFilesystemStore(tmp_path / "storage")
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    event_bus = InMemoryEventBus()
    index = InMemoryIndex()
    consumer = IndexEventConsumer(index=index, store=store, sleep_fn=lambda _: None)

    write_package_dir(tmp_path / "public-pkg")
    publish_skill(
        source_dir=tmp_path / "public-pkg",
        store=store,
        signing_key=keypair,
        trust_policy=trust_policy,
        actor="ci-pipeline",
        audit_sink=InMemoryAuditSink(),
        event_bus=event_bus,
        visibility=Visibility.PUBLIC,
    )

    write_package_dir(
        tmp_path / "private-pkg",
        manifest={
            "apiVersion": "v1",
            "id": "acme.text.private-summarizer",
            "name": "Private Summarizer",
            "version": "1.0.0",
            "description": "Not for anonymous eyes",
            "owner": {"team": "platform", "contact": None},
            "entrypoint": "executor.py",
            "category": "nlp",
            "tags": [],
            "runtime": [{"family": "python", "versionRange": ">=3.10.0,<4.0.0"}],
        },
    )
    publish_skill(
        source_dir=tmp_path / "private-pkg",
        store=store,
        signing_key=keypair,
        trust_policy=trust_policy,
        actor="ci-pipeline",
        audit_sink=InMemoryAuditSink(),
        event_bus=event_bus,
        owner_user="usr_owner",
        owner_tenant="tnt_owner",
        visibility=Visibility.PRIVATE,
    )

    consumer.consume_from(event_bus)

    settings = Settings(storage_root=store.root, policy_dir=tmp_path / "policy")
    app = create_app(index=index, store=store, settings=settings, trust_policy=trust_policy)
    return TestClient(app)


def test_list_files_on_a_public_skill_is_anonymous_reachable(system):
    resp = system.get("/api/v1/skills/acme.text.summarizer/versions/1.2.3/files")
    assert resp.status_code == 200
    assert resp.json() == ["dependencies.yaml", "manifest.yaml", "permissions.yaml", "schema.json"]


def test_get_a_file_returns_its_content(system):
    resp = system.get(
        "/api/v1/skills/acme.text.summarizer/versions/1.2.3/files/manifest.yaml"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "manifest.yaml"
    assert "acme.text.summarizer" in body["content"]


def test_getting_a_file_not_in_the_package_is_404(system):
    resp = system.get(
        "/api/v1/skills/acme.text.summarizer/versions/1.2.3/files/does-not-exist.txt"
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "SKILL_FILE_NOT_FOUND"


def test_listing_files_on_an_unknown_version_is_404(system):
    resp = system.get("/api/v1/skills/acme.text.summarizer/versions/9.9.9/files")
    assert resp.status_code == 404
    assert resp.json()["code"] == "VERSION_NOT_FOUND"


def test_private_skill_files_are_not_visible_to_an_anonymous_caller(system):
    resp = system.get(
        "/api/v1/skills/acme.text.private-summarizer/versions/1.0.0/files"
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "SKILL_NOT_FOUND"

    resp = system.get(
        "/api/v1/skills/acme.text.private-summarizer/versions/1.0.0/files/manifest.yaml"
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "SKILL_NOT_FOUND"
