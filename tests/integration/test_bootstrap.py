import copy

import pytest

from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.artifact.yank import YankRecord, write_status
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.index.bootstrap import bootstrap_index
from jaas_registry.index.models import ArtifactStatus
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
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


def test_bootstrap_from_empty_storage_yields_empty_index(rig):
    index = bootstrap_index(rig["store"])
    assert index.all_ids() == []


def test_bootstrap_reconstructs_full_index_from_storage_alone(rig, tmp_path):
    _publish(rig, tmp_path / "pkg")

    # Simulate an instance crash: a fresh store instance over the same root,
    # bootstrapping purely from what's on disk.
    fresh_store = LocalFilesystemStore(rig["store"].root)
    index = bootstrap_index(fresh_store)

    entry = index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"])
    assert entry is not None
    assert entry.name == VALID_MANIFEST["name"]
    assert entry.permissions == ("fs:read", "network:egress")
    assert entry.dependencies == (("acme.util.tokenizer", ">=1.0.0,<2.0.0"),)


def test_bootstrap_ignores_non_manifest_keys_under_tags_prefix(rig, tmp_path):
    _publish(rig, tmp_path / "pkg")
    rig["store"].write_blob_if_absent(f"tags/{VALID_MANIFEST['id']}/README.md", b"not a manifest")

    index = bootstrap_index(rig["store"])

    assert index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"]) is not None
    assert index.all_ids() == [VALID_MANIFEST["id"]]


def test_bootstrap_reconstructs_multiple_versions(rig, tmp_path):
    v1 = copy.deepcopy(VALID_MANIFEST)
    v1["version"] = "1.0.0"
    v2 = copy.deepcopy(VALID_MANIFEST)
    v2["version"] = "1.1.0"

    _publish(rig, tmp_path / "pkg-v1", manifest=v1)
    _publish(rig, tmp_path / "pkg-v2", manifest=v2)

    index = bootstrap_index(rig["store"])
    assert index.list_versions(VALID_MANIFEST["id"]) == ["1.0.0", "1.1.0"]


def test_bootstrap_survives_a_restart_reflecting_a_yanked_version(rig, tmp_path):
    """A yank sidecar must not be forgotten across a cold-start rebuild —
    the whole point of a sidecar (vs. baking status into the immutable tag)
    is that it's the only thing bootstrap has to re-read on top of the tag."""
    _publish(rig, tmp_path / "pkg")
    write_status(
        rig["store"],
        skill_id=VALID_MANIFEST["id"],
        version=VALID_MANIFEST["version"],
        record=YankRecord(
            status=ArtifactStatus.YANKED, reason="CVE-2026-1234", actor="usr_owner", at="t1"
        ),
    )

    fresh_store = LocalFilesystemStore(rig["store"].root)
    index = bootstrap_index(fresh_store)

    entry = index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"])
    assert entry.status == ArtifactStatus.YANKED


def test_bootstrap_defaults_to_active_when_no_status_sidecar_exists(rig, tmp_path):
    _publish(rig, tmp_path / "pkg")
    index = bootstrap_index(rig["store"])
    entry = index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"])
    assert entry.status == ArtifactStatus.ACTIVE
