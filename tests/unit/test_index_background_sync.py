import asyncio

import pytest

from jaas_registry.index.background_sync import reconcile_periodically
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore


@pytest.mark.asyncio
async def test_reconcile_periodically_runs_reconcile_repeatedly_until_stopped(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    index = InMemoryIndex()
    stop_event = asyncio.Event()
    call_count = 0

    def on_report(_report):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            stop_event.set()

    await asyncio.wait_for(
        reconcile_periodically(
            index, store, interval_seconds=0.01, stop_event=stop_event, on_report=on_report
        ),
        timeout=5,
    )

    assert call_count >= 3


@pytest.mark.asyncio
async def test_reconcile_periodically_returns_immediately_when_already_stopped(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    index = InMemoryIndex()
    stop_event = asyncio.Event()
    stop_event.set()
    call_count = 0

    def on_report(_report):
        nonlocal call_count
        call_count += 1

    await asyncio.wait_for(
        reconcile_periodically(
            index, store, interval_seconds=0.01, stop_event=stop_event, on_report=on_report
        ),
        timeout=5,
    )

    assert call_count == 0


@pytest.mark.asyncio
async def test_reconcile_periodically_picks_up_a_publish_written_by_another_replica(tmp_path):
    """The actual point of this feature: two InMemoryIndex instances sharing
    one on-disk store, modeling two separate app replicas. A publish made
    through one "replica" must become visible in the other's index once the
    periodic loop ticks — this is the mechanism that replaces the roadmap's
    original ("wire the in-memory event bus into create_app") design, which
    cannot work across OS processes at all (see IMPLEMENTATION_PLAN.md Phase
    2.4)."""
    from jaas_registry.artifact.publish import publish_skill
    from jaas_registry.artifact.signing import generate_dev_keypair
    from jaas_registry.artifact.trust import TrustPolicy
    from jaas_registry.common.audit import InMemoryAuditSink
    from tests.fixtures.manifests import VALID_MANIFEST
    from tests.fixtures.package_dir import write_package_dir

    store = LocalFilesystemStore(tmp_path / "storage")
    replica_b_index = InMemoryIndex()  # empty — as if replica A published, not B
    stop_event = asyncio.Event()

    def on_report(_report):
        stop_event.set()

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

    await asyncio.wait_for(
        reconcile_periodically(
            replica_b_index,
            store,
            interval_seconds=0.01,
            stop_event=stop_event,
            on_report=on_report,
        ),
        timeout=5,
    )

    entry = replica_b_index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"])
    assert entry is not None
