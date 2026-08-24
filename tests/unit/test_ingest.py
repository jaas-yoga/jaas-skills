import copy
import json

import pytest

from rune_registry.guardrails.certification import CertificationStatus, GuardrailCertification
from rune_registry.index.ingest import (
    index_entry_from_manifest,
    parse_published_record,
    serialize_published_record,
)
from rune_registry.validation.models import DependenciesDocument, PermissionsDocument
from rune_registry.validation.rules import validate_manifest
from tests.fixtures.manifests import VALID_DEPENDENCIES, VALID_MANIFEST, VALID_PERMISSIONS


def test_index_entry_from_published_manifest():
    manifest = validate_manifest(VALID_MANIFEST)
    published = manifest.model_copy(update={"digest": "sha256:" + "a" * 64, "signature": "sig"})

    permissions = PermissionsDocument.model_validate(VALID_PERMISSIONS)
    dependencies = DependenciesDocument.model_validate(VALID_DEPENDENCIES)

    entry = index_entry_from_manifest(
        published,
        permissions=permissions,
        dependencies=dependencies,
        publish_timestamp="2026-01-01T00:00:00+00:00",
    )

    assert entry.id == manifest.id
    assert entry.digest == "sha256:" + "a" * 64
    assert entry.permissions == tuple(VALID_PERMISSIONS)
    assert entry.dependencies == (("acme.util.tokenizer", ">=1.0.0,<2.0.0"),)
    assert entry.runtime_families == ("python",)
    assert entry.publish_timestamp == "2026-01-01T00:00:00+00:00"


def test_index_entry_without_permissions_or_dependencies_defaults_empty():
    manifest = validate_manifest(VALID_MANIFEST)
    published = manifest.model_copy(update={"digest": "sha256:" + "a" * 64, "signature": "sig"})
    entry = index_entry_from_manifest(published)
    assert entry.permissions == ()
    assert entry.dependencies == ()


def test_index_entry_requires_digest():
    manifest = validate_manifest(copy.deepcopy(VALID_MANIFEST))
    assert manifest.digest is None
    with pytest.raises(ValueError):
        index_entry_from_manifest(manifest)


def test_published_record_roundtrip():
    manifest = validate_manifest(VALID_MANIFEST)
    published = manifest.model_copy(update={"digest": "sha256:" + "a" * 64, "signature": "sig"})
    permissions = PermissionsDocument.model_validate(VALID_PERMISSIONS)
    dependencies = DependenciesDocument.model_validate(VALID_DEPENDENCIES)

    record = serialize_published_record(
        manifest=published,
        permissions=permissions,
        dependencies=dependencies,
        publish_timestamp="2026-01-01T00:00:00+00:00",
    )
    entry = parse_published_record(record)

    assert entry.id == manifest.id
    assert entry.digest == "sha256:" + "a" * 64
    assert entry.permissions == tuple(VALID_PERMISSIONS)
    assert entry.dependencies == (("acme.util.tokenizer", ">=1.0.0,<2.0.0"),)
    assert entry.publish_timestamp == "2026-01-01T00:00:00+00:00"
    # No provenance passed in -> stays None, not e.g. empty string. This
    # distinguishes "published via a non-git path" from "released via git
    # with an unknown repo", which a defaulted "" would blur.
    assert entry.source_repo is None
    assert entry.source_commit is None
    assert entry.source_tag is None
    assert entry.source_branch is None
    assert entry.ci_run_url is None
    # No certification passed in -> None/empty, not e.g. level 0 — this
    # distinguishes "no guardrails service reachable at publish time" from
    # "certified at nothing", which a defaulted 0 would blur.
    assert entry.guardrail_certified_level is None
    assert entry.guardrail_level_statuses == ()
    assert entry.guardrail_warning_check_ids == ()


def test_published_record_roundtrips_guardrail_certification():
    manifest = validate_manifest(VALID_MANIFEST)
    published = manifest.model_copy(update={"digest": "sha256:" + "a" * 64, "signature": "sig"})
    permissions = PermissionsDocument.model_validate(VALID_PERMISSIONS)
    dependencies = DependenciesDocument.model_validate(VALID_DEPENDENCIES)
    certification = GuardrailCertification(
        highest_certified_level=2,
        level_statuses=(
            (1, CertificationStatus.CERTIFIED),
            (2, CertificationStatus.CERTIFIED),
            (3, CertificationStatus.ATTEMPTED_WITH_FINDINGS),
            (4, CertificationStatus.NOT_ATTEMPTED),
        ),
        warning_check_ids=("pii-pattern-scan",),
    )

    record = serialize_published_record(
        manifest=published,
        permissions=permissions,
        dependencies=dependencies,
        publish_timestamp="2026-01-01T00:00:00+00:00",
        certification=certification,
    )
    entry = parse_published_record(record)

    assert entry.guardrail_certified_level == 2
    assert entry.guardrail_level_statuses == (
        (1, "certified"),
        (2, "certified"),
        (3, "attempted_with_findings"),
        (4, "not_attempted"),
    )
    assert entry.guardrail_warning_check_ids == ("pii-pattern-scan",)


def test_parse_published_record_predating_certification_defaults_to_none():
    manifest = validate_manifest(VALID_MANIFEST)
    published = manifest.model_copy(update={"digest": "sha256:" + "a" * 64, "signature": "sig"})
    permissions = PermissionsDocument.model_validate(VALID_PERMISSIONS)
    dependencies = DependenciesDocument.model_validate(VALID_DEPENDENCIES)

    record = serialize_published_record(
        manifest=published,
        permissions=permissions,
        dependencies=dependencies,
        publish_timestamp="2026-01-01T00:00:00+00:00",
    )
    obj = json.loads(record)
    del obj["guardrailCertifiedLevel"]
    del obj["guardrailLevelStatuses"]
    del obj["guardrailWarningCheckIds"]

    entry = parse_published_record(json.dumps(obj).encode())

    assert entry.guardrail_certified_level is None
    assert entry.guardrail_level_statuses == ()
    assert entry.guardrail_warning_check_ids == ()


def test_published_record_roundtrips_git_provenance():
    manifest = validate_manifest(VALID_MANIFEST)
    published = manifest.model_copy(update={"digest": "sha256:" + "a" * 64, "signature": "sig"})
    permissions = PermissionsDocument.model_validate(VALID_PERMISSIONS)
    dependencies = DependenciesDocument.model_validate(VALID_DEPENDENCIES)

    record = serialize_published_record(
        manifest=published,
        permissions=permissions,
        dependencies=dependencies,
        publish_timestamp="2026-01-01T00:00:00+00:00",
        source_repo="acme/tool-x",
        source_commit="abc123",
        source_tag="v1.2.3",
        source_branch="staging",
        source_path="acme.tool.x",
        ci_run_url="https://github.com/acme/tool-x/actions/runs/1",
    )
    entry = parse_published_record(record)

    assert entry.source_repo == "acme/tool-x"
    assert entry.source_commit == "abc123"
    assert entry.source_tag == "v1.2.3"
    assert entry.source_branch == "staging"
    assert entry.source_path == "acme.tool.x"
    assert entry.ci_run_url == "https://github.com/acme/tool-x/actions/runs/1"


def test_parse_published_record_predating_source_path_defaults_to_none():
    """A record written before source_path existed has no "sourcePath" key
    at all — must read back as None (repo root is the skill), not raise."""
    manifest = validate_manifest(VALID_MANIFEST)
    published = manifest.model_copy(update={"digest": "sha256:" + "a" * 64, "signature": "sig"})
    permissions = PermissionsDocument.model_validate(VALID_PERMISSIONS)
    dependencies = DependenciesDocument.model_validate(VALID_DEPENDENCIES)

    record = serialize_published_record(
        manifest=published,
        permissions=permissions,
        dependencies=dependencies,
        publish_timestamp="2026-01-01T00:00:00+00:00",
        source_repo="acme/tool-x",
        source_tag="v1.2.3",
    )
    obj = json.loads(record)
    del obj["sourcePath"]
    entry = parse_published_record(json.dumps(obj).encode())

    assert entry.source_path is None
