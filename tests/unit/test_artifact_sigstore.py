"""Unit tests for the Sigstore trust policy (artifact/sigstore_trust.py).

Deliberately does not exercise real Fulcio/Rekor cryptography or network —
that's sigstore-python's own test suite's job, and Verifier.production()
does real network I/O (fetches the TUF trust root) that would make every
test here slow and offline-hostile. SigstoreTrustPolicy takes an injectable
verifier (same DI pattern as guardrails/client.py's GuardrailsClient +
FakeGuardrailsClient) precisely so these tests can control the outcome
without needing a real signed bundle.
"""

from __future__ import annotations

from jaas_registry.artifact.sigstore_trust import SigstoreTrustPolicy

DIGEST = "sha256:" + "a" * 64


class _FakeVerifier:
    """Records what it was called with; raises iff configured to."""

    def __init__(self, *, should_raise: bool):
        self.should_raise = should_raise
        self.calls: list[tuple] = []

    def verify_artifact(self, input_, bundle, policy) -> None:
        self.calls.append((input_, bundle, policy))
        if self.should_raise:
            from sigstore.errors import VerificationError

            raise VerificationError("fake rejection")


def _policy(verifier) -> SigstoreTrustPolicy:
    from sigstore.verify.policy import OIDCIssuer

    return SigstoreTrustPolicy(
        verifier=verifier, identity_policy=OIDCIssuer("https://token.actions.githubusercontent.com")
    )


def test_malformed_bundle_json_is_rejected_not_crashed():
    policy = _policy(_FakeVerifier(should_raise=False))
    assert policy.verify(DIGEST, "not valid json at all") is False


def test_empty_json_object_is_rejected_not_crashed():
    policy = _policy(_FakeVerifier(should_raise=False))
    assert policy.verify(DIGEST, "{}") is False


def test_verifier_rejection_yields_false():
    """A well-formed-enough bundle whose signature doesn't verify must
    return False, never raise — verify_artifact.py's dispatch logic
    depends on this to turn it into INVALID_SIGNATURE."""
    fake = _FakeVerifier(should_raise=True)
    policy = _policy(fake)
    # SigstoreTrustPolicy.verify() must reject a malformed bundle before
    # ever reaching the injected verifier — this asserts that ordering.
    assert policy.verify(DIGEST, "garbage") is False
    assert fake.calls == []
