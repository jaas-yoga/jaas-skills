from jaas_registry.artifact.governance import (
    GovernanceRecord,
    apply_governance,
    read_governance,
    write_governance,
)
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry


def test_read_governance_returns_none_when_no_sidecar_written(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    assert read_governance(store, skill_id="acme.text.summarizer") is None


def test_write_then_read_governance_round_trips(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    record = GovernanceRecord(
        business_purpose="Summarize customer support tickets",
        systems_accessed=("zendesk", "s3"),
        review_date="2026-12-01",
        updated_by="usr_owner",
        updated_at="2026-09-02T00:00:00+00:00",
    )
    write_governance(store, skill_id="acme.text.summarizer", record=record)

    read_back = read_governance(store, skill_id="acme.text.summarizer")
    assert read_back == record


def test_write_governance_overwrites_a_previous_record(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    first = GovernanceRecord(
        business_purpose="first", systems_accessed=(), review_date=None,
        updated_by="usr_a", updated_at="t1",
    )
    second = GovernanceRecord(
        business_purpose="second", systems_accessed=("crm",), review_date="2026-12-01",
        updated_by="usr_b", updated_at="t2",
    )

    write_governance(store, skill_id="acme.text.summarizer", record=first)
    write_governance(store, skill_id="acme.text.summarizer", record=second)

    assert read_governance(store, skill_id="acme.text.summarizer") == second


def test_governance_is_keyed_by_skill_id_only_shared_across_versions(tmp_path):
    """Unlike yank status, a governance record isn't per-version -- a
    skill's business purpose doesn't change between 1.2.0 and 1.3.0."""
    store = LocalFilesystemStore(tmp_path)
    record = GovernanceRecord(
        business_purpose="shared across versions", systems_accessed=(), review_date=None,
        updated_by="usr_owner", updated_at="t1",
    )
    write_governance(store, skill_id="acme.text.summarizer", record=record)

    assert read_governance(store, skill_id="acme.text.summarizer") == record


def test_apply_governance_returns_entry_unchanged_when_no_record():
    entry = make_entry()
    assert apply_governance(entry, None) is entry


def test_apply_governance_sets_the_three_new_fields_from_record():
    entry = make_entry()
    record = GovernanceRecord(
        business_purpose="Summarize tickets",
        systems_accessed=("zendesk",),
        review_date="2026-12-01",
        updated_by="usr_owner",
        updated_at="t1",
    )
    updated = apply_governance(entry, record)

    assert updated.business_purpose == "Summarize tickets"
    assert updated.systems_accessed == ("zendesk",)
    assert updated.governance_review_date == "2026-12-01"
    # Nothing else about the entry changes.
    assert updated.id == entry.id
    assert updated.version == entry.version
