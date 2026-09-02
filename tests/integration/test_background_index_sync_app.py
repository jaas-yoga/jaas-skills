import time

from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.common.config import FeatureFlags, Settings
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.manifests import VALID_MANIFEST
from tests.fixtures.package_dir import write_package_dir


def test_background_reconciliation_surfaces_a_publish_made_by_another_replica(tmp_path):
    """Simulates two replicas sharing one storage backend: this app's own
    InMemoryIndex starts empty, and the publish happens "elsewhere" (directly
    against the shared store, bypassing this app's index entirely, the way a
    sibling replica's own publish_skill() call would). The periodic
    reconciliation task wired into create_app()'s lifespan must pick it up
    without any explicit event needing to reach this process."""
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(
        storage_root=store.root,
        index_reconciliation_interval_seconds=0.02,
        feature_flags=FeatureFlags(background_index_reconciliation=True),
    )
    app = create_app(index=InMemoryIndex(), store=store, settings=settings)

    with TestClient(app) as client:
        keypair = generate_dev_keypair()
        write_package_dir(tmp_path / "pkg")
        publish_skill(
            source_dir=tmp_path / "pkg",
            store=store,
            signing_key=keypair,
            trust_policy=TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()]),
            actor="ci-pipeline",
            audit_sink=InMemoryAuditSink(),
        )

        deadline = time.monotonic() + 5
        resp = None
        while time.monotonic() < deadline:
            resp = client.get(
                f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/{VALID_MANIFEST['version']}"
            )
            if resp.status_code == 200:
                break
            time.sleep(0.05)

        assert resp is not None and resp.status_code == 200


def test_background_reconciliation_disabled_by_flag_does_not_start_a_task(tmp_path):
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(
        storage_root=store.root,
        feature_flags=FeatureFlags(background_index_reconciliation=False),
    )
    app = create_app(index=InMemoryIndex(), store=store, settings=settings)

    with TestClient(app):
        assert app.state.background_reconciliation_task is None
