"""Thin HTTP client for the JaaS skill registry's public read/download API.

IMPLEMENTATION_PLAN.md Phase 4.1. Wraps exactly the routes jaasctl's own
search/pull/install commands already use (src/jaas_registry/cli.py's
`_download_skill_files`, at the backend repo root) -- replicated here as a
standalone, importable client rather than CLI-entangled code, since that
function prints errors and returns None on failure instead of raising typed
exceptions a caller can handle programmatically.
"""

from __future__ import annotations

import io
import tarfile

import httpx
import yaml

from jaas_client.errors import JaasApiError, JaasAuthError, JaasClientError, JaasNotFoundError
from jaas_client.models import SkillMetadata, SkillSummary

DEFAULT_TIMEOUT_SECONDS = 10.0


def _build_error(response: httpx.Response) -> JaasApiError:
    code: str | None = None
    message = response.text
    details: dict = {}
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        code = body.get("code")
        message = body.get("message", message)
        details = body.get("details", {})

    if response.status_code == 404:
        error_cls = JaasNotFoundError
    elif response.status_code in (401, 403):
        error_cls = JaasAuthError
    else:
        error_cls = JaasApiError
    return error_cls(response.status_code, code, message, details)


def _extract_archive(archive_bytes: bytes) -> dict[str, bytes]:
    """Inverse of jaas_registry.artifact.packaging.build_normalized_archive
    -- a plain stdlib tarfile read, reimplemented here (not imported) to
    keep this client's runtime dependency surface to httpx + pyyaml only."""
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            extracted = tar.extractfile(member)
            if extracted is not None:
                files[member.name] = extracted.read()
    return files


class JaasRegistryClient:
    """A client per registry base URL. Holds one pooled `httpx.Client` for
    its lifetime -- use as a context manager, or call `close()` explicitly."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> JaasRegistryClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise _build_error(response)
        return response

    def search(
        self,
        query: str | None = None,
        *,
        category: str | None = None,
        tags: list[str] | None = None,
        runtime: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[SkillSummary]:
        params: dict[str, str | int] = {"page": page, "pageSize": page_size}
        if query:
            params["query"] = query
        if category:
            params["category"] = category
        if tags:
            params["tags"] = ",".join(tags)
        if runtime:
            params["runtime"] = runtime
        response = self._request("GET", "/api/v1/skills", params=params)
        return [SkillSummary._from_json(item) for item in response.json()["items"]]

    def get_metadata(self, skill_id: str, version: str = "latest") -> SkillMetadata:
        response = self._request("GET", f"/api/v1/skills/{skill_id}/versions/{version}")
        return SkillMetadata._from_json(response.json())

    def pull(self, skill_id: str, version: str = "latest") -> dict[str, bytes]:
        """Fetches the exact files packaged at publish time (manifest.yaml,
        schema.json/permissions.yaml/dependencies.yaml, and the entrypoint
        file if one exists), via the same artifact-token-then-download
        sequence jaasctl pull/install use."""
        token_response = self._request(
            "POST", f"/api/v1/skills/{skill_id}/versions/{version}/artifact-token"
        )
        token = token_response.json()["token"]
        archive_response = self._request("GET", f"/api/v1/artifacts/{token}")
        return _extract_archive(archive_response.content)

    def get_entrypoint_content(self, skill_id: str, version: str = "latest") -> str:
        """Pulls a skill's packaged files and returns its entrypoint file's
        decoded content -- the closest thing to "the skill's instructions"
        for an agent to read, per manifest.yaml's `entrypoint` field."""
        files = self.pull(skill_id, version)
        manifest = yaml.safe_load(files.get("manifest.yaml", b""))
        entrypoint = manifest.get("entrypoint") if isinstance(manifest, dict) else None
        if not entrypoint or entrypoint not in files:
            raise JaasClientError(
                f"skill '{skill_id}@{version}' has no readable entrypoint file"
            )
        return files[entrypoint].decode("utf-8", errors="replace")
