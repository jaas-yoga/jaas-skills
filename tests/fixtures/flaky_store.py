"""A storage wrapper that injects transient failures, for chaos testing.

Design ref: design.md §8.2.3 ("Storage transient error: retry with exponential
backoff and jitter").
"""

from __future__ import annotations


class TransientStorageError(Exception):
    pass


class FlakyStore:
    """Wraps a real ObjectStore, failing the first `fail_times` calls to
    `read` with a transient error before delegating normally."""

    def __init__(self, inner, *, fail_times: int = 0):
        self._inner = inner
        self._fail_times = fail_times
        self.read_attempts = 0

    def read(self, key: str) -> bytes:
        self.read_attempts += 1
        if self.read_attempts <= self._fail_times:
            raise TransientStorageError(f"simulated transient failure #{self.read_attempts}")
        return self._inner.read(key)

    def write_blob_if_absent(self, key: str, data: bytes) -> None:
        self._inner.write_blob_if_absent(key, data)

    def write_tag_if_absent(self, key: str, data: bytes) -> None:
        self._inner.write_tag_if_absent(key, data)

    def exists(self, key: str) -> bool:
        return self._inner.exists(key)

    def list_prefix(self, prefix: str) -> list[str]:
        return self._inner.list_prefix(prefix)
