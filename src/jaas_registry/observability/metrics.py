"""Metrics. Design ref: design.md §10.1, implementation-plan.md Phase 6 task 2.

A dedicated CollectorRegistry (not the global default) so multiple `create_app`
instances in the same process — as happens across tests — don't collide by
registering the same metric name twice.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

registry = CollectorRegistry()

request_latency_seconds = Histogram(
    "jaas_request_latency_seconds",
    "Request latency by endpoint and status",
    ["endpoint", "status"],
    registry=registry,
)

request_total = Counter(
    "jaas_request_total",
    "Request count by endpoint and status",
    ["endpoint", "status"],
    registry=registry,
)

index_build_duration_seconds = Histogram(
    "jaas_index_build_duration_seconds",
    "Cold-start index bootstrap duration",
    registry=registry,
)

index_event_apply_lag_seconds = Gauge(
    "jaas_index_event_apply_lag_seconds",
    "Time between an index-update event's publish and its most recent apply",
    registry=registry,
)

authz_denied_total = Counter(
    "jaas_authz_denied_total",
    "Count of requests denied by the authorization layer",
    registry=registry,
)

signature_verification_failures_total = Counter(
    "jaas_signature_verification_failures_total",
    "Count of artifact signature/digest verification failures",
    ["reason"],
    registry=registry,
)


def reset_metrics() -> None:
    """Test-only: zero every metric so assertions don't depend on run order."""
    for collector in (
        request_latency_seconds,
        request_total,
        index_build_duration_seconds,
        index_event_apply_lag_seconds,
        authz_denied_total,
        signature_verification_failures_total,
    ):
        collector.clear()
