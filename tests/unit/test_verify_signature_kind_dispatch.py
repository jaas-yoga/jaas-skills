"""verify_artifact()'s signature_kind dispatch (IMPLEMENTATION_PLAN.md Phase
1.2). Uses a minimal fake trust policy (matching TrustPolicy/
SigstoreTrustPolicy's shared `.verify(digest, signature) -> bool` shape)
rather than a real SigstoreTrustPolicy, to test the dispatch logic itself in
isolation from real Sigstore cryptography — see test_artifact_sigstore.py
for that boundary."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from jaas_registry.artifact.packaging import compute_digest
from jaas_registry.artifact.signing import generate_dev_keypair, sign_digest
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.artifact.verify import verify_artifact
from jaas_registry.common.errors import ErrorCode, JaasError

ARCHIVE = b"pretend-this-is-a-tar-archive"


@dataclass
class _FakeTrustPolicy:
    result: bool

    def verify(self, digest: str, signature: str) -> bool:
        return self.result


def test_dev_rsa_kind_is_the_default_and_ignores_sigstore_policy():
    """Every pre-existing call site omits signature_kind entirely —
    behavior must be identical to before this feature existed."""
    keypair = generate_dev_keypair()
    digest = compute_digest(ARCHIVE)
    signature = sign_digest(digest, keypair)
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])

    verify_artifact(
        archive_bytes=ARCHIVE,
        digest=digest,
        signature=signature,
        trust_policy=trust_policy,
        sigstore_trust_policy=_FakeTrustPolicy(result=False),  # must be ignored for this kind
    )  # must not raise


def test_sigstore_kind_succeeds_when_the_policy_approves():
    digest = compute_digest(ARCHIVE)
    verify_artifact(
        archive_bytes=ARCHIVE,
        digest=digest,
        signature="a-sigstore-bundle-as-json",
        signature_kind="sigstore",
        trust_policy=TrustPolicy(trusted_public_keys_pem=[]),  # must be ignored for this kind
        sigstore_trust_policy=_FakeTrustPolicy(result=True),
    )  # must not raise


def test_sigstore_kind_raises_invalid_signature_when_the_policy_rejects():
    digest = compute_digest(ARCHIVE)
    with pytest.raises(JaasError) as exc_info:
        verify_artifact(
            archive_bytes=ARCHIVE,
            digest=digest,
            signature="a-sigstore-bundle-as-json",
            signature_kind="sigstore",
            trust_policy=None,
            sigstore_trust_policy=_FakeTrustPolicy(result=False),
        )
    assert exc_info.value.code == ErrorCode.INVALID_SIGNATURE


def test_sigstore_kind_with_no_policy_configured_fails_closed():
    """A deployment that hasn't wired up Sigstore verification must reject
    a sigstore-kind signature outright, never silently accept it."""
    digest = compute_digest(ARCHIVE)
    with pytest.raises(JaasError) as exc_info:
        verify_artifact(
            archive_bytes=ARCHIVE,
            digest=digest,
            signature="a-sigstore-bundle-as-json",
            signature_kind="sigstore",
            trust_policy=None,
            sigstore_trust_policy=None,
        )
    assert exc_info.value.code == ErrorCode.INVALID_SIGNATURE


def test_digest_mismatch_is_checked_before_either_dispatch_branch():
    """CORRUPT_PAYLOAD, not INVALID_SIGNATURE, regardless of signature_kind
    — tampering with the archive is a different failure mode than a bad
    signature, and callers (e.g. the UI) distinguish the two."""
    real_digest = compute_digest(ARCHIVE)
    wrong_digest = "sha256:" + "0" * 64
    with pytest.raises(JaasError) as exc_info:
        verify_artifact(
            archive_bytes=ARCHIVE,
            digest=wrong_digest,
            signature="whatever",
            signature_kind="sigstore",
            trust_policy=None,
            sigstore_trust_policy=_FakeTrustPolicy(result=True),
        )
    assert exc_info.value.code == ErrorCode.CORRUPT_PAYLOAD
    assert real_digest != wrong_digest
