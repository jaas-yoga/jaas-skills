"""IMPLEMENTATION_PLAN.md Phase 4.1: jaas-client is the shared core the
per-framework SDKs (jaas-langgraph/jaas-crewai/jaas-autogen) build on. These
tests use httpx.MockTransport -- no real network, no dependency on the
jaas_registry backend package -- to pin down request/response handling in
isolation. tests/test_client_against_real_api.py (a separate file, gated on
the jaas-registry dev dependency) covers the same client against the real
FastAPI app end-to-end.
"""

from __future__ import annotations

import io
import tarfile

import httpx
import pytest

from jaas_client import JaasRegistryClient
from jaas_client.errors import JaasApiError, JaasAuthError, JaasClientError, JaasNotFoundError

_EMPTY_PAGE = {"items": [], "page": {"total": 0, "nextPageToken": None}}


def _token_response(token: str = "t") -> httpx.Response:
    return httpx.Response(
        200, json={"token": token, "expiresAt": "2026-01-01T00:00:00Z", "ttlSeconds": 60}
    )


def _archive_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _client(handler, *, token: str | None = None) -> JaasRegistryClient:
    transport = httpx.MockTransport(handler)
    return JaasRegistryClient("http://registry.test", token=token, transport=transport)


class TestSearch:
    def test_sends_query_params_and_parses_results(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "acme.text.summarizer",
                            "name": "Summarizer",
                            "version": "1.2.3",
                            "category": "text",
                            "tags": ["nlp", "summarization"],
                            "runtime": ["python"],
                            "digest": "sha256:" + "a" * 64,
                            "score": 1.6,
                            "visibility": "public",
                            "ownerUser": "u1",
                            "ownerTenant": "t1",
                            "status": "active",
                        }
                    ],
                    "page": {"total": 1, "nextPageToken": None},
                },
            )

        with _client(handler, token="tok123") as client:
            results = client.search(query="summarizer", category="text", tags=["nlp"])

        assert "query=summarizer" in seen["url"]
        assert "category=text" in seen["url"]
        assert "tags=nlp" in seen["url"]
        assert seen["headers"]["authorization"] == "Bearer tok123"

        assert len(results) == 1
        assert results[0].id == "acme.text.summarizer"
        assert results[0].name == "Summarizer"
        assert results[0].version == "1.2.3"
        assert results[0].tags == ("nlp", "summarization")
        assert results[0].score == 1.6

    def test_no_query_omits_the_query_param_entirely(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json=_EMPTY_PAGE)

        with _client(handler) as client:
            results = client.search()

        assert "query=" not in seen["url"]
        assert results == []

    def test_no_bearer_header_sent_when_no_token_configured(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = dict(request.headers)
            return httpx.Response(200, json=_EMPTY_PAGE)

        with _client(handler) as client:
            client.search()

        assert "authorization" not in seen["headers"]


class TestGetMetadata:
    def test_returns_typed_metadata(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/skills/acme.text.summarizer/versions/latest"
            return httpx.Response(
                200,
                json={
                    "id": "acme.text.summarizer",
                    "name": "Summarizer",
                    "version": "1.2.3",
                    "description": "Summarizes long documents",
                    "owner": {"team": "platform"},
                    "category": "text",
                    "tags": ["nlp"],
                    "runtime": [{"family": "python", "versionRange": ">=3.10"}],
                    "digest": "sha256:" + "a" * 64,
                    "dependencies": [],
                    "visibility": "public",
                    "ownerUser": "u1",
                    "ownerTenant": "t1",
                    "status": "active",
                },
            )

        with _client(handler) as client:
            metadata = client.get_metadata("acme.text.summarizer")

        assert metadata.id == "acme.text.summarizer"
        assert metadata.version == "1.2.3"
        assert metadata.description == "Summarizes long documents"
        assert metadata.status == "active"

    def test_unknown_skill_raises_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={
                    "code": "SKILL_NOT_FOUND",
                    "message": "skill 'no.such.skill' not found",
                    "details": {},
                },
            )

        with _client(handler) as client:
            with pytest.raises(JaasNotFoundError) as exc_info:
                client.get_metadata("no.such.skill")

        assert exc_info.value.code == "SKILL_NOT_FOUND"
        assert exc_info.value.status_code == 404

    def test_unexpected_error_status_raises_generic_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"code": "INTERNAL", "message": "boom", "details": {}})

        with _client(handler) as client:
            with pytest.raises(JaasApiError) as exc_info:
                client.get_metadata("acme.text.summarizer")

        assert exc_info.value.status_code == 500
        assert not isinstance(exc_info.value, JaasNotFoundError)
        assert not isinstance(exc_info.value, JaasAuthError)


class TestAuthErrors:
    @pytest.mark.parametrize("status", [401, 403])
    def test_401_and_403_both_raise_auth_error(self, status):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status, json={"code": "UNAUTHORIZED", "message": "nope", "details": {}}
            )

        with _client(handler) as client:
            with pytest.raises(JaasAuthError):
                client.get_metadata("acme.text.summarizer")


class TestPull:
    def test_issues_a_token_then_downloads_and_extracts_the_archive(self):
        calls = []
        archive = _archive_bytes(
            {"manifest.yaml": b"id: acme.text.summarizer\n", "SKILL.md": b"# Summarizer\n"}
        )

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            if request.url.path.endswith("/artifact-token"):
                assert request.method == "POST"
                return _token_response("tok-abc")
            if request.url.path == "/api/v1/artifacts/tok-abc":
                return httpx.Response(
                    200, content=archive, headers={"content-type": "application/x-tar"}
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

        with _client(handler, token="tok123") as client:
            files = client.pull("acme.text.summarizer", "1.2.3")

        assert files["manifest.yaml"] == b"id: acme.text.summarizer\n"
        assert files["SKILL.md"] == b"# Summarizer\n"
        token_path = "/api/v1/skills/acme.text.summarizer/versions/1.2.3/artifact-token"
        assert ("POST", token_path) in calls
        assert ("GET", "/api/v1/artifacts/tok-abc") in calls

    def test_defaults_to_the_latest_version(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/artifact-token"):
                assert "/versions/latest/" in request.url.path
                return _token_response()
            return httpx.Response(
                200, content=_archive_bytes({}), headers={"content-type": "application/x-tar"}
            )

        with _client(handler) as client:
            client.pull("acme.text.summarizer")

    def test_no_bearer_token_raises_auth_error_before_download(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/artifact-token")
            return httpx.Response(
                401, json={"code": "UNAUTHORIZED", "message": "missing token", "details": {}}
            )

        with _client(handler) as client:
            with pytest.raises(JaasAuthError):
                client.pull("acme.text.summarizer")


class TestGetEntrypointContent:
    def test_returns_decoded_entrypoint_file_named_in_the_manifest(self):
        archive = _archive_bytes(
            {
                "manifest.yaml": b"id: acme.text.summarizer\nentrypoint: SKILL.md\n",
                "SKILL.md": b"# Summarizer\n\nSummarize the given text.\n",
            }
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/artifact-token"):
                return _token_response()
            return httpx.Response(
                200, content=archive, headers={"content-type": "application/x-tar"}
            )

        with _client(handler) as client:
            content = client.get_entrypoint_content("acme.text.summarizer")

        assert content == "# Summarizer\n\nSummarize the given text.\n"

    def test_manifest_with_no_entrypoint_raises_client_error(self):
        archive = _archive_bytes({"manifest.yaml": b"id: acme.text.summarizer\n"})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/artifact-token"):
                return _token_response()
            return httpx.Response(
                200, content=archive, headers={"content-type": "application/x-tar"}
            )

        with _client(handler) as client:
            with pytest.raises(JaasClientError):
                client.get_entrypoint_content("acme.text.summarizer")
