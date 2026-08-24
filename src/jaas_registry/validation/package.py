"""Whole-package validation: the four documents in design.md §4.1, validated together."""

from __future__ import annotations

from dataclasses import dataclass

from jaas_registry.validation.models import (
    DependenciesDocument,
    IoSchemaDocument,
    ManifestDocument,
    PermissionsDocument,
)
from jaas_registry.validation.rules import (
    validate_dependencies,
    validate_io_schema,
    validate_manifest,
    validate_permissions,
)


@dataclass(frozen=True)
class SkillPackageDocuments:
    manifest: ManifestDocument
    io_schema: IoSchemaDocument
    permissions: PermissionsDocument
    dependencies: DependenciesDocument


def validate_skill_package(
    *,
    manifest: dict,
    io_schema: dict,
    permissions: list | dict,
    dependencies: list | dict,
) -> SkillPackageDocuments:
    """Validate the four package documents; raises JaasError on the first failing rule."""
    return SkillPackageDocuments(
        manifest=validate_manifest(manifest),
        io_schema=validate_io_schema(io_schema),
        permissions=validate_permissions(permissions),
        dependencies=validate_dependencies(dependencies),
    )
