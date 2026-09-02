"""jaasctl search / pull / install — Phase 2.2. Pure HTTP clients of the
backend API, same convention as test_cli_release.py: monkeypatch httpx
rather than standing up a real server."""

from __future__ import annotations

import json

import pytest

from jaas_registry.artifact.packaging import build_normalized_archive
from jaas_registry.cli import main
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


class TestCmdSearch:
    def test_prints_results_and_forwards_query_params(self, capsys, monkeypatch):
        def fake_get(url, *, params, headers, timeout):
            assert url == "http://127.0.0.1:8027/api/v1/skills"
            assert params["query"] == "summarizer"
            assert params["page"] == 1
            assert headers == {"Authorization": "Bearer tok123"}
            return _FakeResponse(
                200,
                {
                    "items": [
                        {
                            "id": "acme.text.summarizer",
                            "version": "1.2.3",
                            "category": "text",
                            "tags": ["nlp"],
                            "visibility": "public",
                            "status": "active",
                        }
                    ],
                    "page": {"total": 1, "nextPageToken": None},
                },
            )

        monkeypatch.setattr("httpx.get", fake_get)

        exit_code = main(["search", "--query", "summarizer", "--token", "tok123"])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "acme.text.summarizer@1.2.3" in out
        assert "1 total" in out

    def test_no_results_prints_a_friendly_message(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "httpx.get",
            lambda url, *, params, headers, timeout: _FakeResponse(
                200, {"items": [], "page": {"total": 0, "nextPageToken": None}}
            ),
        )

        exit_code = main(["search"])

        assert exit_code == 0
        assert "No skills found" in capsys.readouterr().out

    def test_http_error_returns_1(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "httpx.get",
            lambda url, *, params, headers, timeout: _FakeResponse(
                400, {"code": "INVALID_QUERY", "message": "bad query"}
            ),
        )

        exit_code = main(["search"])

        assert exit_code == 1
        assert "INVALID_QUERY" in capsys.readouterr().out


def _fake_archive() -> bytes:
    return build_normalized_archive(
        {
            "manifest.yaml": b"id: acme.text.summarizer\n",
            "schema.json": b"{}",
            "permissions.yaml": b"[]\n",
            "dependencies.yaml": b"[]\n",
        }
    )


class TestCmdPull:
    def test_downloads_and_extracts_files_to_dest(self, tmp_path, capsys, monkeypatch):
        archive_bytes = _fake_archive()

        def fake_post(url, *, headers, timeout):
            assert url == (
                "http://127.0.0.1:8027/api/v1/skills/acme.text.summarizer/"
                "versions/latest/artifact-token"
            )
            assert headers == {"Authorization": "Bearer tok123"}
            return _FakeResponse(200, {"token": "artifact-tok-abc"})

        def fake_get(url, *, timeout):
            assert url == "http://127.0.0.1:8027/api/v1/artifacts/artifact-tok-abc"
            return _FakeResponse(200, content=archive_bytes)

        monkeypatch.setattr("httpx.post", fake_post)
        monkeypatch.setattr("httpx.get", fake_get)

        dest = tmp_path / "out"
        exit_code = main(
            ["pull", "acme.text.summarizer", "--token", "tok123", "--dest", str(dest)]
        )

        assert exit_code == 0
        assert (dest / "manifest.yaml").read_bytes() == b"id: acme.text.summarizer\n"
        assert "PULLED" in capsys.readouterr().out

    def test_requires_token(self, capsys):
        exit_code = main(["pull", "acme.text.summarizer"])

        assert exit_code == 1
        assert "--token" in capsys.readouterr().out

    def test_artifact_token_error_returns_1(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "httpx.post",
            lambda url, *, headers, timeout: _FakeResponse(
                404, {"code": "SKILL_NOT_FOUND", "message": "no such skill"}
            ),
        )

        exit_code = main(["pull", "no.such.skill", "--token", "tok123"])

        assert exit_code == 1
        assert "SKILL_NOT_FOUND" in capsys.readouterr().out


class TestCmdInstall:
    def test_installs_into_dot_claude_skills_directory(self, tmp_path, capsys, monkeypatch):
        archive_bytes = _fake_archive()
        monkeypatch.setattr(
            "httpx.post",
            lambda url, *, headers, timeout: _FakeResponse(200, {"token": "artifact-tok-abc"}),
        )
        monkeypatch.setattr(
            "httpx.get", lambda url, *, timeout: _FakeResponse(200, content=archive_bytes)
        )
        monkeypatch.chdir(tmp_path)

        exit_code = main(["install", "acme.text.summarizer", "--token", "tok123"])

        assert exit_code == 0
        installed = tmp_path / ".claude" / "skills" / "acme.text.summarizer" / "manifest.yaml"
        assert installed.read_bytes() == b"id: acme.text.summarizer\n"
        assert "INSTALLED" in capsys.readouterr().out


class TestAgainstARealApp:
    """The tests above hand-type fake response payloads — this test proves
    those shapes actually match the real routes/schemas, not just my
    assumption about them, by routing httpx.get/post through a real
    FastAPI TestClient instead of a hand-built _FakeResponse."""

    def test_search_pull_and_install_round_trip_a_real_publish(self, tmp_path, capsys, monkeypatch):
        from fastapi.testclient import TestClient

        from jaas_registry.api.app import create_app
        from jaas_registry.artifact.publish import publish_skill
        from jaas_registry.artifact.signing import generate_dev_keypair
        from jaas_registry.artifact.trust import TrustPolicy
        from jaas_registry.common.audit import InMemoryAuditSink
        from jaas_registry.common.config import Settings
        from jaas_registry.index.bootstrap import bootstrap_index
        from jaas_registry.storage.local_filesystem import LocalFilesystemStore
        from tests.fixtures.package_dir import write_package_dir

        store = LocalFilesystemStore(tmp_path / "storage")
        keypair = generate_dev_keypair()
        write_package_dir(tmp_path / "pkg")
        publish_skill(
            source_dir=tmp_path / "pkg",
            store=store,
            signing_key=keypair,
            trust_policy=TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()]),
            actor="ci-pipeline",
            audit_sink=InMemoryAuditSink(),
        )
        index = bootstrap_index(store)
        settings = Settings(storage_root=store.root)
        # No authorizer override -> AllowAllAuthorizer, same default any
        # local/dev create_app() call gets without an explicit JwtAuthorizer.
        app = create_app(index=index, store=store, settings=settings)
        test_client = TestClient(app)

        def fake_get(url, *, params=None, headers=None, timeout=None):
            path = url.removeprefix("http://127.0.0.1:8027")
            return test_client.get(path, params=params, headers=headers)

        def fake_post(url, *, headers=None, timeout=None, json=None):
            path = url.removeprefix("http://127.0.0.1:8027")
            return test_client.post(path, headers=headers, json=json)

        monkeypatch.setattr("httpx.get", fake_get)
        monkeypatch.setattr("httpx.post", fake_post)

        search_exit = main(["search"])
        assert search_exit == 0
        search_out = capsys.readouterr().out
        assert f"{VALID_MANIFEST['id']}@{VALID_MANIFEST['version']}" in search_out

        pull_dest = tmp_path / "pulled"
        pull_exit = main(
            ["pull", VALID_MANIFEST["id"], "--token", "dummy", "--dest", str(pull_dest)]
        )
        assert pull_exit == 0
        assert (pull_dest / "manifest.yaml").is_file()

        monkeypatch.chdir(tmp_path)
        install_exit = main(["install", VALID_MANIFEST["id"], "--token", "dummy"])
        assert install_exit == 0
        installed = tmp_path / ".claude" / "skills" / VALID_MANIFEST["id"] / "manifest.yaml"
        assert installed.is_file()
