import time

from jaas_registry.artifact.tokens import ArtifactTokenIssuer

DIGEST = "sha256:" + "a" * 64
SIGNATURE = "sig"


def test_issue_and_redeem_roundtrip():
    issuer = ArtifactTokenIssuer(ttl_seconds=60)
    issued = issuer.issue(
        blob_key="blobs/sha256/abc", digest=DIGEST, signature=SIGNATURE, signature_kind="dev-rsa"
    )

    redeemed = issuer.redeem(issued.token)
    assert redeemed is not None
    assert redeemed.blob_key == "blobs/sha256/abc"
    assert redeemed.digest == DIGEST
    assert redeemed.signature == SIGNATURE
    assert redeemed.signature_kind == "dev-rsa"


def test_token_is_reusable_within_ttl():
    issuer = ArtifactTokenIssuer(ttl_seconds=60)
    issued = issuer.issue(
        blob_key="blobs/sha256/abc", digest=DIGEST, signature=SIGNATURE, signature_kind="dev-rsa"
    )

    assert issuer.redeem(issued.token) is not None
    assert issuer.redeem(issued.token) is not None  # not single-use


def test_unknown_token_redeems_to_none():
    issuer = ArtifactTokenIssuer(ttl_seconds=60)
    assert issuer.redeem("not-a-real-token") is None


def test_expired_token_redeems_to_none():
    issuer = ArtifactTokenIssuer(ttl_seconds=0)
    issued = issuer.issue(
        blob_key="blobs/sha256/abc", digest=DIGEST, signature=SIGNATURE, signature_kind="dev-rsa"
    )
    time.sleep(0.01)
    assert issuer.redeem(issued.token) is None
