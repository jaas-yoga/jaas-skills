"""Ingest verification: digest comparison, signature verification.

Design ref: design.md §3.3.1 ("Signature verification runs at ingest and can be
rechecked at retrieval for high-assurance mode"), implementation-plan.md Phase 2 task 3.
"""

from __future__ import annotations

from jaas_registry.artifact.packaging import compute_digest
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.observability.metrics import signature_verification_failures_total
from jaas_registry.observability.tracing import annotate_current_span_error


def verify_artifact(
    *, archive_bytes: bytes, digest: str, signature: str, trust_policy: TrustPolicy
) -> None:
    """Raises JaasError(CORRUPT_PAYLOAD) on digest mismatch, or
    JaasError(INVALID_SIGNATURE) if the signature doesn't verify against the
    trust policy. Both checks run every time this is called — at ingest always,
    and again at retrieval when high-assurance mode is enabled. Every failure
    increments signature_verification_failures_total and annotates the current
    trace span as a policy outcome (design.md §10.1.5, §10.3.2).
    """
    if compute_digest(archive_bytes) != digest:
        exc = JaasError(
            ErrorCode.CORRUPT_PAYLOAD, "recomputed digest does not match manifest digest"
        )
        signature_verification_failures_total.labels(reason=exc.code.value).inc()
        annotate_current_span_error(exc)
        raise exc
    if not trust_policy.verify(digest, signature):
        exc = JaasError(
            ErrorCode.INVALID_SIGNATURE, "signature does not verify against the trust policy"
        )
        signature_verification_failures_total.labels(reason=exc.code.value).inc()
        annotate_current_span_error(exc)
        raise exc
