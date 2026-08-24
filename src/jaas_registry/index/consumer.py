"""Event-driven incremental index updater.

Design ref: design.md §3.2 design note 2, §8.2.3 ("retry with exponential
backoff and jitter"), implementation-plan.md Phase 5 task 2.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from jaas_registry.index.events import EventBus, IndexUpdateEvent
from jaas_registry.index.ingest import parse_published_record
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.observability.metrics import index_event_apply_lag_seconds
from jaas_registry.storage.base import ObjectStore


@dataclass(frozen=True)
class DeadLetterEntry:
    event: IndexUpdateEvent
    error: str
    attempts: int


class IndexEventConsumer:
    """Applies IndexUpdateEvents to the index. Re-applying an already-applied
    event id is a no-op (idempotent apply). A read that keeps failing is
    retried with exponential backoff + jitter up to `max_retries`, then moved
    to `dead_letters` instead of blocking the rest of the stream.
    """

    def __init__(
        self,
        *,
        index: InMemoryIndex,
        store: ObjectStore,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.1,
        backoff_max_seconds: float = 2.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.index = index
        self.store = store
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self._sleep = sleep_fn
        self._applied_event_ids: set[str] = set()
        self.dead_letters: list[DeadLetterEntry] = []
        self.last_applied_at: float | None = None
        self.last_apply_lag_seconds: float | None = None

    def apply(self, event: IndexUpdateEvent) -> None:
        if event.event_id in self._applied_event_ids:
            return

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                entry = parse_published_record(self.store.read(event.tag_key))
                self.index.put(entry)
                self._applied_event_ids.add(event.event_id)
                self.last_applied_at = time.time()
                self.last_apply_lag_seconds = self.last_applied_at - event.published_at
                index_event_apply_lag_seconds.set(self.last_apply_lag_seconds)
                return
            except Exception as exc:  # noqa: BLE001 - any read/parse failure is retryable here
                last_error = exc
                if attempt < self.max_retries:
                    delay = min(
                        self.backoff_base_seconds * (2 ** (attempt - 1)), self.backoff_max_seconds
                    )
                    self._sleep(delay + random.uniform(0, self.backoff_base_seconds))

        self.dead_letters.append(
            DeadLetterEntry(event=event, error=str(last_error), attempts=self.max_retries)
        )

    def consume_from(self, bus: EventBus) -> None:
        for event in bus.consume_all():
            self.apply(event)
