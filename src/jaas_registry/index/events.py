"""Index update events and the event stream abstraction.

Design ref: design.md §3.2 design notes 4 & 6 ("every replica subscribes to the
same event stream," "event transport is pluggable"), implementation-plan.md
Phase 5 task 2.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IndexUpdateEvent:
    event_id: str
    skill_id: str
    version: str
    tag_key: str
    published_at: float


class EventBus(Protocol):
    def publish(self, event: IndexUpdateEvent) -> None: ...

    def consume_all(self) -> list[IndexUpdateEvent]:
        """Drain and return all currently pending events."""
        ...


class InMemoryEventBus:
    """Stands in for Kafka/SQS/Pub-Sub (design.md §3.2 note 6). A single shared
    instance models "every replica subscribes to the same stream" for the
    local-first prototype, where there is one process instead of many replicas.
    """

    def __init__(self) -> None:
        self._pending: list[IndexUpdateEvent] = []

    def publish(self, event: IndexUpdateEvent) -> None:
        self._pending.append(event)

    def consume_all(self) -> list[IndexUpdateEvent]:
        events, self._pending = self._pending, []
        return events


def new_index_update_event(
    *, skill_id: str, version: str, tag_key: str, kind: str = "publish"
) -> IndexUpdateEvent:
    """`kind` discriminates event_id by what happened, not just which
    (skill_id, version) it happened to — without it, a publish event and a
    later yank event for the same version would collide on event_id and the
    yank would be silently dropped by IndexEventConsumer's dedup (see
    IMPLEMENTATION_PLAN.md Phase 1.3/2.4)."""
    return IndexUpdateEvent(
        event_id=f"{skill_id}@{version}:{kind}",
        skill_id=skill_id,
        version=version,
        tag_key=tag_key,
        published_at=time.time(),
    )
