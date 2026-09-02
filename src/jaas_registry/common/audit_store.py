"""Durable, queryable audit persistence. IMPLEMENTATION_PLAN.md Phase 3.3.

`StructuredLogAuditSink` (common/audit.py) only ever printed each event as
JSON to stdout — real, but write-only: nothing durable, nothing queryable,
so an "audit export" feature had no data to actually export. `FileAuditSink`
is a drop-in `AuditSink` replacement that does both: prints the same JSON
shape (nothing that tails process logs today loses that output) *and*
appends it as one line to an append-only JSONL file under a new
`Settings.audit_dir`, following this repo's existing file-backed,
no-database persistence convention (`storage_root`/`policy_dir`).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from jaas_registry.common.audit import (
    CustomGuardrailRuleAuditEvent,
    GitHubConnectionAuditEvent,
    PublishAuditEvent,
    ShareGrantAuditEvent,
    YankAuditEvent,
)

_LOG_FILENAME = "audit.jsonl"

_AuditEvent = (
    PublishAuditEvent
    | CustomGuardrailRuleAuditEvent
    | GitHubConnectionAuditEvent
    | YankAuditEvent
    | ShareGrantAuditEvent
)


class FileAuditSink:
    def __init__(self, audit_dir: Path) -> None:
        self._dir = audit_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / _LOG_FILENAME

    def _append(self, event_type: str, event: _AuditEvent) -> None:
        record = {"event_type": event_type, **asdict(event)}
        line = json.dumps(record)
        print(line)
        with self._path.open("a") as f:
            f.write(line + "\n")

    def emit(self, event: PublishAuditEvent) -> None:
        self._append("publish", event)

    def emit_custom_guardrail_change(self, event: CustomGuardrailRuleAuditEvent) -> None:
        self._append("custom_guardrail_change", event)

    def emit_github_connection_change(self, event: GitHubConnectionAuditEvent) -> None:
        self._append("github_connection_change", event)

    def emit_yank(self, event: YankAuditEvent) -> None:
        self._append("yank", event)

    def emit_share_grant_change(self, event: ShareGrantAuditEvent) -> None:
        self._append("share_grant_change", event)

    def read_all(self) -> list[dict]:
        """Every persisted event, oldest first, as the same
        {"event_type": ..., **fields} dicts each line was written with. No
        pagination/filtering here — kept intentionally dumb; the export
        route (api/tenant_routes.py) does its own tenant-scoping filter on
        top of this, since not every event type carries a tenant_id."""
        if not self._path.is_file():
            return []
        return [json.loads(line) for line in self._path.read_text().splitlines() if line]
