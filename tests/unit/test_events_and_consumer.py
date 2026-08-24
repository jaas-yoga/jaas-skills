from jaas_registry.index.consumer import IndexEventConsumer
from jaas_registry.index.events import InMemoryEventBus, new_index_update_event
from jaas_registry.index.ingest import serialize_published_record
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from jaas_registry.validation.models import DependenciesDocument, PermissionsDocument
from jaas_registry.validation.rules import validate_manifest
from tests.fixtures.manifests import VALID_MANIFEST

SKILL_ID = VALID_MANIFEST["id"]
SKILL_VERSION = VALID_MANIFEST["version"]
TAG_KEY = f"tags/{SKILL_ID}/{SKILL_VERSION}/manifest.json"


def _write_published_record(store, tag_key=TAG_KEY):
    manifest = validate_manifest(VALID_MANIFEST).model_copy(
        update={"digest": "sha256:" + "a" * 64, "signature": "sig"}
    )
    record = serialize_published_record(
        manifest=manifest,
        permissions=PermissionsDocument.model_validate([]),
        dependencies=DependenciesDocument.model_validate([]),
        publish_timestamp="2026-01-01T00:00:00+00:00",
    )
    store.write_tag_if_absent(tag_key, record)
    return tag_key


def test_bus_publish_and_consume_all_drains_queue():
    bus = InMemoryEventBus()
    bus.publish(new_index_update_event(skill_id=SKILL_ID, version=SKILL_VERSION, tag_key=TAG_KEY))
    assert len(bus.consume_all()) == 1
    assert bus.consume_all() == []  # drained


def test_consumer_applies_event_and_updates_index(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    tag_key = _write_published_record(store)
    bus = InMemoryEventBus()
    bus.publish(new_index_update_event(skill_id=SKILL_ID, version=SKILL_VERSION, tag_key=tag_key))

    index = InMemoryIndex()
    consumer = IndexEventConsumer(index=index, store=store, sleep_fn=lambda _: None)
    consumer.consume_from(bus)

    entry = index.get(SKILL_ID, SKILL_VERSION)
    assert entry is not None
    assert consumer.last_applied_at is not None
    assert consumer.last_apply_lag_seconds is not None
    assert consumer.last_apply_lag_seconds >= 0


def test_consumer_apply_is_idempotent_for_same_event_id(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    tag_key = _write_published_record(store)
    event = new_index_update_event(skill_id=SKILL_ID, version=SKILL_VERSION, tag_key=tag_key)

    index = InMemoryIndex()
    consumer = IndexEventConsumer(index=index, store=store, sleep_fn=lambda _: None)
    consumer.apply(event)
    consumer.apply(event)  # re-apply of the same event id must not error or duplicate

    assert index.list_versions(SKILL_ID) == [SKILL_VERSION]


def test_consumer_moves_persistently_failing_event_to_dead_letter(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    event = new_index_update_event(
        skill_id="no.such.skill", version="1.0.0", tag_key="tags/no.such.skill/1.0.0/manifest.json"
    )

    index = InMemoryIndex()
    consumer = IndexEventConsumer(index=index, store=store, max_retries=2, sleep_fn=lambda _: None)
    consumer.apply(event)

    assert index.get("no.such.skill", "1.0.0") is None
    assert len(consumer.dead_letters) == 1
    assert consumer.dead_letters[0].attempts == 2
    assert consumer.dead_letters[0].event.event_id == event.event_id
