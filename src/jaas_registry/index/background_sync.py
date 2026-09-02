"""Periodic reconciliation loop: the real production mechanism for keeping a
multi-replica deployment's in-memory indexes in sync with each other.

IMPLEMENTATION_PLAN.md Phase 2.4 originally scoped this as "wire the
existing event-bus consumer into create_app()." Investigating that turned
up a design problem: index/events.py's InMemoryEventBus is an in-process
Python list (its own docstring calls it a stand-in for Kafka/SQS/Pub-Sub) —
it cannot carry events across separate OS processes at all, which is what
"replica" means for a horizontally-scaled deployment. Wiring it into
create_app() would only ever synchronize async tasks within one process,
never actually solving the stated multi-replica problem.

index/reconciliation.py's reconcile() already solves this correctly: it
rebuilds an authoritative view straight from the shared object store
(including re-reading each entry's yank-status sidecar), so it's
process-safe by construction — no shared memory or message transport
needed. This module just runs that on a timer as a FastAPI background task.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from jaas_registry.index.reconciliation import ReconciliationReport, reconcile
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.base import ObjectStore


async def reconcile_periodically(
    index: InMemoryIndex,
    store: ObjectStore,
    *,
    interval_seconds: float,
    stop_event: asyncio.Event,
    on_report: Callable[[ReconciliationReport], None] | None = None,
) -> None:
    """Runs reconcile() (synchronous, blocking storage I/O) in a worker
    thread on a fixed interval until stop_event is set. Checks stop_event
    before each iteration, so setting it before the first tick means
    reconcile() never runs at all."""
    while not stop_event.is_set():
        report = await asyncio.to_thread(reconcile, index, store)
        if on_report is not None:
            on_report(report)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
