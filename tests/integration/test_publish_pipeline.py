import copy

import pytest

from jaas_registry.artifact.packaging import extract_archive
from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.artifact.verify import verify_artifact
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.guardrails.models import GuardrailFinding, GuardrailScanResult, GuardrailSeverity
from jaas_registry.guardrails.policy import GuardrailPolicy
from jaas_registry.storage.keys import tag_key as make_tag_key
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.fake_guardrails_client import FakeGuardrailsClient
from tests.fixtures.manifests import VALID_MANIFEST
from tests.fixtures.package_dir import write_package_dir


@pytest.fixture
def rig(tmp_path):
    keypair = generate_dev_keypair()
    return {
        "store": LocalFilesystemStore(tmp_path / "storage"),
        "signing_key": keypair,
        "trust_policy": TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()]),
        "audit_sink": InMemoryAuditSink(),
        "source_dir": tmp_path / "package",
    }


def test_publish_populates_digest_and_signature(rig):
    write_package_dir(rig["source_dir"])
    result = publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )
    assert result.manifest.digest.startswith("sha256:")
    assert result.manifest.signature
    assert rig["store"].exists(result.blob_key)
    assert rig["store"].exists(result.tag_key)


def test_publish_emits_audit_event_with_actor_and_digest(rig):
    write_package_dir(rig["source_dir"])
    result = publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )
    assert len(rig["audit_sink"].events) == 1
    event = rig["audit_sink"].events[0]
    assert event.actor == "ci-pipeline"
    assert event.digest == result.manifest.digest
    assert event.skill_id == VALID_MANIFEST["id"]


def test_duplicate_publish_returns_409(rig):
    write_package_dir(rig["source_dir"])
    publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )
    with pytest.raises(JaasError) as exc_info:
        publish_skill(
            source_dir=rig["source_dir"],
            store=rig["store"],
            signing_key=rig["signing_key"],
            trust_policy=rig["trust_policy"],
            actor="ci-pipeline",
            audit_sink=rig["audit_sink"],
        )
    assert exc_info.value.code == ErrorCode.DUPLICATE_PUBLISH


def test_tampered_archive_is_rejected_at_reverification(rig):
    write_package_dir(rig["source_dir"])
    result = publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )
    tampered_archive = rig["store"].read(result.blob_key) + b"tampered-bytes"
    with pytest.raises(JaasError) as exc_info:
        verify_artifact(
            archive_bytes=tampered_archive,
            digest=result.manifest.digest,
            signature=result.manifest.signature,
            trust_policy=rig["trust_policy"],
        )
    assert exc_info.value.code == ErrorCode.CORRUPT_PAYLOAD


def test_signature_from_untrusted_key_is_rejected(rig):
    write_package_dir(rig["source_dir"])
    result = publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )
    other_keypair = generate_dev_keypair()
    attacker_trust_policy = TrustPolicy(trusted_public_keys_pem=[other_keypair.public_key_pem()])
    archive = rig["store"].read(result.blob_key)
    with pytest.raises(JaasError) as exc_info:
        verify_artifact(
            archive_bytes=archive,
            digest=result.manifest.digest,
            signature=result.manifest.signature,
            trust_policy=attacker_trust_policy,
        )
    assert exc_info.value.code == ErrorCode.INVALID_SIGNATURE


def test_publish_archives_the_entrypoint_file_when_present(rig):
    write_package_dir(rig["source_dir"])
    # VALID_MANIFEST's entrypoint is "executor.py".
    (rig["source_dir"] / "executor.py").write_text("def run(): ...\n")

    result = publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )

    files = extract_archive(rig["store"].read(result.blob_key))
    assert files["executor.py"] == b"def run(): ...\n"


def test_publish_skips_the_entrypoint_file_when_absent(rig):
    write_package_dir(rig["source_dir"])
    # VALID_MANIFEST's entrypoint ("executor.py") is deliberately never created.

    result = publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )

    files = extract_archive(rig["store"].read(result.blob_key))
    assert "executor.py" not in files


@pytest.mark.parametrize("bad_entrypoint", ["../secret.txt", "/etc/secret.txt"])
def test_publish_rejects_a_path_traversing_entrypoint(rig, bad_entrypoint):
    """entrypoint is attacker/user-controlled content straight out of
    manifest.yaml — same guard as drafts/store.py's _safe_file_path."""
    manifest = copy.deepcopy(VALID_MANIFEST)
    manifest["entrypoint"] = bad_entrypoint
    write_package_dir(rig["source_dir"], manifest=manifest)
    (rig["source_dir"].parent / "secret.txt").write_text("do not leak")

    result = publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )

    archive = rig["store"].read(result.blob_key)
    assert b"do not leak" not in archive
    assert bad_entrypoint not in extract_archive(archive)


def test_missing_dependency_rejected(rig):
    write_package_dir(rig["source_dir"])
    with pytest.raises(JaasError) as exc_info:
        publish_skill(
            source_dir=rig["source_dir"],
            store=rig["store"],
            signing_key=rig["signing_key"],
            trust_policy=rig["trust_policy"],
            actor="ci-pipeline",
            audit_sink=rig["audit_sink"],
            existing_dependency_graph={},  # acme.util.tokenizer is not published
        )
    assert exc_info.value.code == ErrorCode.MISSING_DEPENDENCY


def test_circular_dependency_rejected(rig):
    manifest = copy.deepcopy(VALID_MANIFEST)
    manifest["id"] = "acme.text.summarizer"
    write_package_dir(
        rig["source_dir"],
        manifest=manifest,
        dependencies=[{"id": "acme.util.tokenizer", "versionConstraint": ">=1.0.0,<2.0.0"}],
    )
    # tokenizer already published and depends back on summarizer -> cycle
    existing_graph = {"acme.util.tokenizer": ["acme.text.summarizer"]}
    with pytest.raises(JaasError) as exc_info:
        publish_skill(
            source_dir=rig["source_dir"],
            store=rig["store"],
            signing_key=rig["signing_key"],
            trust_policy=rig["trust_policy"],
            actor="ci-pipeline",
            audit_sink=rig["audit_sink"],
            existing_dependency_graph=existing_graph,
        )
    assert exc_info.value.code == ErrorCode.CIRCULAR_DEPENDENCY


def test_mandatory_guardrail_blocks_publish_and_writes_nothing(rig):
    """Detection logic itself lives in the standalone jaas-guardrails
    service's own test suite — this only verifies publish_skill's wiring:
    a BLOCK finding from the client stops the publish before anything is
    written, regardless of what produced that finding."""
    write_package_dir(rig["source_dir"])
    fake_client = FakeGuardrailsClient(
        scan_result=GuardrailScanResult(
            blocking=(
                GuardrailFinding(
                    check_id="secret-scan",
                    file="manifest.yaml",
                    message="fake secret finding",
                    severity=GuardrailSeverity.BLOCK,
                ),
            ),
            warnings=(),
        )
    )
    with pytest.raises(JaasError) as exc_info:
        publish_skill(
            source_dir=rig["source_dir"],
            store=rig["store"],
            signing_key=rig["signing_key"],
            trust_policy=rig["trust_policy"],
            actor="ci-pipeline",
            audit_sink=rig["audit_sink"],
            guardrails_client=fake_client,
        )
    assert exc_info.value.code == ErrorCode.GUARDRAIL_VIOLATION
    assert exc_info.value.details["findings"][0]["check_id"] == "secret-scan"
    assert rig["audit_sink"].events == []
    expected_tag_key = make_tag_key(VALID_MANIFEST["id"], VALID_MANIFEST["version"])
    assert not rig["store"].exists(expected_tag_key)


def test_warn_only_guardrail_still_publishes_and_is_audited(rig):
    write_package_dir(rig["source_dir"])
    fake_client = FakeGuardrailsClient(
        scan_result=GuardrailScanResult(
            blocking=(),
            warnings=(
                GuardrailFinding(
                    check_id="unpinned-dependency-range",
                    file="dependencies.yaml",
                    message="fake warning",
                    severity=GuardrailSeverity.WARN,
                ),
            ),
        )
    )
    result = publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
        guardrails_client=fake_client,
    )
    assert rig["store"].exists(result.blob_key)
    event = rig["audit_sink"].events[0]
    assert event.guardrail_warning_ids == ("unpinned-dependency-range",)


def test_omitting_guardrails_client_skips_the_scan_entirely(rig):
    """Same opt-in-via-None shape as `existing_dependency_graph` — a caller
    that doesn't pass a client gets today's-equivalent-of-lenient behavior,
    not a crash or a forced network call."""
    write_package_dir(rig["source_dir"])
    result = publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
    )
    assert rig["store"].exists(result.blob_key)
    assert rig["audit_sink"].events[0].guardrail_warning_ids == ()


def test_guardrail_policy_enabled_ids_reach_the_client(rig):
    """Verifies the resolved policy's enabled_check_ids is what actually
    gets sent to the client — the specific check-selection behavior itself
    is the standalone service's responsibility, not this app's."""
    write_package_dir(rig["source_dir"])
    fake_client = FakeGuardrailsClient()
    policy = GuardrailPolicy(
        tenant_id="tnt_test", enabled_check_ids=frozenset({"dependency-typosquat-heuristic"})
    )
    publish_skill(
        source_dir=rig["source_dir"],
        store=rig["store"],
        signing_key=rig["signing_key"],
        trust_policy=rig["trust_policy"],
        actor="ci-pipeline",
        audit_sink=rig["audit_sink"],
        guardrails_client=fake_client,
        guardrail_policy=policy,
    )
    assert fake_client.last_scan_kwargs["enabled_check_ids"] == frozenset(
        {"dependency-typosquat-heuristic"}
    )
