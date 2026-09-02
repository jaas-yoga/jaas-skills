"""Bidirectional conversion between this registry's manifest.yaml and the
open agentskills.io SKILL.md format (YAML frontmatter + markdown body).

Design ref: IMPLEMENTATION_PLAN.md Phase 2.1. Deliberately v1/lossy in both
directions, per an explicit product decision:

- Only a single SKILL.md file round-trips. A skill directory with a
  scripts/references/assets folder isn't importable yet — this registry's
  packaging pipeline (artifact/packaging.py::collect_package_files) only
  ever bundles exactly four known documents plus one entrypoint file, no
  arbitrary extra files. Extending that is a separate, larger change.
- SKILL.md has no id/version/owner/category/runtime-compatibility concept
  at all — those are supplied explicitly by the caller on import (never
  guessed from the bare `name` field, which has no namespace and can't
  safely stand in for this registry's globally-unique dotted `id`).
- This registry's manifest has no license/allowed-tools concept, and no
  freeform-instructions field distinct from `description` — the closest
  analog is the entrypoint file's own content, which becomes the SKILL.md
  body verbatim on export when it's already a text/markdown file, or a
  synthesized summary otherwise (a program entrypoint has no home in a
  single SKILL.md file in this v1 scope, so it's dropped, not embedded).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from jaas_registry.artifact.packaging import DEFAULT_PACKAGE_FILE_CONTENTS
from jaas_registry.validation.models import ManifestDocument

_DELIMITER = "---"
_MAX_DESCRIPTION_LENGTH = 1024
_MAX_COMPATIBILITY_LENGTH = 500
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_TEXT_ENTRYPOINT_SUFFIXES = (".md", ".markdown", ".txt")


class SkillMdFormatError(ValueError):
    """Raised when a SKILL.md file doesn't satisfy the agentskills.io spec's
    structural rules (frontmatter delimiters, required fields, name shape)."""


@dataclass(frozen=True)
class ParsedSkillMd:
    name: str
    description: str
    license: str | None
    compatibility: str | None
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: str | None = None
    body: str = ""


def slugify_skill_id(skill_id: str) -> str:
    """SKILL.md's `name` field has no namespace and must be a bare
    lowercase-hyphen slug matching its own directory name — this
    registry's `id` is a dotted, 3+-segment namespaced identity
    (validation/models.py's ID_PATTERN). Each dot-segment is already
    lowercase-alnum-hyphen per that pattern and never starts/ends with a
    hyphen itself, so replacing dots with hyphens always produces a valid
    SKILL.md name with no further escaping needed."""
    return skill_id.replace(".", "-")


def manifest_to_skillmd(manifest: ManifestDocument, *, entrypoint_content: bytes | None) -> bytes:
    """Export direction. `entrypoint_content` is the raw bytes of the file
    `manifest.entrypoint` names, if it was present in the published
    package (None if it wasn't archived at publish time)."""
    description = manifest.description
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        description = description[: _MAX_DESCRIPTION_LENGTH - 1] + "…"

    metadata: dict[str, str] = {
        "jaas-id": manifest.id,
        "jaas-version": manifest.version,
        "jaas-category": manifest.category,
        "jaas-owner-team": manifest.owner.team,
    }
    if manifest.tags:
        metadata["jaas-tags"] = ",".join(manifest.tags)

    frontmatter: dict[str, object] = {
        "name": slugify_skill_id(manifest.id),
        "description": description,
        "metadata": metadata,
    }
    if manifest.runtime:
        compatibility = ", ".join(f"{rt.family} {rt.version_range}" for rt in manifest.runtime)
        if len(compatibility) <= _MAX_COMPATIBILITY_LENGTH:
            frontmatter["compatibility"] = compatibility

    is_text_entrypoint = manifest.entrypoint.lower().endswith(_TEXT_ENTRYPOINT_SUFFIXES)
    if entrypoint_content is not None and is_text_entrypoint:
        body = entrypoint_content.decode("utf-8", errors="replace").strip()
    else:
        body = f"# {manifest.name}\n\n{manifest.description}\n"
        if entrypoint_content is not None:
            body += (
                f"\n_Converted from jaas-registry skill `{manifest.id}` — the "
                f"original entrypoint (`{manifest.entrypoint}`) is not a text "
                f"file and is not included in this export._\n"
            )

    frontmatter_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    return f"{_DELIMITER}\n{frontmatter_yaml}{_DELIMITER}\n\n{body}\n".encode()


def parse_skillmd(raw: bytes) -> ParsedSkillMd:
    text = raw.decode("utf-8")
    prefix = f"{_DELIMITER}\n"
    if not text.startswith(prefix):
        raise SkillMdFormatError("SKILL.md must start with '---' YAML frontmatter")

    rest = text[len(prefix) :]
    closing = f"\n{_DELIMITER}\n"
    frontmatter_block, delimiter, body = rest.partition(closing)
    if not delimiter:
        raise SkillMdFormatError("SKILL.md frontmatter is not closed with a second '---'")

    frontmatter = yaml.safe_load(frontmatter_block) or {}
    if not isinstance(frontmatter, dict):
        raise SkillMdFormatError("SKILL.md frontmatter must be a YAML mapping")

    name = frontmatter.get("name")
    if not name or not isinstance(name, str):
        raise SkillMdFormatError("SKILL.md frontmatter is missing required field 'name'")
    if not _NAME_PATTERN.match(name):
        raise SkillMdFormatError(
            f"SKILL.md 'name' must be lowercase letters/numbers/hyphens, no "
            f"leading/trailing/consecutive hyphens: got {name!r}"
        )

    description = frontmatter.get("description")
    if not description or not isinstance(description, str):
        raise SkillMdFormatError("SKILL.md frontmatter is missing required field 'description'")

    return ParsedSkillMd(
        name=name,
        description=description,
        license=frontmatter.get("license"),
        compatibility=frontmatter.get("compatibility"),
        metadata=frontmatter.get("metadata") or {},
        allowed_tools=frontmatter.get("allowed-tools"),
        body=body.strip("\n"),
    )


def skillmd_to_source_documents(
    raw: bytes,
    *,
    id: str,  # noqa: A002 - matches ManifestDocument's own field name
    version: str,
    owner_team: str,
    category: str,
    runtime: list[tuple[str, str]],
    api_version: str = "v1",
) -> dict[str, bytes]:
    """Import direction: produces the same {filename: bytes} shape
    artifact/packaging.py::collect_package_files returns, ready to write to
    disk and feed through the existing validate_skill_package()/
    publish_skill() pipeline unchanged. `id`/`version`/`owner_team`/
    `category`/`runtime` all come from the caller (jaasctl import's
    --id/--version/--owner-team/--category/--runtime flags) since none of
    them exist in SKILL.md's frontmatter — see this module's docstring."""
    parsed = parse_skillmd(raw)

    manifest = {
        "apiVersion": api_version,
        "id": id,
        "name": parsed.name,
        "version": version,
        "description": parsed.description,
        "owner": {"team": owner_team},
        # The SKILL.md body is the skill's real instructions — preserved
        # verbatim as its own entrypoint file, the same pattern
        # artifact/publish.py::load_source_documents already documents
        # (prompt.md/SKILL.md/executor.py are all valid entrypoints).
        "entrypoint": "SKILL.md",
        "category": category,
        "tags": (
            parsed.metadata["jaas-tags"].split(",") if parsed.metadata.get("jaas-tags") else []
        ),
        "runtime": [
            {"family": family, "versionRange": version_range} for family, version_range in runtime
        ],
    }
    return {
        "manifest.yaml": yaml.safe_dump(manifest, sort_keys=False).encode("utf-8"),
        "schema.json": DEFAULT_PACKAGE_FILE_CONTENTS["schema.json"],
        "permissions.yaml": DEFAULT_PACKAGE_FILE_CONTENTS["permissions.yaml"],
        "dependencies.yaml": DEFAULT_PACKAGE_FILE_CONTENTS["dependencies.yaml"],
        "SKILL.md": raw,
    }
