"""Rollback dry run. implementation-plan.md Phase 8 task 4; see ROLLOUT.md.

The property that makes a rollback safe for this service: it is stateless
compute over immutable storage, so "roll back" means nothing more than
redeploying a previous build against the *same* storage. This test proves
that property directly — data published while one app instance is "live"
remains fully and identically servable by a completely fresh instance
constructed afterward, standing in for "the previous build's replicas,"
without any data migration step.
"""

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rune_registry.api.app import create_app
from rune_registry.artifact.publish import publish_skill
from rune_registry.artifact.signing import generate_dev_keypair
from rune_registry.artifact.trust import TrustPolicy
from rune_registry.common.audit import InMemoryAuditSink
from rune_registry.common.config import Settings
from rune_registry.index.bootstrap import bootstrap_index
from rune_registry.observability.tracing import build_tracer
from rune_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.manifests import VALID_MANIFEST
from tests.fixtures.package_dir import write_package_dir


def _quiet_app(**kwargs):
    return create_app(tracer=build_tracer(exporter=InMemorySpanExporter()), **kwargs)


def test_fresh_instance_serves_identically_to_the_instance_that_published(tmp_path):
    keypair = generate_dev_keypair()
    store = LocalFilesystemStore(tmp_path / "storage")
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])

    # "Canary build": publishes a skill, then serves it.
    write_package_dir(tmp_path / "pkg")
    publish_skill(
        source_dir=tmp_path / "pkg",
        store=store,
        signing_key=keypair,
        trust_policy=trust_policy,
        actor="ci",
        audit_sink=InMemoryAuditSink(),
    )
    canary_index = bootstrap_index(store)
    canary_client = TestClient(
        _quiet_app(index=canary_index, store=store, settings=Settings(storage_root=store.root))
    )
    canary_response = canary_client.get(
        f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/{VALID_MANIFEST['version']}"
    ).json()

    # "Rollback": a brand-new store handle and a brand-new index, bootstrapped
    # fresh from the same on-disk root — standing in for the previous
    # build's replicas, which never touched the canary's in-memory state.
    rolled_back_store = LocalFilesystemStore(tmp_path / "storage")
    rolled_back_index = bootstrap_index(rolled_back_store)
    rolled_back_client = TestClient(
        _quiet_app(
            index=rolled_back_index,
            store=rolled_back_store,
            settings=Settings(storage_root=store.root),
        )
    )
    rolled_back_response = rolled_back_client.get(
        f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/{VALID_MANIFEST['version']}"
    ).json()

    assert rolled_back_response == canary_response


def test_rollback_does_not_lose_data_published_just_before_it(tmp_path):
    """A publish that lands right at the rollback boundary must still be
    visible afterward — rollback affects only which code serves requests,
    never which data is durable."""
    keypair = generate_dev_keypair()
    store = LocalFilesystemStore(tmp_path / "storage")
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])

    write_package_dir(tmp_path / "pkg")
    publish_skill(
        source_dir=tmp_path / "pkg",
        store=store,
        signing_key=keypair,
        trust_policy=trust_policy,
        actor="ci",
        audit_sink=InMemoryAuditSink(),
    )

    # Simulate the rollback itself: a new store/index pair, as the previous
    # build's replicas would construct on their own restart.
    post_rollback_index = bootstrap_index(LocalFilesystemStore(tmp_path / "storage"))

    assert post_rollback_index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"]) is not None
