import boto3
import pytest
from moto import mock_aws
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.observability.tracing import build_tracer
from jaas_registry.storage.s3_store import S3ObjectStore

BUCKET = "jaas-registry-test"


@pytest.fixture
def s3_client():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def make_store(s3_client, **kwargs) -> S3ObjectStore:
    return S3ObjectStore(bucket=BUCKET, client=s3_client, **kwargs)


def test_write_read_roundtrip(s3_client):
    store = make_store(s3_client)
    store.write_tag_if_absent("tags/a.b.c/1.0.0/manifest.json", b'{"id": "a.b.c"}')
    assert store.read("tags/a.b.c/1.0.0/manifest.json") == b'{"id": "a.b.c"}'
    assert store.exists("tags/a.b.c/1.0.0/manifest.json") is True


def test_write_tag_if_absent_rejects_duplicate(s3_client):
    store = make_store(s3_client)
    store.write_tag_if_absent("tags/a.b.c/1.0.0/manifest.json", b"first")
    with pytest.raises(JaasError) as exc_info:
        store.write_tag_if_absent("tags/a.b.c/1.0.0/manifest.json", b"second")
    assert exc_info.value.code == ErrorCode.DUPLICATE_PUBLISH
    # first write wins, untouched
    assert store.read("tags/a.b.c/1.0.0/manifest.json") == b"first"


def test_write_blob_if_absent_is_idempotent(s3_client):
    store = make_store(s3_client)
    store.write_blob_if_absent("blobs/sha256/abc", b"content")
    store.write_blob_if_absent("blobs/sha256/abc", b"content")  # no raise
    assert store.read("blobs/sha256/abc") == b"content"


def test_write_object_creates_a_new_key(s3_client):
    store = make_store(s3_client)
    store.write_object("tags/a.b.c/1.0.0/status.json", b'{"status": "active"}')
    assert store.read("tags/a.b.c/1.0.0/status.json") == b'{"status": "active"}'


def test_write_object_overwrites_an_existing_key(s3_client):
    store = make_store(s3_client)
    store.write_object("tags/a.b.c/1.0.0/status.json", b'{"status": "active"}')
    store.write_object("tags/a.b.c/1.0.0/status.json", b'{"status": "yanked"}')
    assert store.read("tags/a.b.c/1.0.0/status.json") == b'{"status": "yanked"}'


def test_list_prefix_returns_sorted_relative_paths(s3_client):
    store = make_store(s3_client)
    store.write_tag_if_absent("tags/a.b.c/2.0.0/manifest.json", b"x")
    store.write_tag_if_absent("tags/a.b.c/1.0.0/manifest.json", b"x")
    assert store.list_prefix("tags/a.b.c") == [
        "tags/a.b.c/1.0.0/manifest.json",
        "tags/a.b.c/2.0.0/manifest.json",
    ]


def test_list_prefix_missing_returns_empty(s3_client):
    store = make_store(s3_client)
    assert store.list_prefix("tags/nothing.here") == []


def test_exists_false_for_missing_key(s3_client):
    store = make_store(s3_client)
    assert store.exists("blobs/sha256/missing") is False


def test_prefix_option_namespaces_keys_and_is_stripped_on_list(s3_client):
    store = make_store(s3_client, prefix="envs/staging")
    store.write_blob_if_absent("blobs/sha256/abc", b"content")

    # stored under the namespaced key on the raw client
    raw = s3_client.get_object(Bucket=BUCKET, Key="envs/staging/blobs/sha256/abc")
    assert raw["Body"].read() == b"content"

    # but this store's own view strips the prefix back off
    assert store.read("blobs/sha256/abc") == b"content"
    assert store.list_prefix("blobs") == ["blobs/sha256/abc"]


def test_storage_calls_are_traced_when_tracer_configured(s3_client):
    exporter = InMemorySpanExporter()
    store = make_store(s3_client, tracer=build_tracer(exporter=exporter))

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


def test_no_spans_recorded_without_a_tracer(s3_client):
    store = make_store(s3_client)
    store.write_blob_if_absent("blobs/sha256/abc", b"content")
    assert store.read("blobs/sha256/abc") == b"content"
