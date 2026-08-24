"""Security test suite: signature/trust-chain attack scenarios.

implementation-plan.md Phase 7 task 4. Covers design.md §7.1's trust chain:
CI signs with a private key, the registry verifies only against configured
trusted public keys — never by asking the signer to vouch for itself.
"""

import pytest

from rune_registry.artifact.packaging import compute_digest as _digest_of
from rune_registry.artifact.signing import generate_dev_keypair, sign_digest
from rune_registry.artifact.trust import TrustPolicy
from rune_registry.artifact.verify import verify_artifact
from rune_registry.common.errors import ErrorCode, RuneError

ARCHIVE = b"pretend-this-is-a-tar-archive"


def test_attacker_self_signed_key_is_never_trusted():
    """An attacker who controls their own keypair and re-signs a tampered
    artifact must not verify, because their public key was never registered."""
    legit_keypair = generate_dev_keypair()
    attacker_keypair = generate_dev_keypair()

    digest = _digest_of(ARCHIVE)
    attacker_signature = sign_digest(digest, attacker_keypair)

    trust_policy = TrustPolicy(trusted_public_keys_pem=[legit_keypair.public_key_pem()])
    with pytest.raises(RuneError) as exc_info:
        verify_artifact(
            archive_bytes=ARCHIVE,
            digest=digest,
            signature=attacker_signature,
            trust_policy=trust_policy,
        )
    assert exc_info.value.code == ErrorCode.INVALID_SIGNATURE


def test_key_rotation_both_old_and_new_keys_verify_during_overlap():
    """During a rotation window, a trust policy naturally holds two keys; an
    artifact signed by either must still verify."""
    old_keypair = generate_dev_keypair()
    new_keypair = generate_dev_keypair()
    trust_policy = TrustPolicy(
        trusted_public_keys_pem=[old_keypair.public_key_pem(), new_keypair.public_key_pem()]
    )

    digest = _digest_of(ARCHIVE)
    for keypair in (old_keypair, new_keypair):
        signature = sign_digest(digest, keypair)
        verify_artifact(
            archive_bytes=ARCHIVE, digest=digest, signature=signature, trust_policy=trust_policy
        )  # must not raise


def test_key_revocation_old_signature_stops_verifying_once_key_removed():
    """After rotation completes and the old key is dropped from the trust
    policy, artifacts signed only by that old key must stop verifying."""
    old_keypair = generate_dev_keypair()
    new_keypair = generate_dev_keypair()
    digest = _digest_of(ARCHIVE)
    old_signature = sign_digest(digest, old_keypair)

    post_rotation_policy = TrustPolicy(trusted_public_keys_pem=[new_keypair.public_key_pem()])
    with pytest.raises(RuneError) as exc_info:
        verify_artifact(
            archive_bytes=ARCHIVE,
            digest=digest,
            signature=old_signature,
            trust_policy=post_rotation_policy,
        )
    assert exc_info.value.code == ErrorCode.INVALID_SIGNATURE


def test_signature_from_one_artifact_replayed_against_another_is_rejected():
    """A valid (digest, signature) pair for artifact A must not verify against
    a different artifact B's bytes, even with the correct trust policy."""
    keypair = generate_dev_keypair()
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])

    artifact_a = b"artifact-a-bytes"
    artifact_b = b"artifact-b-bytes-completely-different"
    digest_a = _digest_of(artifact_a)
    signature_a = sign_digest(digest_a, keypair)

    with pytest.raises(RuneError) as exc_info:
        verify_artifact(
            archive_bytes=artifact_b,
            digest=digest_a,
            signature=signature_a,
            trust_policy=trust_policy,
        )
    assert exc_info.value.code == ErrorCode.CORRUPT_PAYLOAD


def test_empty_trust_policy_rejects_even_a_correctly_signed_artifact():
    """Fail-closed: if the trust policy has no configured keys (e.g. a
    misconfigured deployment), nothing verifies — never fail open."""
    keypair = generate_dev_keypair()
    digest = _digest_of(ARCHIVE)
    signature = sign_digest(digest, keypair)

    empty_policy = TrustPolicy(trusted_public_keys_pem=[])
    with pytest.raises(RuneError) as exc_info:
        verify_artifact(
            archive_bytes=ARCHIVE, digest=digest, signature=signature, trust_policy=empty_policy
        )
    assert exc_info.value.code == ErrorCode.INVALID_SIGNATURE


@pytest.mark.parametrize(
    "malformed_signature",
    ["", "not-base64!!!", "🎉🎉🎉", "a" * 100_000],
)
def test_malformed_signature_values_are_rejected_not_crashed(malformed_signature):
    keypair = generate_dev_keypair()
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    digest = _digest_of(ARCHIVE)

    with pytest.raises(RuneError) as exc_info:
        verify_artifact(
            archive_bytes=ARCHIVE,
            digest=digest,
            signature=malformed_signature,
            trust_policy=trust_policy,
        )
    assert exc_info.value.code == ErrorCode.INVALID_SIGNATURE


def test_corrupted_bit_flip_in_archive_is_detected():
    """A single flipped bit anywhere in the archive must break the digest
    match — this is what protects against bit rot and partial tampering."""
    keypair = generate_dev_keypair()
    digest = _digest_of(ARCHIVE)
    signature = sign_digest(digest, keypair)
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])

    corrupted = bytearray(ARCHIVE)
    corrupted[0] ^= 0b00000001
    with pytest.raises(RuneError) as exc_info:
        verify_artifact(
            archive_bytes=bytes(corrupted),
            digest=digest,
            signature=signature,
            trust_policy=trust_policy,
        )
    assert exc_info.value.code == ErrorCode.CORRUPT_PAYLOAD
