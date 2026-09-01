"""Local filesystem object store — stands in for S3/MinIO or an OCI registry
(design.md §2, "Object Storage / OCI Source") for the local-first prototype.

Uses O_EXCL ("xb") exclusive creation so the immutability check is atomic and
race-free, matching the "S3 conditional write or OCI immutable tag strategy"
called for in implementation-plan.md Phase 2 task 4.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from opentelemetry.trace import Tracer

from jaas_registry.common.errors import ErrorCode, JaasError


class LocalFilesystemStore:
    def __init__(self, root: Path, *, tracer: Tracer | None = None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._tracer = tracer

    def _span(self, name: str):
        """design.md §10.3: trace storage calls. No-op context manager when no
        tracer is configured, so instrumentation is opt-in, not a hard dependency."""
        if self._tracer is None:
            return nullcontext()
        return self._tracer.start_as_current_span(name)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f"key '{key}' escapes storage root")
        return path

    def write_blob_if_absent(self, key: str, data: bytes) -> None:
        with self._span("storage.write_blob_if_absent"):
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(path, "xb") as f:
                    f.write(data)
            except FileExistsError:
                pass

    def write_tag_if_absent(self, key: str, data: bytes) -> None:
        with self._span("storage.write_tag_if_absent"):
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(path, "xb") as f:
                    f.write(data)
            except FileExistsError as exc:
                raise JaasError(
                    ErrorCode.DUPLICATE_PUBLISH, f"'{key}' has already been published"
                ) from exc

    def write_object(self, key: str, data: bytes) -> None:
        with self._span("storage.write_object"):
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-temp-then-rename: os.replace is atomic on the same
            # filesystem, so a reader never observes a partial write, unlike
            # writing `path` directly.
            tmp_path = path.with_name(path.name + ".tmp")
            tmp_path.write_bytes(data)
            tmp_path.replace(path)

    def read(self, key: str) -> bytes:
        with self._span("storage.read"):
            return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        with self._span("storage.exists"):
            return self._path(key).exists()

    def list_prefix(self, prefix: str) -> list[str]:
        with self._span("storage.list_prefix"):
            base = self._path(prefix)
            if not base.exists():
                return []
            return sorted(
                str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file()
            )
