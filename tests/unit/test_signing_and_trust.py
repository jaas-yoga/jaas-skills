from rune_registry.artifact.signing import generate_dev_keypair, load_or_create_keypair, sign_digest
from rune_registry.artifact.trust import TrustPolicy, ensure_key_registered, load_trust_policy


def test_signature_verifies_against_matching_public_key():
    keypair = generate_dev_keypair()
    digest = "sha256:" + "a" * 64
    signature = sign_digest(digest, keypair)

    policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    assert policy.verify(digest, signature) is True


def test_signature_rejected_by_untrusted_key():
    signer_keypair = generate_dev_keypair()
    other_keypair = generate_dev_keypair()
    digest = "sha256:" + "a" * 64
    signature = sign_digest(digest, signer_keypair)

    policy = TrustPolicy(trusted_public_keys_pem=[other_keypair.public_key_pem()])
    assert policy.verify(digest, signature) is False


def test_signature_rejected_if_digest_tampered_after_signing():
    keypair = generate_dev_keypair()
    original_digest = "sha256:" + "a" * 64
    tampered_digest = "sha256:" + "b" * 64
    signature = sign_digest(original_digest, keypair)

    policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    assert policy.verify(tampered_digest, signature) is False


def test_empty_trust_policy_rejects_everything():
    keypair = generate_dev_keypair()
    digest = "sha256:" + "a" * 64
    signature = sign_digest(digest, keypair)

    policy = TrustPolicy(trusted_public_keys_pem=[])
    assert policy.verify(digest, signature) is False


def test_malformed_signature_does_not_raise():
    keypair = generate_dev_keypair()
    policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    assert policy.verify("sha256:" + "a" * 64, "not-valid-base64!!!") is False


def test_load_trust_policy_reads_pem_files_from_policy_dir(tmp_path):
    keypair = generate_dev_keypair()
    keys_dir = tmp_path / "trusted_keys"
    keys_dir.mkdir()
    (keys_dir / "ci.pem").write_bytes(keypair.public_key_pem())

    policy = load_trust_policy(tmp_path)

    digest = "sha256:" + "a" * 64
    signature = sign_digest(digest, keypair)
    assert policy.verify(digest, signature) is True


def test_load_trust_policy_missing_dir_yields_empty_policy(tmp_path):
    policy = load_trust_policy(tmp_path / "does-not-exist")
    assert policy.trusted_public_keys_pem == []


def test_load_or_create_keypair_persists_across_calls(tmp_path):
    key_path = tmp_path / "signing_key.pem"
    first = load_or_create_keypair(key_path)
    second = load_or_create_keypair(key_path)
    assert first.public_key_pem() == second.public_key_pem()


def test_load_or_create_keypair_signature_verifies_after_reload(tmp_path):
    key_path = tmp_path / "signing_key.pem"
    original = load_or_create_keypair(key_path)
    reloaded = load_or_create_keypair(key_path)

    digest = "sha256:" + "a" * 64
    signature = sign_digest(digest, original)
    policy = TrustPolicy(trusted_public_keys_pem=[reloaded.public_key_pem()])
    assert policy.verify(digest, signature) is True


def test_ensure_key_registered_is_idempotent(tmp_path):
    keypair = generate_dev_keypair()
    ensure_key_registered(tmp_path, keypair.public_key_pem(), name="ci")
    ensure_key_registered(tmp_path, keypair.public_key_pem(), name="ci")  # no raise, no dup

    policy = load_trust_policy(tmp_path)
    assert policy.trusted_public_keys_pem == [keypair.public_key_pem()]
