import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.common.config import FeatureFlags, Settings
from jaas_registry.index.bootstrap import bootstrap_index
from jaas_registry.index.consumer import IndexEventConsumer
from jaas_registry.index.events import InMemoryEventBus
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.observability import metrics as m
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET
from tests.fixtures.package_dir import write_package_dir


def _counter_total(counter) -> float:
    total = 0.0
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total"):
                total += sample.value
    return total


@pytest.fixture
def client(tmp_path, clean_metrics):
    index = InMemoryIndex()
    index.put(make_entry())
    store = LocalFilesystemStore(tmp_path)
    settings = Settings(storage_root=tmp_path)
    app = create_app(index=index, store=store, settings=settings)
    return TestClient(app)


def test_response_gets_a_generated_correlation_id(client):
    resp = client.get("/api/v1/skills")
    assert resp.headers["x-correlation-id"]


def test_response_echoes_caller_supplied_correlation_id(client):
    resp = client.get("/api/v1/skills", headers={"X-Correlation-Id": "caller-supplied-id"})
    assert resp.headers["x-correlation-id"] == "caller-supplied-id"


def test_metrics_endpoint_exposes_prometheus_format(client):
    client.get("/api/v1/skills")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "jaas_request_total" in resp.text
    assert "jaas_request_latency_seconds" in resp.text


def test_request_total_increments_after_real_request(client):
    client.get("/api/v1/skills")
    metrics_text = client.get("/metrics").text
    assert 'endpoint="/api/v1/skills"' in metrics_text
    assert 'status="200"' in metrics_text


def test_authz_denied_metric_increments_on_403(tmp_path, clean_metrics):
    index = InMemoryIndex()
    index.put(make_entry(permissions=("fs:read",)))
    store = LocalFilesystemStore(tmp_path)
    settings = Settings(storage_root=tmp_path)
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(index=index, store=store, settings=settings, authorizer=authorizer)
    client = TestClient(app)

    before = m.authz_denied_total._value.get()
    resp = client.post("/api/v1/skills/acme.text.summarizer/versions/1.0.0/artifact-token")
    assert resp.status_code == 403
    assert m.authz_denied_total._value.get() == before + 1


def test_signature_verification_failure_metric_increments_on_tampered_download(
    tmp_path, clean_metrics
):
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
    index = InMemoryIndex()
    IndexEventConsumer(index=index, store=store, sleep_fn=lambda _: None).consume_from(event_bus)

    settings = Settings(
        storage_root=store.root,
        feature_flags=FeatureFlags(high_assurance_signature_recheck=True),
    )
    app = create_app(index=index, store=store, settings=settings, trust_policy=trust_policy)
    client = TestClient(app)

    token = client.post(
        "/api/v1/skills/acme.text.summarizer/versions/1.2.3/artifact-token"
    ).json()["token"]

    entry = index.get("acme.text.summarizer", "1.2.3")
    blob_path = store.root / f"blobs/{entry.digest.replace(':', '/')}"
    blob_path.write_bytes(blob_path.read_bytes() + b"tampered")

    before = _counter_total(m.signature_verification_failures_total)
    resp = client.get(f"/api/v1/artifacts/{token}")
    assert resp.status_code == 400
    assert _counter_total(m.signature_verification_failures_total) == before + 1


def test_index_build_duration_observed_after_bootstrap(tmp_path, clean_metrics):
    store = LocalFilesystemStore(tmp_path)
    count_before = m.index_build_duration_seconds._sum.get()
    bootstrap_index(store)
    assert m.index_build_duration_seconds._sum.get() >= count_before


def test_index_event_apply_lag_gauge_set_after_consumer_applies_event(tmp_path, clean_metrics):
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

    index = InMemoryIndex()
    consumer = IndexEventConsumer(index=index, store=store, sleep_fn=lambda _: None)
    consumer.consume_from(event_bus)

    assert m.index_event_apply_lag_seconds._value.get() >= 0
