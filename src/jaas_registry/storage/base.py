"""Object storage interface. design.md §1.1.5 and §9.3.2 keep this pluggable — the
same interface later fronts S3/MinIO or an OCI registry; only local_filesystem.py
is prototype-only.
"""

from __future__ import annotations

from typing import Protocol


class ObjectStore(Protocol):
    def write_blob_if_absent(self, key: str, data: bytes) -> None:
        """Content-addressed write: idempotent no-op if `key` already exists,
        since the same key implies the same content (see digest scheme)."""
        ...

    def write_tag_if_absent(self, key: str, data: bytes) -> None:
        """Mutable-name write (an id+version 'tag'): raises JaasError(DUPLICATE_PUBLISH)
        if `key` already exists — this is the immutability enforcement point."""
        ...

    def read(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def list_prefix(self, prefix: str) -> list[str]: ...
