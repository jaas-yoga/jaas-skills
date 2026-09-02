"""Ingest verification: digest comparison, signature verification.

Design ref: design.md §3.3.1 ("Signature verification runs at ingest and can be
rechecked at retrieval for high-assurance mode"), implementation-plan.md Phase 2 task 3.
"""

from __future__ import annotations

from jaas_registry.artifact.packaging import compute_digest
from jaas_registry.artifact.sigstore_trust import SigstoreTrustPolicy
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.observability.metrics import signature_verification_failures_total
from jaas_registry.observability.tracing import annotate_current_span_error


def verify_artifact(
    *,
    archive_bytes: bytes,
    digest: str,
    signature: str,
    signature_kind: str = "dev-rsa",
    trust_policy: TrustPolicy | None = None,
    sigstore_trust_policy: SigstoreTrustPolicy | None = None,
) -> None:
    """Raises JaasError(CORRUPT_PAYLOAD) on digest mismatch, or
    JaasError(INVALID_SIGNATURE) if the signature doesn't verify against the
    relevant trust policy for `signature_kind`. Both checks run every time
    this is called — at ingest always, and again at retrieval when
    high-assurance mode is enabled. Every failure increments
    signature_verification_failures_total and annotates the current trace
    span as a policy outcome (design.md §10.1.5, §10.3.2).

    `signature_kind` defaults to "dev-rsa" and every call site that predates
    Sigstore support omits it entirely — this dispatch is purely additive,
    zero behavior change for any existing caller. A "sigstore" kind with no
    sigstore_trust_policy configured fails closed (INVALID_SIGNATURE), same
    as an empty-keys dev-rsa TrustPolicy does today.
    """
    if compute_digest(archive_bytes) != digest:
        exc = JaasError(
            ErrorCode.CORRUPT_PAYLOAD, "recomputed digest does not match manifest digest"
        )
        signature_verification_failures_total.labels(reason=exc.code.value).inc()
        annotate_current_span_error(exc)
        raise exc

    if signature_kind == "sigstore":
        verified = sigstore_trust_policy is not None and sigstore_trust_policy.verify(
            digest, signature
        )
    else:
        verified = trust_policy is not None and trust_policy.verify(digest, signature)

    if not verified:
        exc = JaasError(
            ErrorCode.INVALID_SIGNATURE, "signature does not verify against the trust policy"
        )
        signature_verification_failures_total.labels(reason=exc.code.value).inc()
        annotate_current_span_error(exc)
        raise exc
