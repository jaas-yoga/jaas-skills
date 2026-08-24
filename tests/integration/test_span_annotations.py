"""Confirms design.md §10.3.2 ("span annotations for validation and policy
outcomes") is actually wired through the real authz, verification, and publish
code paths, not just the annotate_current_span_error() helper in isolation.
"""

import copy

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.common.errors import JaasError
from jaas_registry.observability.tracing import build_tracer
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET
from tests.fixtures.manifests import VALID_MANIFEST
from tests.fixtures.package_dir import write_package_dir


def test_authz_denial_annotates_the_active_span():
    exporter = InMemorySpanExporter()
    tracer = build_tracer(exporter=exporter)
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )

    with tracer.start_as_current_span("request"), pytest.raises(JaasError):
        authorizer.check(token=None, tenant_header=None, required_permissions=())

    span = exporter.get_finished_spans()[0]
    assert span.events[0].attributes["error.code"] == "UNAUTHORIZED"


def test_publish_validation_failure_annotates_the_active_span(tmp_path):
    exporter = InMemorySpanExporter()
    tracer = build_tracer(exporter=exporter)
    keypair = generate_dev_keypair()

    bad_manifest = copy.deepcopy(VALID_MANIFEST)
    bad_manifest["version"] = "not-semver"
    write_package_dir(tmp_path / "pkg", manifest=bad_manifest)

    with tracer.start_as_current_span("jaasctl.publish"), pytest.raises(JaasError):
        publish_skill(
            source_dir=tmp_path / "pkg",
            store=LocalFilesystemStore(tmp_path / "storage"),
            signing_key=keypair,
            trust_policy=TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()]),
            actor="ci",
            audit_sink=InMemoryAuditSink(),
        )

    span = exporter.get_finished_spans()[0]
    assert span.events[0].attributes["error.code"] == "INVALID_VERSION_FORMAT"


def test_storage_spans_nest_under_the_publish_span(tmp_path):
    exporter = InMemorySpanExporter()
    tracer = build_tracer(exporter=exporter)
    keypair = generate_dev_keypair()
    store = LocalFilesystemStore(tmp_path / "storage", tracer=tracer)

    write_package_dir(tmp_path / "pkg")
    with tracer.start_as_current_span("jaasctl.publish") as parent:
        publish_skill(
            source_dir=tmp_path / "pkg",
            store=store,
            signing_key=keypair,
            trust_policy=TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()]),
            actor="ci",
            audit_sink=InMemoryAuditSink(),
        )
        parent_trace_id = parent.get_span_context().trace_id

    spans = exporter.get_finished_spans()
    storage_spans = [s for s in spans if s.name.startswith("storage.")]
    assert len(storage_spans) == 2  # write_blob_if_absent + write_tag_if_absent
    assert all(s.context.trace_id == parent_trace_id for s in storage_spans)
