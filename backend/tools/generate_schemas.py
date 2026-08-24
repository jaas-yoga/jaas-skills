"""Regenerate the finalized JSON Schemas under schemas/ from the pydantic models.

The pydantic models in validation/models.py are the single source of truth
(design.md §4.2); this script emits their JSON Schema form as the checked-in,
finalized schemas deliverable for Phase 1. Run after changing any model:

    uv run python tools/generate_schemas.py

A test (tests/unit/test_schema_drift.py) fails CI if the checked-in files and
the models fall out of sync.
"""

from __future__ import annotations

import json
from pathlib import Path

from rune_registry.validation.models import (
    DependenciesDocument,
    IoSchemaDocument,
    ManifestDocument,
    PermissionsDocument,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

MODELS = {
    "manifest.schema.json": ManifestDocument,
    "schema.schema.json": IoSchemaDocument,
    "permissions.schema.json": PermissionsDocument,
    "dependencies.schema.json": DependenciesDocument,
}


def generate() -> dict[str, dict]:
    return {filename: model.model_json_schema(by_alias=True) for filename, model in MODELS.items()}


def write() -> None:
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, schema in generate().items():
        (SCHEMAS_DIR / filename).write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    write()
