import copy

import pytest

from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.validation.package import validate_skill_package
from tests.fixtures.manifests import (
    VALID_DEPENDENCIES,
    VALID_IO_SCHEMA,
    VALID_MANIFEST,
    VALID_PERMISSIONS,
)


def test_valid_package_validates_all_four_documents():
    result = validate_skill_package(
        manifest=VALID_MANIFEST,
        io_schema=VALID_IO_SCHEMA,
        permissions=VALID_PERMISSIONS,
        dependencies=VALID_DEPENDENCIES,
    )
    assert result.manifest.id == "acme.text.summarizer"
    assert result.permissions.root == VALID_PERMISSIONS
    assert result.dependencies.root[0].id == "acme.util.tokenizer"
    assert result.io_schema.inputs["type"] == "object"


def test_invalid_manifest_fails_the_whole_package():
    bad_manifest = copy.deepcopy(VALID_MANIFEST)
    bad_manifest["version"] = "not-semver"
    with pytest.raises(RuneError) as exc_info:
        validate_skill_package(
            manifest=bad_manifest,
            io_schema=VALID_IO_SCHEMA,
            permissions=VALID_PERMISSIONS,
            dependencies=VALID_DEPENDENCIES,
        )
    assert exc_info.value.code == ErrorCode.INVALID_VERSION_FORMAT
