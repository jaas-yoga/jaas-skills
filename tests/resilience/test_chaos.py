"""Resilience / chaos scenarios. implementation-plan.md Phase 7 task 3.

Covers design.md §8.2's three recovery behaviors: instance crash (rebuild from
storage), event delay (reconciliation catches up), and storage transient
errors (retry with backoff).
"""

import pytest

from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.index.bootstrap import bootstrap_index
from jaas_registry.index.consumer import IndexEventConsumer
from jaas_registry.index.events import InMemoryEventBus
from jaas_registry.index.reconciliation import reconcile
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.flaky_store import FlakyStore, TransientStorageError
from tests.fixtures.manifests import VALID_MANIFEST
from tests.fixtures.package_dir import write_package_dir


@pytest.fixture
def published_rig(tmp_path):
    keypair = generate_dev_keypair()
    store = LocalFilesystemStore(tmp_path / "storage")
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    event_bus = InMemoryEventBus()

    write_package_dir(tmp_path / "pkg")
    publish_skill(
        source_dir=tmp_path / "pkg",
        store=store,
        signing_key=keypair,
        trust_policy=trust_policy,
        actor="ci",
        audit_sink=InMemoryAuditSink(),
        event_bus=event_bus,
    )
    return {"store": store, "event_bus": event_bus}


# --- Storage transient failures (design.md §8.2.3) --------------------------


def test_consumer_recovers_from_transient_storage_failures_within_retry_budget(published_rig):
    """A read that fails twice then succeeds must still result in a successful
    apply — not a dead letter — because it recovered within max_retries."""
    flaky_store = FlakyStore(published_rig["store"], fail_times=2)
    index = InMemoryIndex()
    consumer = IndexEventConsumer(
        index=index, store=flaky_store, max_retries=3, sleep_fn=lambda _: None
    )

    consumer.consume_from(published_rig["event_bus"])

    assert index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"]) is not None
    assert consumer.dead_letters == []
    assert flaky_store.read_attempts == 3  # 2 failures + 1 success


def test_consumer_exhausts_retries_and_dead_letters_when_failures_persist(published_rig):
    """A read that never recovers within max_retries must land in dead_letters,
    not silently disappear or crash the consumer loop."""
    flaky_store = FlakyStore(published_rig["store"], fail_times=999)
    index = InMemoryIndex()
    consumer = IndexEventConsumer(
        index=index, store=flaky_store, max_retries=3, sleep_fn=lambda _: None
    )

    consumer.consume_from(published_rig["event_bus"])

    assert index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"]) is None
    assert len(consumer.dead_letters) == 1
    assert "simulated transient failure" in consumer.dead_letters[0].error


def test_transient_failure_during_reconciliation_bootstrap_propagates_cleanly(published_rig):
    """Reconciliation's fresh-view bootstrap has no retry logic of its own —
    confirm a storage error surfaces as a normal exception rather than
    silently producing a wrong/partial index."""
    flaky_store = FlakyStore(published_rig["store"], fail_times=999)
    index = InMemoryIndex()
    with pytest.raises(TransientStorageError):
        reconcile(index, flaky_store)


# --- Event delay (design.md §8.2.2) -----------------------------------------


def test_reconciliation_catches_up_when_events_are_delayed_indefinitely(published_rig):
    """Simulates a stuck consumer group: the publish event never gets
    consumed at all, but the periodic reconciliation scan still converges
    the index against storage."""
    index = InMemoryIndex()  # no consumer ever ran

    report = reconcile(index, published_rig["store"])

    assert index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"]) is not None
    assert report.drift_detected is True


def test_late_arriving_event_after_reconciliation_is_still_idempotent(published_rig):
    """Reconciliation repairs the entry first (event delayed); when the event
    eventually does arrive, applying it must be a harmless no-op, not a
    duplicate or inconsistent overwrite."""
    index = InMemoryIndex()
    reconcile(index, published_rig["store"])
    entry_after_reconciliation = index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"])

    consumer = IndexEventConsumer(
        index=index, store=published_rig["store"], sleep_fn=lambda _: None
    )
    consumer.consume_from(published_rig["event_bus"])  # the "late" event arrives now

    entry_after_late_event = index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"])
    assert entry_after_reconciliation == entry_after_late_event


# --- Node restart storms (design.md §8.2.1) ---------------------------------


def test_repeated_bootstrap_after_simulated_restarts_is_always_consistent(published_rig):
    """A 'restart storm': rebuild the index from scratch many times in a row
    (as if replicas kept crash-looping), asserting every rebuild converges to
    the same state — no partial reads, no accumulating drift."""
    snapshots = []
    for _ in range(20):
        index = bootstrap_index(published_rig["store"])
        snapshots.append(index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"]))

    assert all(snapshot == snapshots[0] for snapshot in snapshots)
    assert snapshots[0] is not None


def test_bootstrap_mid_publish_sequence_only_reflects_durably_written_skills(tmp_path):
    """A restart that happens between two publishes must see exactly the one
    that completed — never a half-written or missing-but-should-exist state."""
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

    # "Restart" here, before a second skill would have been published.
    index = bootstrap_index(store)
    assert index.all_ids() == [VALID_MANIFEST["id"]]
