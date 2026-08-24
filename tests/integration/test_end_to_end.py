"""Full-stack walk: publish (Phase 2) -> event sync (Phase 5) -> search/metadata/
artifact-token over real HTTP (Phase 3) -> JWT scope enforcement (Phase 4).

Exercises every phase together against one running app, the way a real client
of this registry would use it.
"""

import pytest
from fastapi.testclient import TestClient

from rune_registry.api.app import create_app
from rune_registry.artifact.publish import publish_skill
from rune_registry.artifact.signing import generate_dev_keypair
from rune_registry.artifact.trust import TrustPolicy
from rune_registry.authz.policy import JwtAuthorizer
from rune_registry.common.audit import InMemoryAuditSink
from rune_registry.common.config import Settings
from rune_registry.index.consumer import IndexEventConsumer
from rune_registry.index.events import InMemoryEventBus
from rune_registry.index.store import InMemoryIndex
from rune_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token
from tests.fixtures.package_dir import write_package_dir


@pytest.fixture
def system(tmp_path):
    keypair = generate_dev_keypair()
    store = LocalFilesystemStore(tmp_path / "storage")
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    event_bus = InMemoryEventBus()
    audit_sink = InMemoryAuditSink()

    # Publish the dependency first, then the dependent skill, both through the
    # real publish pipeline (Phase 2), each emitting an index-update event.
    write_package_dir(
        tmp_path / "tokenizer",
        manifest={
            "apiVersion": "v1",
            "id": "acme.util.tokenizer",
            "name": "Tokenizer",
            "version": "1.2.0",
            "description": "Tokenizes text",
            "owner": {"team": "platform"},
            "entrypoint": "executor.py",
            "category": "nlp-utils",
            "tags": ["tokenizer"],
            "runtime": [{"family": "python", "versionRange": ">=3.10.0,<4.0.0"}],
        },
        dependencies=[],
    )
    write_package_dir(
        tmp_path / "summarizer",
        dependencies=[{"id": "acme.util.tokenizer", "versionConstraint": ">=1.0.0,<2.0.0"}],
    )

    for pkg_dir in (tmp_path / "tokenizer", tmp_path / "summarizer"):
        publish_skill(
            source_dir=pkg_dir,
            store=store,
            signing_key=keypair,
            trust_policy=trust_policy,
            actor="ci-pipeline",
            audit_sink=audit_sink,
            event_bus=event_bus,
        )

    # Phase 5: a fresh index, synced purely from the events the publishes emitted.
    index = InMemoryIndex()
    consumer = IndexEventConsumer(index=index, store=store, sleep_fn=lambda _: None)
    consumer.consume_from(event_bus)

    settings = Settings(storage_root=store.root)
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(index=index, store=store, settings=settings, authorizer=authorizer)
    return TestClient(app)


def test_both_skills_are_searchable_after_event_sync(system):
    resp = system.get("/api/v1/skills")
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == {"acme.text.summarizer", "acme.util.tokenizer"}


def test_metadata_resolves_the_real_published_dependency_version(system):
    resp = system.get("/api/v1/skills/acme.text.summarizer/versions/1.2.3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dependencies"][0] == {
        "id": "acme.util.tokenizer",
        "versionConstraint": ">=1.0.0,<2.0.0",
        "resolvedVersion": "1.2.0",
    }


def test_artifact_token_requires_scope_from_published_permissions(system):
    # no token at all
    assert (
        system.post("/api/v1/skills/acme.text.summarizer/versions/1.2.3/artifact-token").status_code
        == 403
    )

    # token with an unrelated scope
    wrong_scope = make_token(scopes=("network:egress",))
    resp = system.post(
        "/api/v1/skills/acme.text.summarizer/versions/1.2.3/artifact-token",
        headers={"Authorization": f"Bearer {wrong_scope}"},
    )
    assert resp.status_code == 403

    # token with the scope the published permissions.yaml actually declared
    right_scope = make_token(scopes=("fs:read", "network:egress"))
    resp = system.post(
        "/api/v1/skills/acme.text.summarizer/versions/1.2.3/artifact-token",
        headers={"Authorization": f"Bearer {right_scope}"},
    )
    assert resp.status_code == 200
    assert resp.json()["token"]
