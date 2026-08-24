"""Alert evaluation. Design ref: implementation-plan.md Phase 6 task 4
(error rate spikes, index lag threshold breach, signature verification anomaly).

This evaluates the metrics in metrics.py against configurable thresholds and
returns which alerts are currently firing. Wiring the result to a real paging
channel (Slack/PagerDuty/Alertmanager) is outside a local prototype's reach —
this is the evaluation logic a production deployment's rules would run.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import Counter, Gauge

from rune_registry.observability import metrics as m


@dataclass(frozen=True)
class Alert:
    name: str
    severity: str
    message: str


def _counter_total(counter: Counter) -> float:
    total = 0.0
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total"):
                total += sample.value
    return total


def _gauge_value(gauge: Gauge) -> float:
    return gauge._value.get()  # noqa: SLF001 - metrics.py only declares unlabeled gauges


def evaluate_error_rate_spike(*, threshold: float = 0.1) -> Alert | None:
    """Fires when the share of 5xx responses across all requests exceeds `threshold`."""
    total = 0.0
    errors = 0.0
    for metric in m.request_total.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            total += sample.value
            if sample.labels.get("status", "").startswith("5"):
                errors += sample.value
    if total == 0:
        return None
    error_rate = errors / total
    if error_rate > threshold:
        return Alert(
            name="error_rate_spike",
            severity="critical",
            message=f"5xx error rate {error_rate:.1%} exceeds threshold {threshold:.1%}",
        )
    return None


def evaluate_index_lag_breach(*, threshold_seconds: float = 30.0) -> Alert | None:
    """Fires when the most recently observed index-event apply lag exceeds `threshold_seconds`."""
    lag = _gauge_value(m.index_event_apply_lag_seconds)
    if lag > threshold_seconds:
        return Alert(
            name="index_lag_breach",
            severity="warning",
            message=f"index event apply lag {lag:.1f}s exceeds threshold {threshold_seconds:.1f}s",
        )
    return None


def evaluate_signature_verification_anomaly(*, threshold: int = 1) -> Alert | None:
    """Fires when any signature/digest verification failures have been observed."""
    failures = _counter_total(m.signature_verification_failures_total)
    if failures >= threshold:
        return Alert(
            name="signature_verification_anomaly",
            severity="critical",
            message=f"{int(failures)} signature verification failure(s) observed",
        )
    return None


def evaluate_all(
    *,
    error_rate_threshold: float = 0.1,
    index_lag_threshold_seconds: float = 30.0,
    signature_failure_threshold: int = 1,
) -> list[Alert]:
    checks = (
        evaluate_error_rate_spike(threshold=error_rate_threshold),
        evaluate_index_lag_breach(threshold_seconds=index_lag_threshold_seconds),
        evaluate_signature_verification_anomaly(threshold=signature_failure_threshold),
    )
    return [alert for alert in checks if alert is not None]
