"""Structural models for the four documents in the canonical skill package layout.

Design ref: design.md §4.1 (Package Layout), §4.2 (manifest.yaml Required Fields).

`digest` and `signature` are optional here because they don't exist until the
Phase 2 publish pipeline computes them; a raw, unpublished manifest.yaml won't
have them yet.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, RootModel

ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*){2,}$")


class Owner(BaseModel):
    team: str
    contact: str | None = None


class RuntimeCompatibility(BaseModel):
    family: str
    version_range: str = Field(alias="versionRange")

    model_config = {"populate_by_name": True}


class ManifestDocument(BaseModel):
    """manifest.yaml"""

    api_version: str = Field(alias="apiVersion")
    id: str
    name: str
    version: str
    description: str
    owner: Owner
    entrypoint: str
    category: str
    tags: list[str] = Field(default_factory=list)
    runtime: list[RuntimeCompatibility]
    digest: str | None = None
    signature: str | None = None
    # "dev-rsa" | "sigstore" (artifact/signing.py vs. artifact/sigstore_sign.py)
    # — like digest/signature, unset until publish. A record predating this
    # field (parsed back via index/ingest.py) also reads as None here; that
    # absence is treated as "dev-rsa" at the one place that matters
    # (index_entry_from_manifest), not here — this field only ever reflects
    # what's actually in the JSON, never guesses.
    signature_kind: str | None = None

    model_config = {"populate_by_name": True}


class IoSchemaDocument(BaseModel):
    """schema.json — the skill's own input/output contract, each a JSON Schema document."""

    inputs: dict
    outputs: dict


class PermissionsDocument(RootModel[list[str]]):
    """permissions.yaml — a flat list of permission scope strings."""

    root: list[str] = Field(default_factory=list)


class DependencyDeclaration(BaseModel):
    id: str
    version_constraint: str = Field(alias="versionConstraint")

    model_config = {"populate_by_name": True}


class DependenciesDocument(RootModel[list[DependencyDeclaration]]):
    """dependencies.yaml — a flat list of {id, versionConstraint} entries."""

    root: list[DependencyDeclaration] = Field(default_factory=list)
