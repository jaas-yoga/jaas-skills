"""Validation rules: required fields, SemVer, id namespace, runtime format, dependency constraints.

Design ref: implementation-plan.md Phase 1 task 2.

Each `validate_*` function raises JaasError with a specific, stable code on the
first rule it fails, so callers get a deterministic reason rather than a bag of
pydantic errors.
"""

from __future__ import annotations

import re

import semantic_version
from jsonschema.validators import Draft202012Validator
from pydantic import ValidationError as PydanticValidationError

from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.validation.models import (
    ID_PATTERN,
    DependenciesDocument,
    DependencyDeclaration,
    IoSchemaDocument,
    ManifestDocument,
    PermissionsDocument,
    RuntimeCompatibility,
)

RUNTIME_FAMILY_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def _wrap_pydantic_error(exc: PydanticValidationError) -> JaasError:
    return JaasError(
        ErrorCode.SCHEMA_VALIDATION_FAILED,
        "document is missing required fields or has the wrong shape",
        details={"errors": exc.errors(include_url=False)},
    )


def parse_manifest_fields(data: dict) -> ManifestDocument:
    try:
        return ManifestDocument.model_validate(data)
    except PydanticValidationError as exc:
        raise _wrap_pydantic_error(exc) from exc


def validate_id_format(id_: str) -> None:
    if not ID_PATTERN.match(id_):
        raise JaasError(
            ErrorCode.INVALID_ID_FORMAT,
            f"id '{id_}' must match 'vendor.domain.capability' "
            "(lowercase, dot-separated, at least 3 segments)",
        )


def validate_semver(version: str) -> None:
    try:
        semantic_version.Version(version)
    except ValueError as exc:
        raise JaasError(
            ErrorCode.INVALID_VERSION_FORMAT, f"version '{version}' is not strict SemVer"
        ) from exc


def validate_runtime_declarations(runtimes: list[RuntimeCompatibility]) -> None:
    if not runtimes:
        raise JaasError(
            ErrorCode.INVALID_RUNTIME_FORMAT,
            "at least one runtime compatibility declaration is required",
        )
    for rt in runtimes:
        if not RUNTIME_FAMILY_PATTERN.match(rt.family):
            raise JaasError(
                ErrorCode.INVALID_RUNTIME_FORMAT,
                f"runtime family '{rt.family}' must be lowercase alphanumeric/hyphen",
            )
        try:
            semantic_version.SimpleSpec(rt.version_range)
        except ValueError as exc:
            raise JaasError(
                ErrorCode.INVALID_RUNTIME_FORMAT,
                f"runtime version range '{rt.version_range}' for '{rt.family}' is invalid: {exc}",
            ) from exc


def validate_manifest(data: dict) -> ManifestDocument:
    """Run the full manifest.yaml rule chain against a raw payload."""
    manifest = parse_manifest_fields(data)
    validate_id_format(manifest.id)
    validate_semver(manifest.version)
    validate_runtime_declarations(manifest.runtime)
    return manifest


def validate_io_schema(data: dict) -> IoSchemaDocument:
    """schema.json validation: structurally present, and each side is a valid JSON Schema."""
    try:
        doc = IoSchemaDocument.model_validate(data)
    except PydanticValidationError as exc:
        raise _wrap_pydantic_error(exc) from exc

    for side, sub_schema in (("inputs", doc.inputs), ("outputs", doc.outputs)):
        try:
            Draft202012Validator.check_schema(sub_schema)
        except Exception as exc:
            raise JaasError(
                ErrorCode.SCHEMA_VALIDATION_FAILED,
                f"schema.json '{side}' is not a valid JSON Schema document: {exc}",
            ) from exc
    return doc


def validate_permissions(data: list | dict) -> PermissionsDocument:
    try:
        return PermissionsDocument.model_validate(data)
    except PydanticValidationError as exc:
        raise _wrap_pydantic_error(exc) from exc


def _validate_dependency_declaration(dep: DependencyDeclaration) -> None:
    if not ID_PATTERN.match(dep.id):
        raise JaasError(
            ErrorCode.INVALID_DEPENDENCY_CONSTRAINT,
            f"dependency id '{dep.id}' does not match required id format",
        )
    try:
        semantic_version.SimpleSpec(dep.version_constraint)
    except ValueError as exc:
        raise JaasError(
            ErrorCode.INVALID_DEPENDENCY_CONSTRAINT,
            f"dependency '{dep.id}' has invalid version constraint "
            f"'{dep.version_constraint}': {exc}",
        ) from exc


def validate_dependencies(data: list | dict) -> DependenciesDocument:
    try:
        doc = DependenciesDocument.model_validate(data)
    except PydanticValidationError as exc:
        raise _wrap_pydantic_error(exc) from exc
    for dep in doc.root:
        _validate_dependency_declaration(dep)
    return doc
