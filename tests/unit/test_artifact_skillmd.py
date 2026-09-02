import pytest
import yaml

from jaas_registry.artifact.skillmd import (
    SkillMdFormatError,
    manifest_to_skillmd,
    parse_skillmd,
    skillmd_to_source_documents,
    slugify_skill_id,
)
from jaas_registry.validation.models import ManifestDocument
from tests.fixtures.manifests import VALID_MANIFEST


def _valid_manifest(**overrides) -> ManifestDocument:
    data = {**VALID_MANIFEST, **overrides}
    return ManifestDocument.model_validate(data)


class TestSlugifySkillId:
    def test_replaces_dots_with_hyphens(self):
        assert slugify_skill_id("acme.text.summarizer") == "acme-text-summarizer"

    def test_result_is_a_valid_skillmd_name(self):
        import re

        slug = slugify_skill_id("acme.text.summarizer")
        assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", slug)


class TestManifestToSkillmd:
    def test_frontmatter_has_required_fields(self):
        manifest = _valid_manifest()
        out = manifest_to_skillmd(manifest, entrypoint_content=None)
        parsed = parse_skillmd(out)

        assert parsed.name == "acme-text-summarizer"
        assert parsed.description == manifest.description

    def test_lossy_fields_are_preserved_under_metadata(self):
        manifest = _valid_manifest()
        parsed = parse_skillmd(manifest_to_skillmd(manifest, entrypoint_content=None))

        assert parsed.metadata["jaas-id"] == manifest.id
        assert parsed.metadata["jaas-version"] == manifest.version
        assert parsed.metadata["jaas-category"] == manifest.category
        assert parsed.metadata["jaas-owner-team"] == manifest.owner.team

    def test_runtime_becomes_compatibility_free_text(self):
        manifest = _valid_manifest()
        parsed = parse_skillmd(manifest_to_skillmd(manifest, entrypoint_content=None))

        assert "python" in parsed.compatibility
        assert ">=3.10.0,<4.0.0" in parsed.compatibility

    def test_markdown_entrypoint_becomes_the_body_verbatim(self):
        manifest = _valid_manifest(entrypoint="prompt.md")
        content = b"# Do the thing\n\nStep 1. Do it.\n"
        parsed = parse_skillmd(manifest_to_skillmd(manifest, entrypoint_content=content))

        assert parsed.body == "# Do the thing\n\nStep 1. Do it."

    def test_non_text_entrypoint_produces_a_summary_body_not_the_program(self):
        manifest = _valid_manifest(entrypoint="executor.py")
        content = b"import os\nprint('hello')\n"
        parsed = parse_skillmd(manifest_to_skillmd(manifest, entrypoint_content=content))

        assert "import os" not in parsed.body
        assert manifest.description in parsed.body

    def test_description_over_1024_chars_is_truncated(self):
        manifest = _valid_manifest(description="x" * 2000)
        parsed = parse_skillmd(manifest_to_skillmd(manifest, entrypoint_content=None))

        assert len(parsed.description) <= 1024


class TestParseSkillmd:
    def test_parses_minimal_valid_file(self):
        raw = b"---\nname: pdf-processing\ndescription: Handles PDFs.\n---\n\nBody text.\n"
        parsed = parse_skillmd(raw)

        assert parsed.name == "pdf-processing"
        assert parsed.description == "Handles PDFs."
        assert parsed.body == "Body text."

    def test_missing_frontmatter_delimiter_raises(self):
        with pytest.raises(SkillMdFormatError):
            parse_skillmd(b"name: pdf-processing\ndescription: x\n")

    def test_unclosed_frontmatter_raises(self):
        with pytest.raises(SkillMdFormatError):
            parse_skillmd(b"---\nname: pdf-processing\ndescription: x\n")

    def test_missing_name_raises(self):
        with pytest.raises(SkillMdFormatError):
            parse_skillmd(b"---\ndescription: x\n---\n\nBody\n")

    def test_missing_description_raises(self):
        with pytest.raises(SkillMdFormatError):
            parse_skillmd(b"---\nname: pdf-processing\n---\n\nBody\n")

    def test_invalid_name_pattern_raises(self):
        with pytest.raises(SkillMdFormatError):
            parse_skillmd(b"---\nname: PDF-Processing\ndescription: x\n---\n\nBody\n")

    def test_name_with_consecutive_hyphens_raises(self):
        with pytest.raises(SkillMdFormatError):
            parse_skillmd(b"---\nname: pdf--processing\ndescription: x\n---\n\nBody\n")


class TestSkillmdToSourceDocuments:
    RAW = (
        b"---\nname: pdf-processing\ndescription: Extract text from PDFs.\n---\n\n"
        b"# PDF processing\n\nUse pdftotext.\n"
    )

    def test_produces_all_four_canonical_files_plus_skillmd_entrypoint(self):
        files = skillmd_to_source_documents(
            self.RAW,
            id="acme.doc.pdf-processing",
            version="1.0.0",
            owner_team="platform",
            category="documents",
            runtime=[("python", ">=3.10.0,<4.0.0")],
        )

        assert set(files) == {
            "manifest.yaml",
            "schema.json",
            "permissions.yaml",
            "dependencies.yaml",
            "SKILL.md",
        }
        assert files["SKILL.md"] == self.RAW

    def test_manifest_yaml_is_valid_and_round_trips_the_supplied_fields(self):
        files = skillmd_to_source_documents(
            self.RAW,
            id="acme.doc.pdf-processing",
            version="1.0.0",
            owner_team="platform",
            category="documents",
            runtime=[("python", ">=3.10.0,<4.0.0")],
        )
        manifest_data = yaml.safe_load(files["manifest.yaml"])
        manifest = ManifestDocument.model_validate(manifest_data)

        assert manifest.id == "acme.doc.pdf-processing"
        assert manifest.version == "1.0.0"
        assert manifest.owner.team == "platform"
        assert manifest.category == "documents"
        assert manifest.entrypoint == "SKILL.md"
        assert manifest.name == "pdf-processing"
        assert manifest.description == "Extract text from PDFs."
        assert manifest.runtime[0].family == "python"
        assert manifest.runtime[0].version_range == ">=3.10.0,<4.0.0"

    def test_permissions_and_dependencies_default_to_empty(self):
        files = skillmd_to_source_documents(
            self.RAW,
            id="acme.doc.pdf-processing",
            version="1.0.0",
            owner_team="platform",
            category="documents",
            runtime=[("python", ">=3.10.0,<4.0.0")],
        )

        assert yaml.safe_load(files["permissions.yaml"]) == []
        assert yaml.safe_load(files["dependencies.yaml"]) == []

    def test_malformed_skillmd_raises(self):
        with pytest.raises(SkillMdFormatError):
            skillmd_to_source_documents(
                b"not frontmatter at all",
                id="acme.doc.pdf-processing",
                version="1.0.0",
                owner_team="platform",
                category="documents",
                runtime=[("python", ">=3.10.0,<4.0.0")],
            )


class TestRoundTrip:
    def test_export_then_import_preserves_identity_via_metadata(self):
        """The exported SKILL.md doesn't carry a machine-usable id (SKILL.md
        has no such concept) -- but a human/tool re-importing it can recover
        the original id/version/category/owner from the jaas-* metadata keys
        this module writes on export, rather than losing them entirely."""
        manifest = _valid_manifest()
        exported = manifest_to_skillmd(manifest, entrypoint_content=b"# Instructions\n")
        parsed = parse_skillmd(exported)

        files = skillmd_to_source_documents(
            exported,
            id=parsed.metadata["jaas-id"],
            version=parsed.metadata["jaas-version"],
            owner_team=parsed.metadata["jaas-owner-team"],
            category=parsed.metadata["jaas-category"],
            runtime=[("python", ">=3.10.0,<4.0.0")],
        )
        reimported = ManifestDocument.model_validate(yaml.safe_load(files["manifest.yaml"]))

        assert reimported.id == manifest.id
        assert reimported.version == manifest.version
        assert reimported.category == manifest.category
        assert reimported.owner.team == manifest.owner.team
