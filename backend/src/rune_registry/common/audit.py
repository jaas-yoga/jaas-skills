"""Audit events. Design ref: design.md §7.3, §10.2.

"Tamper-evident logs in a centralized observability platform" (§7.3.3) is a
production concern out of scope for the local prototype; StructuredLogAuditSink
emits the same JSON shape that platform would ingest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class PublishAuditEvent:
    actor: str
    skill_id: str
    version: str
    digest: str
    timestamp: str
    # design.md §4.5/§7.3: non-blocking guardrail checks that fired, even
    # though they didn't stop the publish — lets a tenant audit warning
    # trends from the log alone, without a separate scan-result store.
    guardrail_warning_ids: tuple[str, ...] = ()
    # Populated only on a git-native release (api/release_routes.py) — a
    # web-UI or local `runectl publish` release leaves all four None,
    # which is itself meaningful provenance ("not traceable to a CI run").
    source_repo: str | None = None
    source_commit: str | None = None
    source_tag: str | None = None
    source_branch: str | None = None
    ci_run_url: str | None = None


def new_publish_event(
    *,
    actor: str,
    skill_id: str,
    version: str,
    digest: str,
    guardrail_warning_ids: tuple[str, ...] = (),
    source_repo: str | None = None,
    source_commit: str | None = None,
    source_tag: str | None = None,
    source_branch: str | None = None,
    ci_run_url: str | None = None,
) -> PublishAuditEvent:
    return PublishAuditEvent(
        actor=actor,
        skill_id=skill_id,
        version=version,
        digest=digest,
        timestamp=datetime.now(UTC).isoformat(),
        guardrail_warning_ids=guardrail_warning_ids,
        source_repo=source_repo,
        source_commit=source_commit,
        source_tag=source_tag,
        source_branch=source_branch,
        ci_run_url=ci_run_url,
    )


@dataclass(frozen=True)
class CustomGuardrailRuleAuditEvent:
    """Who changed a tenant's custom guardrail rule library, and how —
    these rules execute against every future publish they're applied to,
    so unlike most tenant settings this needs the same kind of audit trail
    a publish gets, not just the store's own overwrite."""

    actor: str
    tenant_id: str
    rule_id: str
    action: str  # "created" | "updated" | "deleted"
    timestamp: str


def new_custom_guardrail_rule_event(
    *, actor: str, tenant_id: str, rule_id: str, action: str
) -> CustomGuardrailRuleAuditEvent:
    return CustomGuardrailRuleAuditEvent(
        actor=actor,
        tenant_id=tenant_id,
        rule_id=rule_id,
        action=action,
        timestamp=datetime.now(UTC).isoformat(),
    )


@dataclass(frozen=True)
class GitHubConnectionAuditEvent:
    """Connecting/disconnecting GitHub grants or revokes this app's ability
    to browse a tenant's repos/branches — a security-relevant tenant
    setting change, same audit posture as a custom guardrail rule edit."""

    actor: str
    tenant_id: str
    github_login: str | None
    action: str  # "connected" | "disconnected"
    timestamp: str


def new_github_connection_event(
    *, actor: str, tenant_id: str, github_login: str | None, action: str
) -> GitHubConnectionAuditEvent:
    return GitHubConnectionAuditEvent(
        actor=actor,
        tenant_id=tenant_id,
        github_login=github_login,
        action=action,
        timestamp=datetime.now(UTC).isoformat(),
    )


class AuditSink(Protocol):
    def emit(self, event: PublishAuditEvent) -> None: ...

    def emit_custom_guardrail_change(self, event: CustomGuardrailRuleAuditEvent) -> None: ...

    def emit_github_connection_change(self, event: GitHubConnectionAuditEvent) -> None: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[PublishAuditEvent] = []
        self.custom_guardrail_events: list[CustomGuardrailRuleAuditEvent] = []
        self.github_connection_events: list[GitHubConnectionAuditEvent] = []

    def emit(self, event: PublishAuditEvent) -> None:
        self.events.append(event)

    def emit_custom_guardrail_change(self, event: CustomGuardrailRuleAuditEvent) -> None:
        self.custom_guardrail_events.append(event)

    def emit_github_connection_change(self, event: GitHubConnectionAuditEvent) -> None:
        self.github_connection_events.append(event)


class StructuredLogAuditSink:
    def emit(self, event: PublishAuditEvent) -> None:
        print(json.dumps({"event_type": "publish", **asdict(event)}))

    def emit_custom_guardrail_change(self, event: CustomGuardrailRuleAuditEvent) -> None:
        print(json.dumps({"event_type": "custom_guardrail_change", **asdict(event)}))

    def emit_github_connection_change(self, event: GitHubConnectionAuditEvent) -> None:
        print(json.dumps({"event_type": "github_connection_change", **asdict(event)}))
