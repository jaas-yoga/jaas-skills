import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.observability.tracing import build_tracer
from rune_registry.storage.local_filesystem import LocalFilesystemStore


def test_write_read_roundtrip(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    store.write_tag_if_absent("tags/a.b.c/1.0.0/manifest.json", b'{"id": "a.b.c"}')
    assert store.read("tags/a.b.c/1.0.0/manifest.json") == b'{"id": "a.b.c"}'
    assert store.exists("tags/a.b.c/1.0.0/manifest.json") is True


def test_write_tag_if_absent_rejects_duplicate(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    store.write_tag_if_absent("tags/a.b.c/1.0.0/manifest.json", b"first")
    with pytest.raises(RuneError) as exc_info:
        store.write_tag_if_absent("tags/a.b.c/1.0.0/manifest.json", b"second")
    assert exc_info.value.code == ErrorCode.DUPLICATE_PUBLISH
    # first write wins, untouched
    assert store.read("tags/a.b.c/1.0.0/manifest.json") == b"first"


def test_write_blob_if_absent_is_idempotent(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    store.write_blob_if_absent("blobs/sha256/abc", b"content")
    store.write_blob_if_absent("blobs/sha256/abc", b"content")  # no raise
    assert store.read("blobs/sha256/abc") == b"content"


def test_list_prefix_returns_sorted_relative_paths(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    store.write_tag_if_absent("tags/a.b.c/2.0.0/manifest.json", b"x")
    store.write_tag_if_absent("tags/a.b.c/1.0.0/manifest.json", b"x")
    assert store.list_prefix("tags/a.b.c") == [
        "tags/a.b.c/1.0.0/manifest.json",
        "tags/a.b.c/2.0.0/manifest.json",
    ]


def test_list_prefix_missing_returns_empty(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    assert store.list_prefix("tags/nothing.here") == []


def test_key_cannot_escape_storage_root(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    with pytest.raises(ValueError):
        store.write_blob_if_absent("../../etc/passwd", b"pwned")


def test_storage_calls_are_traced_when_tracer_configured(tmp_path):
    exporter = InMemorySpanExporter()
    store = LocalFilesystemStore(tmp_path, tracer=build_tracer(exporter=exporter))

    store.write_blob_if_absent("blobs/sha256/abc", b"content")
    store.write_tag_if_absent("tags/a.b.c/1.0.0/manifest.json", b"x")
    store.read("blobs/sha256/abc")
    store.exists("blobs/sha256/abc")
    store.list_prefix("tags")

    span_names = [s.name for s in exporter.get_finished_spans()]
    assert span_names == [
        "storage.write_blob_if_absent",
        "storage.write_tag_if_absent",
        "storage.read",
        "storage.exists",
        "storage.list_prefix",
    ]


def test_no_spans_recorded_without_a_tracer(tmp_path):
    # LocalFilesystemStore(tmp_path) with no tracer must not raise and must not trace.
    store = LocalFilesystemStore(tmp_path)
    store.write_blob_if_absent("blobs/sha256/abc", b"content")
    assert store.read("blobs/sha256/abc") == b"content"
