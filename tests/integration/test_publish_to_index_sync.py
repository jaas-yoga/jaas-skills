import pytest

from rune_registry.artifact.publish import publish_skill
from rune_registry.artifact.signing import generate_dev_keypair
from rune_registry.artifact.trust import TrustPolicy
from rune_registry.common.audit import InMemoryAuditSink
from rune_registry.index.consumer import IndexEventConsumer
from rune_registry.index.events import InMemoryEventBus
from rune_registry.index.store import InMemoryIndex
from rune_registry.storage.local_filesystem import LocalFilesystemStore
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
        "event_bus": InMemoryEventBus(),
        "source_dir": tmp_path / "package",
    }


def test_publish_emits_event_that_consumer_applies_to_index(rig):
    write_package_dir(rig["source_dir"])
    publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
        event_bus=rig["event_bus"],
    )

    index = InMemoryIndex()
    assert index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"]) is None  # not yet synced

    consumer = IndexEventConsumer(index=index, store=rig["store"], sleep_fn=lambda _: None)
    consumer.consume_from(rig["event_bus"])

    entry = index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"])
    assert entry is not None
    assert entry.name == VALID_MANIFEST["name"]
