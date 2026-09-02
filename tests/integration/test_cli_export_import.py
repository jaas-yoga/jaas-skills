"""jaasctl export / jaasctl import — Phase 2.1 (SKILL.md interop).
export is a pure HTTP client of the backend API (same convention as
test_cli_release.py); import is purely local/offline, like validate."""

from __future__ import annotations

import json

import pytest
import yaml

from jaas_registry.artifact.packaging import build_normalized_archive
from jaas_registry.artifact.skillmd import manifest_to_skillmd
from jaas_registry.cli import main
from jaas_registry.validation.models import ManifestDocument
from tests.fixtures.manifests import VALID_MANIFEST


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JAAS_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("JAAS_POLICY_DIR", str(tmp_path / "policy"))


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = json.dumps(payload) if payload is not None else content.decode(errors="replace")

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class TestCmdExport:
    def _archive_with_markdown_entrypoint(self) -> bytes:
        manifest_yaml = yaml.safe_dump({**VALID_MANIFEST, "entrypoint": "prompt.md"})
        return build_normalized_archive(
            {
                "manifest.yaml": manifest_yaml.encode(),
                "schema.json": b"{}",
                "permissions.yaml": b"[]\n",
                "dependencies.yaml": b"[]\n",
                "prompt.md": b"# Summarize\n\nSummarize the input text.\n",
            }
        )

    def test_writes_a_skillmd_file(self, tmp_path, capsys, monkeypatch):
        archive_bytes = self._archive_with_markdown_entrypoint()
        monkeypatch.setattr(
            "httpx.post",
            lambda url, *, headers, timeout: _FakeResponse(200, {"token": "artifact-tok"}),
        )
        monkeypatch.setattr(
            "httpx.get", lambda url, *, timeout: _FakeResponse(200, content=archive_bytes)
        )

        out = tmp_path / "out"
        exit_code = main(
            ["export", VALID_MANIFEST["id"], "--token", "tok123", "--out", str(out)]
        )

        assert exit_code == 0
        skillmd_path = out / "SKILL.md"
        assert skillmd_path.is_file()
        content = skillmd_path.read_text()
        assert content.startswith("---\n")
        assert "Summarize the input text." in content
        assert "EXPORTED" in capsys.readouterr().out

    def test_requires_token(self, capsys):
        exit_code = main(["export", VALID_MANIFEST["id"]])

        assert exit_code == 1
        assert "--token" in capsys.readouterr().out

    def test_artifact_token_error_returns_1(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "httpx.post",
            lambda url, *, headers, timeout: _FakeResponse(
                404, {"code": "SKILL_NOT_FOUND", "message": "no such skill"}
            ),
        )

        exit_code = main(["export", "no.such.skill", "--token", "tok123"])

        assert exit_code == 1
        assert "SKILL_NOT_FOUND" in capsys.readouterr().out


class TestCmdImport:
    def _write_skillmd(self, tmp_path):
        manifest = ManifestDocument.model_validate(VALID_MANIFEST)
        skillmd_bytes = manifest_to_skillmd(
            manifest, entrypoint_content=b"# Summarize\n\nSummarize the input text.\n"
        )
        path = tmp_path / "SKILL.md"
        path.write_bytes(skillmd_bytes)
        return path

    def test_writes_a_valid_source_package(self, tmp_path, capsys):
        skillmd_path = self._write_skillmd(tmp_path)
        out = tmp_path / "out"

        exit_code = main(
            [
                "import",
                str(skillmd_path),
                "--id",
                "acme.text.summarizer",
                "--version",
                "1.0.0",
                "--owner-team",
                "platform",
                "--category",
                "nlp",
                "--runtime",
                "python:>=3.10.0,<4.0.0",
                "--out",
                str(out),
            ]
        )

        assert exit_code == 0
        manifest_data = yaml.safe_load((out / "manifest.yaml").read_text())
        manifest = ManifestDocument.model_validate(manifest_data)
        assert manifest.id == "acme.text.summarizer"
        assert manifest.entrypoint == "SKILL.md"
        assert (out / "SKILL.md").read_bytes() == skillmd_path.read_bytes()
        assert "IMPORTED" in capsys.readouterr().out

    def test_accepts_a_directory_containing_skillmd(self, tmp_path):
        self._write_skillmd(tmp_path)
        out = tmp_path / "out"

        exit_code = main(
            [
                "import",
                str(tmp_path),
                "--id",
                "acme.text.summarizer",
                "--version",
                "1.0.0",
                "--owner-team",
                "platform",
                "--category",
                "nlp",
                "--runtime",
                "python:>=3.10.0,<4.0.0",
                "--out",
                str(out),
            ]
        )

        assert exit_code == 0
        assert (out / "manifest.yaml").is_file()

    def test_requires_at_least_one_runtime(self, tmp_path, capsys):
        skillmd_path = self._write_skillmd(tmp_path)

        exit_code = main(
            [
                "import",
                str(skillmd_path),
                "--id",
                "acme.text.summarizer",
                "--version",
                "1.0.0",
                "--owner-team",
                "platform",
                "--category",
                "nlp",
            ]
        )

        assert exit_code == 1
        assert "--runtime" in capsys.readouterr().out

    def test_malformed_skillmd_returns_1(self, tmp_path, capsys):
        path = tmp_path / "SKILL.md"
        path.write_text("not frontmatter at all")

        exit_code = main(
            [
                "import",
                str(path),
                "--id",
                "acme.text.summarizer",
                "--version",
                "1.0.0",
                "--owner-team",
                "platform",
                "--category",
                "nlp",
                "--runtime",
                "python:>=3.10.0,<4.0.0",
            ]
        )

        assert exit_code == 1
        assert "IMPORT FAILED" in capsys.readouterr().out

    def test_the_imported_package_actually_validates(self, tmp_path):
        """End-to-end proof: an imported SKILL.md's output directory must
        pass through the existing jaasctl validate pipeline unchanged."""
        skillmd_path = self._write_skillmd(tmp_path)
        out = tmp_path / "out"
        main(
            [
                "import",
                str(skillmd_path),
                "--id",
                "acme.text.summarizer",
                "--version",
                "1.0.0",
                "--owner-team",
                "platform",
                "--category",
                "nlp",
                "--runtime",
                "python:>=3.10.0,<4.0.0",
                "--out",
                str(out),
            ]
        )

        from tests.fixtures.fake_guardrails_client import FakeGuardrailsClient

        exit_code = main(["validate", str(out)], guardrails_client=FakeGuardrailsClient())

        assert exit_code == 0
