from jaas_registry.index.models import ArtifactStatus
from jaas_registry.index.store import InMemoryIndex
from tests.fixtures.index_entries import make_entry


def test_put_and_get_roundtrip():
    index = InMemoryIndex()
    index.put(make_entry(version="1.0.0"))
    entry = index.get("acme.text.summarizer", "1.0.0")
    assert entry is not None
    assert entry.version == "1.0.0"


def test_put_is_idempotent_upsert():
    index = InMemoryIndex()
    index.put(make_entry(version="1.0.0", description="first"))
    index.put(make_entry(version="1.0.0", description="second"))
    entry = index.get("acme.text.summarizer", "1.0.0")
    assert entry.description == "second"
    assert index.list_versions("acme.text.summarizer") == ["1.0.0"]


def test_list_versions_sorted():
    index = InMemoryIndex()
    for v in ["2.0.0", "1.0.0", "1.5.0"]:
        index.put(make_entry(version=v))
    assert index.list_versions("acme.text.summarizer") == ["1.0.0", "1.5.0", "2.0.0"]


def test_get_resolved_picks_latest_stable():
    index = InMemoryIndex()
    index.put(make_entry(version="1.0.0"))
    index.put(make_entry(version="1.5.0"))
    entry = index.get_resolved("acme.text.summarizer", None)
    assert entry.version == "1.5.0"


def test_get_resolved_unknown_id_returns_none():
    index = InMemoryIndex()
    assert index.get_resolved("no.such.skill", None) is None


def test_all_ids_sorted():
    index = InMemoryIndex()
    index.put(make_entry(id="zzz.a.b", version="1.0.0"))
    index.put(make_entry(id="aaa.a.b", version="1.0.0"))
    assert index.all_ids() == ["aaa.a.b", "zzz.a.b"]


def test_get_resolved_skips_a_yanked_latest_version():
    index = InMemoryIndex()
    index.put(make_entry(version="1.0.0", status=ArtifactStatus.ACTIVE))
    index.put(make_entry(version="1.1.0", status=ArtifactStatus.YANKED))
    entry = index.get_resolved("acme.text.summarizer", None)
    assert entry.version == "1.0.0"


def test_get_resolved_exact_pin_still_resolves_a_yanked_version():
    index = InMemoryIndex()
    index.put(make_entry(version="1.0.0", status=ArtifactStatus.ACTIVE))
    index.put(make_entry(version="1.1.0", status=ArtifactStatus.YANKED))
    entry = index.get_resolved("acme.text.summarizer", "1.1.0")
    assert entry is not None
    assert entry.version == "1.1.0"
    assert entry.status == ArtifactStatus.YANKED


def test_get_resolved_returns_none_when_every_version_is_yanked_and_unconstrained():
    index = InMemoryIndex()
    index.put(make_entry(version="1.0.0", status=ArtifactStatus.YANKED))
    assert index.get_resolved("acme.text.summarizer", None) is None


def test_get_resolved_range_constraint_falls_through_a_yanked_version():
    index = InMemoryIndex()
    index.put(make_entry(version="1.0.0", status=ArtifactStatus.ACTIVE))
    index.put(make_entry(version="1.1.0", status=ArtifactStatus.YANKED))
    entry = index.get_resolved("acme.text.summarizer", ">=1.0.0,<2.0.0")
    assert entry.version == "1.0.0"
