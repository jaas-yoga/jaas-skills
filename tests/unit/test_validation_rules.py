import copy

import pytest

from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.validation.rules import (
    validate_dependencies,
    validate_io_schema,
    validate_manifest,
    validate_permissions,
)
from tests.fixtures.manifests import (
    VALID_DEPENDENCIES,
    VALID_IO_SCHEMA,
    VALID_MANIFEST,
    VALID_PERMISSIONS,
)


def test_valid_manifest_passes():
    doc = validate_manifest(VALID_MANIFEST)
    assert doc.id == "acme.text.summarizer"
    assert doc.runtime[0].family == "python"


def test_manifest_missing_required_field_is_schema_validation_failed():
    data = copy.deepcopy(VALID_MANIFEST)
    del data["owner"]
    with pytest.raises(RuneError) as exc_info:
        validate_manifest(data)
    assert exc_info.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED


@pytest.mark.parametrize("bad_id", ["nodots", "only.two", "Has.Upper.Case", "trailing-.dot.here"])
def test_manifest_bad_id_format(bad_id):
    data = copy.deepcopy(VALID_MANIFEST)
    data["id"] = bad_id
    with pytest.raises(RuneError) as exc_info:
        validate_manifest(data)
    assert exc_info.value.code == ErrorCode.INVALID_ID_FORMAT


@pytest.mark.parametrize("bad_version", ["1.2", "v1.2.3", "1.2.3.4", "latest"])
def test_manifest_bad_version_format(bad_version):
    data = copy.deepcopy(VALID_MANIFEST)
    data["version"] = bad_version
    with pytest.raises(RuneError) as exc_info:
        validate_manifest(data)
    assert exc_info.value.code == ErrorCode.INVALID_VERSION_FORMAT


def test_manifest_empty_runtime_list_rejected():
    data = copy.deepcopy(VALID_MANIFEST)
    data["runtime"] = []
    with pytest.raises(RuneError) as exc_info:
        validate_manifest(data)
    assert exc_info.value.code == ErrorCode.INVALID_RUNTIME_FORMAT


def test_manifest_bad_runtime_family_rejected():
    data = copy.deepcopy(VALID_MANIFEST)
    data["runtime"] = [{"family": "Python!", "versionRange": ">=3.10.0"}]
    with pytest.raises(RuneError) as exc_info:
        validate_manifest(data)
    assert exc_info.value.code == ErrorCode.INVALID_RUNTIME_FORMAT


def test_manifest_bad_runtime_range_rejected():
    data = copy.deepcopy(VALID_MANIFEST)
    data["runtime"] = [{"family": "python", "versionRange": "not-a-range"}]
    with pytest.raises(RuneError) as exc_info:
        validate_manifest(data)
    assert exc_info.value.code == ErrorCode.INVALID_RUNTIME_FORMAT


def test_io_schema_missing_required_field_rejected():
    with pytest.raises(RuneError) as exc_info:
        validate_io_schema({"inputs": {"type": "object"}})
    assert exc_info.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED


def test_valid_io_schema_passes():
    doc = validate_io_schema(VALID_IO_SCHEMA)
    assert doc.inputs["type"] == "object"


def test_io_schema_with_invalid_json_schema_rejected():
    data = {
        "inputs": {"type": "object", "required": "not-a-list"},
        "outputs": {"type": "object"},
    }
    with pytest.raises(RuneError) as exc_info:
        validate_io_schema(data)
    assert exc_info.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED


def test_valid_permissions_pass():
    doc = validate_permissions(VALID_PERMISSIONS)
    assert doc.root == VALID_PERMISSIONS


def test_permissions_wrong_shape_rejected():
    with pytest.raises(RuneError) as exc_info:
        validate_permissions({"not": "a-list"})
    assert exc_info.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED


def test_valid_dependencies_pass():
    doc = validate_dependencies(VALID_DEPENDENCIES)
    assert doc.root[0].id == "acme.util.tokenizer"


def test_dependencies_wrong_shape_rejected():
    with pytest.raises(RuneError) as exc_info:
        validate_dependencies({"not": "a-list"})
    assert exc_info.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED


def test_dependency_bad_id_format_rejected():
    data = [{"id": "bad", "versionConstraint": ">=1.0.0"}]
    with pytest.raises(RuneError) as exc_info:
        validate_dependencies(data)
    assert exc_info.value.code == ErrorCode.INVALID_DEPENDENCY_CONSTRAINT


def test_dependency_bad_constraint_rejected():
    data = [{"id": "acme.util.tokenizer", "versionConstraint": "not-a-constraint"}]
    with pytest.raises(RuneError) as exc_info:
        validate_dependencies(data)
    assert exc_info.value.code == ErrorCode.INVALID_DEPENDENCY_CONSTRAINT
