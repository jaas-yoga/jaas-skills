"""Usage-based ranking signal. IMPLEMENTATION_PLAN.md Phase 3.1.

Counts artifact-token issuance (api/routes.py::create_artifact_token) —
the proxy for "someone is about to download this version," already hit by
every real download path (`jaasctl pull`/`install`/`export`, per Phase
2.2's `_download_skill_files`) — per skill_id.

Deliberately NOT the audit log's one-file-append-per-event pattern
(common/audit_store.py): design.md §9.2 documents ~80 RPS average on that
exact endpoint (~6.9M events/day), which a per-event durable write cannot
absorb without real throughput risk. Instead: a cheap in-process counter
(no I/O on the hot download-token-issuance path) periodically flushed as
merged totals into one shared counts file — same "periodic, eventually
consistent, safe by construction" tradeoff index/background_sync.py
already established for multi-replica index sync, applied here because
usage data tolerates staleness far better than index correctness does,
and because a ranking signal being briefly stale or losing a rare
increment under concurrent flushes is an acceptable approximation, unlike
Phase 1.3/3.2's grant/yank data.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
from collections import Counter
from collections.abc import Callable
from pathlib import Path

_COUNTS_FILENAME = "usage_counts.json"

# Diminishing-returns scaling so one viral skill can't dominate ranking
# regardless of query relevance — a starting point, not a data-derived
# constant (no real usage data exists yet to calibrate against).
_SATURATION_COUNT = 1000


class UsageCounter:
    """In-process, per-replica counter. `record()` is O(1) with a lock —
    safe to call on the hot artifact-token-issuance path. `drain()`
    returns accumulated counts since the last drain and resets to zero,
    so repeated flushes (see flush_usage_counts) accumulate correctly
    rather than double-counting."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()

    def record(self, skill_id: str) -> None:
        with self._lock:
            self._counts[skill_id] += 1

    def drain(self) -> dict[str, int]:
        with self._lock:
            drained = dict(self._counts)
            self._counts.clear()
            return drained


def _counts_path(usage_dir: Path) -> Path:
    return usage_dir / _COUNTS_FILENAME


def read_usage_counts(usage_dir: Path) -> dict[str, int]:
    path = _counts_path(usage_dir)
    if not path.is_file():
        return {}
    data: dict[str, int] = json.loads(path.read_text())
    return data


def flush_usage_counts(counter: UsageCounter, usage_dir: Path) -> None:
    """Merges this process's accumulated deltas into the shared durable
    file additively, then resets the in-process counter via drain().
    Read-modify-write, not atomic across concurrently-flushing replicas —
    a rare lost increment under a race is an acceptable approximation for
    a ranking signal, not a security control (contrast artifact/yank.py's
    write_object, which has no such tolerance)."""
    delta = counter.drain()
    if not delta:
        return
    usage_dir.mkdir(parents=True, exist_ok=True)
    current = read_usage_counts(usage_dir)
    for skill_id, count in delta.items():
        current[skill_id] = current.get(skill_id, 0) + count
    _counts_path(usage_dir).write_text(json.dumps(current))


def usage_score(count: int) -> float:
    """Normalizes a raw usage count into roughly [0, 1] with diminishing
    returns (log scaling), so usage acts as a bounded supporting signal
    in index/query.py's ranking rather than one popular skill swamping
    every other weight regardless of query relevance."""
    if count <= 0:
        return 0.0
    return min(1.0, math.log1p(count) / math.log1p(_SATURATION_COUNT))


async def flush_usage_counts_periodically(
    counter: UsageCounter,
    usage_dir: Path,
    *,
    interval_seconds: float,
    stop_event: asyncio.Event,
    on_flush: Callable[[], None] | None = None,
) -> None:
    """Same loop shape as index/background_sync.py::reconcile_periodically
    — checks stop_event before each iteration, so setting it before the
    first tick means flush_usage_counts() never runs at all."""
    while not stop_event.is_set():
        await asyncio.to_thread(flush_usage_counts, counter, usage_dir)
        if on_flush is not None:
            on_flush()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
