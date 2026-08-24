import pytest

from rune_registry.artifact.publish import publish_skill
from rune_registry.artifact.signing import generate_dev_keypair
from rune_registry.artifact.trust import TrustPolicy
from rune_registry.common.audit import InMemoryAuditSink
from rune_registry.index.reconciliation import compute_checksum, reconcile
from rune_registry.index.store import InMemoryIndex
from rune_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry
from tests.fixtures.manifests import VALID_MANIFEST
from tests.fixtures.package_dir import write_package_dir


@pytest.fixture
def rig(tmp_path):
    keypair = generate_dev_keypair()
    return {
        "store": LocalFilesystemStore(tmp_path / "storage"),
        "signing_key": keypair,
        "trust_policy": TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()]),
        "audit_sink": InMemoryAuditSink(),
    }


def _publish(rig, source_dir, manifest=None):
    write_package_dir(source_dir, manifest=manifest)
    return publish_skill(
        source_dir=source_dir,
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )


def test_reconcile_on_already_consistent_index_reports_no_drift(rig, tmp_path):
    _publish(rig, tmp_path / "pkg")
    index = InMemoryIndex()
    index.put(
        make_entry(
            id=VALID_MANIFEST["id"],
            version=VALID_MANIFEST["version"],
            name=VALID_MANIFEST["name"],
        )
    )
    # First reconcile syncs it up (index was seeded independently above, so it
    # won't match storage's actual digest); the *second* reconcile should be a no-op.
    reconcile(index, rig["store"])
    report = reconcile(index, rig["store"])
    assert report.drift_detected is False
    assert report.repaired == ()


def test_reconcile_repairs_missing_entry_synthetic_drift(rig, tmp_path):
    """Synthetic drift: an event never arrived, so a published skill is simply
    absent from the index. Reconciliation must add it."""
    _publish(rig, tmp_path / "pkg")
    index = InMemoryIndex()  # empty — as if the publish event was dropped

    report = reconcile(index, rig["store"])

    assert index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"]) is not None
    assert f"{VALID_MANIFEST['id']}@{VALID_MANIFEST['version']}" in report.repaired
    assert report.drift_detected is True


def test_reconcile_repairs_stale_entry_synthetic_drift(rig, tmp_path):
    """Synthetic drift: the index holds an out-of-date entry (e.g. an event
    applied against stale data). Reconciliation must overwrite it to match
    the authoritative storage record."""
    _publish(rig, tmp_path / "pkg")
    index = InMemoryIndex()
    index.put(
        make_entry(
            id=VALID_MANIFEST["id"],
            version=VALID_MANIFEST["version"],
            digest="sha256:" + "0" * 64,  # deliberately wrong/stale digest
        )
    )

    report = reconcile(index, rig["store"])

    entry = index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"])
    assert entry.digest != "sha256:" + "0" * 64
    assert report.drift_detected is True


def test_checksum_changes_when_index_contents_change():
    index = InMemoryIndex()
    empty_checksum = compute_checksum(index)
    index.put(make_entry())
    assert compute_checksum(index) != empty_checksum


def test_checksum_is_order_independent():
    index_a = InMemoryIndex()
    index_a.put(make_entry(id="acme.a.one", version="1.0.0"))
    index_a.put(make_entry(id="acme.b.two", version="1.0.0"))

    index_b = InMemoryIndex()
    index_b.put(make_entry(id="acme.b.two", version="1.0.0"))
    index_b.put(make_entry(id="acme.a.one", version="1.0.0"))

    assert compute_checksum(index_a) == compute_checksum(index_b)
