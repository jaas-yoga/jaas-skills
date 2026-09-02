import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.common.config import FeatureFlags, Settings
from jaas_registry.index.consumer import IndexEventConsumer
from jaas_registry.index.events import InMemoryEventBus
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.package_dir import write_package_dir


@pytest.fixture
def system(tmp_path):
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
        actor="ci-pipeline",
        audit_sink=InMemoryAuditSink(),
        event_bus=event_bus,
    )

    index = InMemoryIndex()
    IndexEventConsumer(index=index, store=store, sleep_fn=lambda _: None).consume_from(event_bus)

    def make_client(*, high_assurance: bool, wrong_trust_policy: bool = False):
        settings = Settings(
            storage_root=store.root,
            feature_flags=FeatureFlags(high_assurance_signature_recheck=high_assurance),
        )
        active_trust_policy = (
            TrustPolicy(trusted_public_keys_pem=[generate_dev_keypair().public_key_pem()])
            if wrong_trust_policy
            else trust_policy
        )
        app = create_app(
            index=index, store=store, settings=settings, trust_policy=active_trust_policy
        )
        return TestClient(app)

    return {"store": store, "index": index, "make_client": make_client}


def _issue_token(client) -> str:
    resp = client.post("/api/v1/skills/acme.text.summarizer/versions/1.2.3/artifact-token")
    assert resp.status_code == 200
    return resp.json()["token"]


def test_download_returns_the_published_archive_bytes(system):
    client = system["make_client"](high_assurance=False)
    token = _issue_token(client)

    resp = client.get(f"/api/v1/artifacts/{token}")
    assert resp.status_code == 200
    entry = system["index"].get("acme.text.summarizer", "1.2.3")
    assert resp.content == system["store"].read(f"blobs/{entry.digest.replace(':', '/')}")


def test_download_is_reusable_within_ttl(system):
    client = system["make_client"](high_assurance=False)
    token = _issue_token(client)

    assert client.get(f"/api/v1/artifacts/{token}").status_code == 200
    assert client.get(f"/api/v1/artifacts/{token}").status_code == 200


def test_download_unknown_token_is_401_style_unauthorized(system):
    client = system["make_client"](high_assurance=False)
    resp = client.get("/api/v1/artifacts/not-a-real-token")
    assert resp.status_code == 403
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_high_assurance_recheck_passes_for_untampered_artifact(system):
    client = system["make_client"](high_assurance=True)
    token = _issue_token(client)
    resp = client.get(f"/api/v1/artifacts/{token}")
    assert resp.status_code == 200


def test_high_assurance_recheck_rejects_tampered_blob(system):
    client = system["make_client"](high_assurance=True)
    token = _issue_token(client)

    entry = system["index"].get("acme.text.summarizer", "1.2.3")
    blob_path = system["store"].root / f"blobs/{entry.digest.replace(':', '/')}"
    original = blob_path.read_bytes()
    blob_path.write_bytes(original + b"tampered")

    resp = client.get(f"/api/v1/artifacts/{token}")
    assert resp.status_code == 400
    assert resp.json()["code"] == "CORRUPT_PAYLOAD"


def test_high_assurance_recheck_rejects_wrong_trust_policy(system):
    client = system["make_client"](high_assurance=True, wrong_trust_policy=True)
    token = _issue_token(client)

    resp = client.get(f"/api/v1/artifacts/{token}")
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_SIGNATURE"


def test_high_assurance_recheck_dispatches_to_sigstore_for_a_sigstore_signed_artifact(
    tmp_path, monkeypatch
):
    """IMPLEMENTATION_PLAN.md Phase 1.2 gap fix: a Sigstore-signed artifact's
    token must recheck against a SigstoreTrustPolicy, not silently try
    (and fail) an RSA check — this was a real bug found while implementing
    this feature (ArtifactToken didn't carry signature_kind at all).
    Monkeypatches api.routes.load_sigstore_trust_policy so this test
    doesn't need real network access to Sigstore's trust root."""
    from dataclasses import dataclass

    from jaas_registry.artifact.publish import publish_skill
    from jaas_registry.common.audit import InMemoryAuditSink

    @dataclass
    class _FakeSigstoreTrustPolicy:
        result: bool

        def verify(self, digest: str, signature: str) -> bool:
            return self.result

    store = LocalFilesystemStore(tmp_path / "storage")
    write_package_dir(tmp_path / "pkg")
    publish_skill(
        source_dir=tmp_path / "pkg",
        store=store,
        external_signature="a-sigstore-bundle-as-json",
        sigstore_trust_policy=_FakeSigstoreTrustPolicy(result=True),
        actor="ci-pipeline",
        audit_sink=InMemoryAuditSink(),
    )
    from jaas_registry.index.bootstrap import bootstrap_index

    index = bootstrap_index(store)

    monkeypatch.setattr(
        "jaas_registry.api.routes.load_sigstore_trust_policy",
        lambda *, identity_issuer: _FakeSigstoreTrustPolicy(result=True),
    )

    settings = Settings(
        storage_root=store.root, feature_flags=FeatureFlags(high_assurance_signature_recheck=True)
    )
    app = create_app(index=index, store=store, settings=settings)
    client = TestClient(app)
    token = _issue_token(client)

    resp = client.get(f"/api/v1/artifacts/{token}")

    assert resp.status_code == 200


def test_high_assurance_disabled_by_default_skips_recheck_even_if_tampered(system):
    client = system["make_client"](high_assurance=False)
    token = _issue_token(client)

    entry = system["index"].get("acme.text.summarizer", "1.2.3")
    blob_path = system["store"].root / f"blobs/{entry.digest.replace(':', '/')}"
    blob_path.write_bytes(blob_path.read_bytes() + b"tampered")

    resp = client.get(f"/api/v1/artifacts/{token}")
    assert resp.status_code == 200  # recheck is off, so tampering isn't caught here
