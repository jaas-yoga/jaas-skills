from jaas_registry.artifact.yank import YankRecord, apply_status, read_status, write_status
from jaas_registry.index.models import ArtifactStatus
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry


def test_read_status_returns_none_when_no_sidecar_written(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    assert read_status(store, skill_id="acme.text.summarizer", version="1.0.0") is None


def test_write_then_read_status_round_trips(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    record = YankRecord(
        status=ArtifactStatus.YANKED,
        reason="CVE-2026-1234",
        actor="usr_owner",
        at="2026-09-02T00:00:00+00:00",
    )
    write_status(store, skill_id="acme.text.summarizer", version="1.0.0", record=record)

    read_back = read_status(store, skill_id="acme.text.summarizer", version="1.0.0")
    assert read_back == record


def test_write_status_overwrites_a_previous_record(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    first = YankRecord(status=ArtifactStatus.YANKED, reason="first", actor="usr_a", at="t1")
    second = YankRecord(status=ArtifactStatus.ACTIVE, reason=None, actor="usr_b", at="t2")

    write_status(store, skill_id="acme.text.summarizer", version="1.0.0", record=first)
    write_status(store, skill_id="acme.text.summarizer", version="1.0.0", record=second)

    assert read_status(store, skill_id="acme.text.summarizer", version="1.0.0") == second


def test_apply_status_returns_entry_unchanged_when_no_record():
    entry = make_entry()
    assert apply_status(entry, None) is entry


def test_apply_status_replaces_status_field_from_record():
    entry = make_entry()
    record = YankRecord(status=ArtifactStatus.YANKED, reason="broken", actor="usr_owner", at="t1")
    updated = apply_status(entry, record)
    assert updated.status == ArtifactStatus.YANKED
    # Nothing else about the entry changes.
    assert updated.id == entry.id
    assert updated.version == entry.version
