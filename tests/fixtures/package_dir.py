"""Helper to materialize a canonical skill package directory (design.md §4.1) on disk."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.fixtures.manifests import (
    VALID_DEPENDENCIES,
    VALID_IO_SCHEMA,
    VALID_MANIFEST,
    VALID_PERMISSIONS,
)


def write_package_dir(
    root: Path,
    *,
    manifest: dict | None = None,
    io_schema: dict | None = None,
    permissions: list | None = None,
    dependencies: list | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest or VALID_MANIFEST))
    (root / "schema.json").write_text(json.dumps(io_schema or VALID_IO_SCHEMA))
    (root / "permissions.yaml").write_text(yaml.safe_dump(permissions or VALID_PERMISSIONS))
    (root / "dependencies.yaml").write_text(yaml.safe_dump(dependencies or VALID_DEPENDENCIES))
    return root
