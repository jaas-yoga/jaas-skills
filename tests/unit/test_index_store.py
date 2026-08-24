from rune_registry.index.store import InMemoryIndex
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
