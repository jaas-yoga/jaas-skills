"""Artifact signing.

Design ref: design.md §7.1 ("Signature produced through Cosign/Sigstore").

This module is a **local-dev stand-in**, not production signing: it uses an
RSA keypair generated in-process instead of a transparency-log-backed
Sigstore/Cosign trust chain. Swap this for a real `cosign sign`/`cosign verify`
integration (or Sigstore's Python client) before this touches real CI — the
call sites (publish.py, verify.py) only depend on the digest-in/signature-out
shape, not on this implementation.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_PADDING = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH)


@dataclass(frozen=True)
class DevKeypair:
    private_key: rsa.RSAPrivateKey
    public_key: rsa.RSAPublicKey

    def public_key_pem(self) -> bytes:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )


def generate_dev_keypair() -> DevKeypair:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return DevKeypair(private_key=private_key, public_key=private_key.public_key())


def sign_digest(digest: str, keypair: DevKeypair) -> str:
    signature = keypair.private_key.sign(digest.encode(), _PADDING, hashes.SHA256())
    return base64.b64encode(signature).decode()


def load_or_create_keypair(path: Path) -> DevKeypair:
    """Persists the dev signing key across process runs (e.g. separate `jaasctl
    publish` and `jaasctl serve` invocations) so signatures verify consistently.
    Unencrypted PEM on local disk — fine for the dev stand-in, not for prod.
    """
    if path.exists():
        private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        return DevKeypair(private_key=private_key, public_key=private_key.public_key())

    keypair = generate_dev_keypair()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        keypair.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return keypair
